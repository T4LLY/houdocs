from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path
from types import TracebackType

from houdocs.errors import HouDocsError
from houdocs.paths import VersionPaths


class InitStaging:
    """Own the temporary artifacts and atomic promotion for one init run."""

    def __init__(self, paths: VersionPaths) -> None:
        self.paths = paths
        self.database = _staging_database(paths.database)
        self.search_database = _staging_database(paths.search_database)
        self.docs = paths.root / ".init-staging-docs"
        self.reports = paths.root / ".init-staging-reports"

    def __enter__(self) -> "InitStaging":
        self.prepare()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc, traceback
        self.discard()

    def prepare(self) -> None:
        for path in (
            *_sqlite_family(self.database),
            *_sqlite_family(self.search_database),
        ):
            _remove_path(path)
        _remove_path(self.docs)
        _remove_path(self.reports)
        self.docs.mkdir(parents=True, exist_ok=True)
        self.reports.mkdir(parents=True, exist_ok=True)

    def discard(self) -> None:
        for path in (
            *_sqlite_family(self.database),
            *_sqlite_family(self.search_database),
        ):
            try:
                _remove_path(path)
            except OSError:
                pass
        for path in (self.docs, self.reports):
            try:
                _remove_path(path)
            except OSError:
                pass

    def promote(self, *, artifacts: tuple[tuple[Path, Path], ...]) -> None:
        _checkpoint_sqlite_database(self.database)
        _checkpoint_sqlite_database(self.search_database)

        staged_pairs = (
            (self.database, self.paths.database),
            (self.search_database, self.paths.search_database),
            (self.docs, self.paths.docs),
            *artifacts,
        )
        for staged, _final in staged_pairs:
            if not staged.exists():
                raise HouDocsError(
                    "init_staging_incomplete",
                    f"Initialization staging artifact is missing: {staged}",
                )

        final_paths: list[Path] = []
        for final in (self.paths.database, self.paths.search_database):
            final_paths.extend(_sqlite_family(final))
        final_paths.extend(final for _staged, final in staged_pairs[2:])

        backup_pairs: list[tuple[Path, Path]] = []
        for final in final_paths:
            backup = _backup_path(final)
            if backup.exists():
                raise HouDocsError(
                    "init_recovery_required",
                    f"Previous init backup still exists: {backup}",
                )
            if final.exists():
                backup_pairs.append((backup, final))

        promoted: list[Path] = []
        try:
            for backup, final in backup_pairs:
                final.replace(backup)
            for staged, final in staged_pairs:
                staged.replace(final)
                promoted.append(final)
        except BaseException:
            for final in reversed(promoted):
                try:
                    _remove_path(final)
                except OSError:
                    pass
            for backup, final in reversed(backup_pairs):
                if backup.exists():
                    backup.replace(final)
            raise
        else:
            for backup, _final in backup_pairs:
                try:
                    _remove_path(backup)
                except OSError:
                    # The new initialized state is already committed. A leftover
                    # backup is safer than turning cleanup failure into a false init
                    # failure; the next init will report init_recovery_required.
                    pass


def _staging_database(path: Path) -> Path:
    return Path(str(path) + ".init-new")


def _sqlite_family(path: Path) -> tuple[Path, ...]:
    return (
        path,
        Path(str(path) + "-wal"),
        Path(str(path) + "-shm"),
        Path(str(path) + "-journal"),
    )


def _remove_path(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


def _checkpoint_sqlite_database(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        connection.close()
    for sidecar in _sqlite_family(path)[1:]:
        sidecar.unlink(missing_ok=True)


def _backup_path(path: Path) -> Path:
    return Path(str(path) + ".init-backup")
