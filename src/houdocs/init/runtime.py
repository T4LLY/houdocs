from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

from houdocs.errors import HouDocsError
from houdocs.init import probe as runtime_probe
from houdocs.init.probe import RuntimeSnapshot


_VERSION_RE = re.compile(r"(?:Houdini\s*)?(\d+)\.(\d+)(?:\.(\d+))?", re.IGNORECASE)


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


class HoudiniRuntime:
    def __init__(
        self,
        *,
        popen: Callable[..., subprocess.Popen[bytes]] = subprocess.Popen,
        run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        startup_timeout_seconds: float = 30.0,
        startup_poll_interval_seconds: float = 0.5,
        command_timeout_seconds: float = 15.0,
    ) -> None:
        self._popen = popen
        self._run = run
        self._sleep = sleep
        self._monotonic = monotonic
        self.startup_timeout_seconds = startup_timeout_seconds
        self.startup_poll_interval_seconds = startup_poll_interval_seconds
        self.command_timeout_seconds = command_timeout_seconds

    def select(self, requested_version: str | None) -> HoudiniInstallation:
        return select_houdini_installation(requested_version)

    def probe(
        self,
        installation: HoudiniInstallation,
        *,
        requested_version: str | None,
    ) -> RuntimeSnapshot:
        port = _unused_loopback_port()
        with tempfile.TemporaryDirectory(prefix="houdocs-init-") as temporary:
            root = Path(temporary)
            startup_script = root / "openport.cmd"
            probe_script = root / "probe.py"
            result_path = root / "runtime.json"
            startup_script.write_text(f"openport -q {port}\n", encoding="utf-8")
            probe_script.write_text(
                runtime_probe.build_probe_script(result_path),
                encoding="utf-8",
            )

            process = self._launch(installation, startup_script)
            try:
                self._wait_for_probe(
                    installation,
                    port=port,
                    probe_script=probe_script,
                    result_path=result_path,
                    process=process,
                )
            finally:
                _terminate_process(process)
            snapshot = runtime_probe.load_probe_snapshot(result_path)

        _validate_requested_runtime_version(requested_version, snapshot.houdini_version)
        return snapshot

    def _launch(
        self,
        installation: HoudiniInstallation,
        startup_script: Path,
    ) -> subprocess.Popen[bytes]:
        try:
            return self._popen(
                [str(installation.houdini), str(startup_script)],
                cwd=str(installation.root),
                env=subprocess_environment_for(installation.houdini),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            )
        except OSError as exc:
            raise HouDocsError(
                "houdini_launch_failed",
                f"Failed to launch Houdini {installation.version_string}.",
                detail=str(exc),
            ) from exc

    def _wait_for_probe(
        self,
        installation: HoudiniInstallation,
        *,
        port: int,
        probe_script: Path,
        result_path: Path,
        process: subprocess.Popen[bytes],
    ) -> None:
        deadline = self._monotonic() + self.startup_timeout_seconds
        last_detail: str | None = None
        while self._monotonic() < deadline:
            return_code = process.poll()
            if return_code not in {None, 0}:
                raise HouDocsError(
                    "houdini_launch_failed",
                    f"Houdini exited before initialization probe completed (status {return_code}).",
                )

            result_path.unlink(missing_ok=True)
            completed = self._execute_probe(installation, port, probe_script)
            if completed.returncode == 0 and result_path.is_file():
                return

            last_detail = _clip((completed.stderr or completed.stdout or "").strip()) or None
            self._sleep(self.startup_poll_interval_seconds)

        raise HouDocsError(
            "houdini_startup_timeout",
            "Houdini was launched but the initialization session did not become reachable.",
            detail=last_detail,
        )

    def _execute_probe(
        self,
        installation: HoudiniInstallation,
        port: int,
        probe_script: Path,
    ) -> subprocess.CompletedProcess[str]:
        command = f'python "{probe_script.resolve().as_posix().replace(chr(34), chr(92) + chr(34))}"'
        try:
            return self._run(
                [str(installation.hcommand), str(port), command],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.command_timeout_seconds,
                env=subprocess_environment_for(installation.hcommand),
            )
        except subprocess.TimeoutExpired as exc:
            return subprocess.CompletedProcess(
                args=exc.cmd,
                returncode=124,
                stdout=exc.stdout or "",
                stderr=exc.stderr or "",
            )
        except OSError as exc:
            raise HouDocsError(
                "hcommand_failed",
                f"Failed to execute hcommand: {installation.hcommand}",
                detail=str(exc),
            ) from exc


def subprocess_environment_for(executable: str | Path) -> dict[str, str]:
    env = os.environ.copy()
    path = Path(executable).expanduser()
    if not path.is_absolute() or path.parent.name.casefold() != "bin":
        return env

    bin_dir = path.parent.resolve()
    root = bin_dir.parent
    env.setdefault("HFS", str(root))
    current_path = env.get("PATH", "")
    parts = [part for part in current_path.split(os.pathsep) if part]
    if str(bin_dir).casefold() not in {part.casefold() for part in parts}:
        env["PATH"] = str(bin_dir) + (os.pathsep + current_path if current_path else "")
    return env


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

    return HoudiniInstallation(
        root=resolved,
        bin_dir=bin_dir,
        houdini=houdini,
        hcommand=hcommand,
        version=_version_from_path(resolved),
    )


def _version_from_path(path: Path) -> tuple[int, int, int]:
    for value in (path.name, str(path)):
        match = _VERSION_RE.search(value)
        if match:
            return tuple(int(part or 0) for part in match.groups())  # type: ignore[return-value]
    return (0, 0, 0)


def _unused_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _validate_requested_runtime_version(requested: str | None, actual: str) -> None:
    if requested is None:
        return
    requested_parts = requested.split(".")
    actual_parts = actual.split(".")
    if actual_parts[: len(requested_parts)] != requested_parts:
        raise HouDocsError(
            "houdini_version_mismatch",
            f"Requested Houdini {requested}, but runtime reported {actual}.",
        )


def _terminate_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        process.terminate()
        process.wait(timeout=5)
        return
    except (OSError, subprocess.TimeoutExpired):
        pass
    try:
        process.kill()
        process.wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        pass


def _clip(value: str, limit: int = 4096) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + "…"
