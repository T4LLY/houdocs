from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from houdocs.config import default_data_root, validate_version
from houdocs.errors import HouDocsError


@dataclass(frozen=True)
class VersionPaths:
    root: Path
    version: str
    database: Path
    search_database: Path
    docs: Path
    reports: Path

    @classmethod
    def for_version(
        cls,
        version: str,
        *,
        data_root: Path | None = None,
    ) -> "VersionPaths":
        normalized = validate_version(version)
        root = (data_root or default_data_root()).expanduser().resolve()
        version_root = root / "versions" / normalized
        return cls(
            root=version_root,
            version=normalized,
            database=version_root / "docs.db",
            search_database=version_root / "search.db",
            docs=version_root / "docs",
            reports=version_root / "reports",
        )

    def ensure(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.docs.mkdir(parents=True, exist_ok=True)
        self.reports.mkdir(parents=True, exist_ok=True)


def resolve_initialized_version(
    requested: str | None,
    *,
    data_root: Path | None = None,
) -> str:
    root = (data_root or default_data_root()).expanduser().resolve() / "versions"
    if not root.is_dir():
        raise HouDocsError("docs_index_missing", "Run houdocs init first.")

    available: list[tuple[tuple[int, ...], str]] = []
    for child in root.iterdir():
        if not child.is_dir() or not (child / "docs.db").is_file():
            continue
        try:
            normalized = validate_version(child.name)
        except HouDocsError:
            continue
        available.append((tuple(int(part) for part in normalized.split(".")), normalized))

    if not available:
        raise HouDocsError("docs_index_missing", "Run houdocs init first.")

    if requested is None:
        return max(available)[1]

    normalized = validate_version(requested)
    parts = tuple(int(part) for part in normalized.split("."))
    if len(parts) == 3:
        if any(version == normalized for _key, version in available):
            return normalized
        raise HouDocsError(
            "docs_index_missing",
            f"HouDocs index is not initialized for Houdini {normalized}.",
        )

    matches = [(key, version) for key, version in available if key[:2] == parts[:2]]
    if not matches:
        raise HouDocsError(
            "docs_index_missing",
            f"HouDocs index is not initialized for Houdini {normalized}.",
        )
    return max(matches)[1]
