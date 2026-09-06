from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from houdocs.config import default_data_root, validate_version


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
