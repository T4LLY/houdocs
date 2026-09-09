from __future__ import annotations

import os
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

from houdocs.errors import HouDocsError
from houdocs.houdini.session import HoudiniSession


_VERSION_RE = re.compile(r"(?:Houdini\s*)?(\d+)\.(\d+)(?:\.(\d+))?", re.IGNORECASE)
_VERSION_HEADER_RE = re.compile(
    r'^\s*#define\s+SYS_VERSION_FULL\s+"(\d+)\.(\d+)\.(\d+)"',
    re.MULTILINE,
)


@dataclass(frozen=True)
class HoudiniInstallation:
    root: Path
    bin_dir: Path
    houdini: Path
    hcommand: Path
    version: tuple[int, int, int]

    @property
    def version_string(self) -> str:
        return ".".join(str(part) for part in self.version)


class HoudiniRuntime:
    """Select installed Houdini builds and create reusable local sessions."""

    def __init__(
        self,
        *,
        session_factory: Callable[[HoudiniInstallation], HoudiniSession] | None = None,
    ) -> None:
        self._session_factory = session_factory or HoudiniSession

    def select(self, requested_version: str | None) -> HoudiniInstallation:
        return select_houdini_installation(requested_version)

    def session(self, installation: HoudiniInstallation) -> HoudiniSession:
        return self._session_factory(installation)


def discover_houdini_installations(
    *,
    environ: Mapping[str, str] | None = None,
    platform: str | None = None,
) -> tuple[HoudiniInstallation, ...]:
    env = os.environ if environ is None else environ
    platform_name = sys.platform if platform is None else platform
    roots: list[Path] = []

    hfs = env.get("HFS")
    if hfs:
        roots.append(Path(hfs))

    if platform_name.startswith("win"):
        program_files = env.get("ProgramFiles")
        if program_files is None and environ is None:
            program_files = r"C:\Program Files"
        if program_files:
            sidefx_root = Path(program_files) / "Side Effects Software"
            if sidefx_root.is_dir():
                roots.extend(sidefx_root.glob("Houdini*"))
    elif platform_name.startswith("linux"):
        roots.extend(Path("/opt").glob("hfs*"))

    path_hcommand = shutil.which("hcommand", path=env.get("PATH"))
    if path_hcommand:
        roots.append(Path(path_hcommand).resolve().parent.parent)

    path_houdini = shutil.which("houdini", path=env.get("PATH"))
    if path_houdini:
        candidate = Path(path_houdini).resolve()
        suffix = ".exe" if platform_name.startswith("win") else ""
        if (candidate.parent / f"hcommand{suffix}").is_file():
            roots.append(candidate.parent.parent)

    unique: dict[Path, HoudiniInstallation] = {}
    for root in roots:
        installation = _installation_from_root(root, platform_name)
        if installation is not None:
            unique[installation.root] = installation

    return tuple(
        sorted(
            unique.values(),
            key=lambda item: (item.version, str(item.root).casefold()),
            reverse=True,
        )
    )


def select_houdini_installation(
    requested_version: str | None,
    *,
    installations: tuple[HoudiniInstallation, ...] | None = None,
) -> HoudiniInstallation:
    available = installations if installations is not None else discover_houdini_installations()
    if not available:
        raise HouDocsError(
            "houdini_installation_not_found",
            "Unable to locate a Houdini installation.",
        )

    if requested_version is None:
        return available[0]

    requested = tuple(int(part) for part in requested_version.split("."))
    matches = [
        installation
        for installation in available
        if installation.version[: len(requested)] == requested
    ]
    if matches:
        return matches[0]

    versions = ", ".join(item.version_string for item in available)
    raise HouDocsError(
        "houdini_version_not_found",
        f"Houdini {requested_version} is not installed.",
        detail=f"Available versions: {versions}",
    )


def _installation_from_root(root: Path, platform_name: str) -> HoudiniInstallation | None:
    try:
        resolved = root.expanduser().resolve()
    except OSError:
        return None
    if not resolved.is_dir():
        return None

    suffix = ".exe" if platform_name.startswith("win") else ""
    bin_dir = resolved / "bin"
    hcommand = bin_dir / f"hcommand{suffix}"
    houdini = bin_dir / f"houdini{suffix}"
    if not hcommand.is_file() or not houdini.is_file():
        return None

    version = _version_from_installation(resolved)
    if version is None:
        return None

    return HoudiniInstallation(
        root=resolved,
        bin_dir=bin_dir,
        houdini=houdini,
        hcommand=hcommand,
        version=version,
    )


def _version_from_installation(root: Path) -> tuple[int, int, int] | None:
    header = root / "toolkit" / "include" / "SYS" / "SYS_Version.h"
    try:
        text = header.read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    match = _VERSION_HEADER_RE.search(text)
    if match:
        return tuple(int(part) for part in match.groups())  # type: ignore[return-value]

    match = _VERSION_RE.search(root.name)
    if match:
        return tuple(int(part or 0) for part in match.groups())  # type: ignore[return-value]
    return None
