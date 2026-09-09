from __future__ import annotations

import zipfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from houdocs.errors import HouDocsError


IssueCallback = Callable[[str, str, str | None], None]


@dataclass(frozen=True)
class CachedDocument:
    relative_path: str
    cached_path: Path


def cache_bookish_trees(
    sources: Sequence[Path],
    destination: Path,
    *,
    on_error: IssueCallback | None = None,
) -> list[CachedDocument]:
    resolved_sources = [source.expanduser().resolve() for source in sources]
    for source in resolved_sources:
        if not source.is_dir():
            raise HouDocsError(
                "docs_source_missing",
                f"Documentation source is not a directory: {source}",
            )

    destination = destination.expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    cached_by_relative: dict[str, CachedDocument] = {}

    for source in resolved_sources:
        for source_path in sorted(source.rglob("*.txt")):
            if not source_path.is_file():
                continue
            relative = source_path.relative_to(source).as_posix()
            if relative in cached_by_relative:
                continue
            try:
                data = source_path.read_bytes()
            except OSError as exc:
                _report(
                    on_error,
                    "docs_source_read_error",
                    f"Unable to read Houdini help file: {exc}",
                    relative,
                )
                continue
            cached_by_relative[relative] = _cache_bytes(
                relative=relative,
                data=data,
                destination=destination,
            )

        for archive_path in sorted(source.rglob("*.zip")):
            if not archive_path.is_file():
                continue
            prefix = archive_path.relative_to(source).with_suffix("").as_posix()
            try:
                with zipfile.ZipFile(archive_path) as archive:
                    for member in sorted(archive.namelist()):
                        member_path = PurePosixPath(member)
                        if (
                            member_path.is_absolute()
                            or ".." in member_path.parts
                            or member_path.suffix.casefold() != ".txt"
                        ):
                            continue
                        relative = PurePosixPath(prefix, member_path).as_posix()
                        if relative in cached_by_relative:
                            continue
                        try:
                            data = archive.read(member)
                        except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
                            _report(
                                on_error,
                                "docs_archive_member_error",
                                f"Unable to read Houdini help archive member: {exc}",
                                relative,
                            )
                            continue
                        cached_by_relative[relative] = _cache_bytes(
                            relative=relative,
                            data=data,
                            destination=destination,
                        )
            except (OSError, zipfile.BadZipFile) as exc:
                relative_archive = archive_path.relative_to(source).as_posix()
                _report(
                    on_error,
                    "docs_archive_invalid",
                    f"Invalid Houdini help archive: {exc}",
                    relative_archive,
                )

    return [cached_by_relative[key] for key in sorted(cached_by_relative)]


def _cache_bytes(
    *,
    relative: str,
    data: bytes,
    destination: Path,
) -> CachedDocument:
    cached_path = destination / Path(relative)
    cached_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = cached_path.with_suffix(cached_path.suffix + ".tmp")
    temporary.write_bytes(data)
    temporary.replace(cached_path)
    return CachedDocument(relative_path=relative, cached_path=cached_path)


def _report(
    callback: IssueCallback | None,
    kind: str,
    detail: str,
    document: str | None,
) -> None:
    if callback is not None:
        callback(kind, detail, document)
