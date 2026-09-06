from __future__ import annotations

import sqlite3
import zipfile
from pathlib import Path

from houdocs.docs.bookish import BookishDocumentParser
from houdocs.docs.index import DocumentIndexer, classify_document
from houdocs.docs.repository import DocumentRepository
from houdocs.docs.source import cache_bookish_trees


def test_cache_bookish_trees_preserves_help_root_priority(tmp_path: Path) -> None:
    high = tmp_path / "high"
    low = tmp_path / "low"
    high.mkdir()
    low.mkdir()
    with zipfile.ZipFile(high / "vex.zip", "w") as archive:
        archive.writestr("functions/noise.txt", "= High Noise =\n")
    with zipfile.ZipFile(low / "vex.zip", "w") as archive:
        archive.writestr("functions/noise.txt", "= Low Noise =\n")
        archive.writestr("functions/random.txt", "= Random =\n")

    cached = cache_bookish_trees((high, low), tmp_path / "cache")

    assert [item.relative_path for item in cached] == [
        "vex/functions/noise.txt",
        "vex/functions/random.txt",
    ]
    assert cached[0].source_path == high / "vex.zip"
    assert cached[0].cached_path.read_text(encoding="utf-8") == "= High Noise =\n"


def test_loose_txt_precedes_archive_member_in_same_root(tmp_path: Path) -> None:
    source = tmp_path / "help"
    source.mkdir()
    (source / "commands").mkdir()
    (source / "commands" / "opadd.txt").write_text("= Loose =\n", encoding="utf-8")
    with zipfile.ZipFile(source / "commands.zip", "w") as archive:
        archive.writestr("opadd.txt", "= Archived =\n")

    cached = cache_bookish_trees((source,), tmp_path / "cache")

    assert [item.relative_path for item in cached] == ["commands/opadd.txt"]
    assert cached[0].source_member is None
    assert cached[0].cached_path.read_text(encoding="utf-8") == "= Loose =\n"


def test_invalid_archive_is_reported_and_other_documents_continue(tmp_path: Path) -> None:
    source = tmp_path / "help"
    source.mkdir()
    (source / "credits.txt").write_text("= Credits =\n", encoding="utf-8")
    (source / "broken.zip").write_bytes(b"not a zip")
    issues: list[tuple[str, str, str | None]] = []

    cached = cache_bookish_trees(
        (source,),
        tmp_path / "cache",
        on_error=lambda kind, detail, document: issues.append((kind, detail, document)),
    )

    assert [item.relative_path for item in cached] == ["credits.txt"]
    assert issues[0][0] == "docs_archive_invalid"
    assert issues[0][2] == "broken.zip"


def test_bookish_parser_preserves_headings_anchors_and_at_sections() -> None:
    parser = BookishDocumentParser()
    source = '''= Geometry =
#context: sop
"""Geometry overview."""

== Noise == (noise)
Add noise.
{{{
#!vex
v@P += noise(v@P);
}}}

@parameters
::Amplitude:
    Controls noise strength.
'''

    sections = parser.parse(source, document_id="doc", kind="vex")

    assert sections[1].section_id == "doc#noise"
    assert sections[2].section_id == "doc#parameters"
    assert sections[1].heading_path == ("Geometry", "Noise")
    assert sections[2].heading_path == ("Geometry", "Parameters")
    assert sections[1].text.startswith("Geometry\nNoise\n")
    assert "v@P += noise(v@P);" in sections[1].text
    assert sections[1].metadata["bookish"]["context"] == "sop"


def test_classify_document_domains() -> None:
    assert classify_document("hom/hou/Node.txt") == "hom"
    assert classify_document("vex/functions/noise.txt") == "vex"
    assert classify_document("nodes/sop/attribwrangle.txt") == "node-doc"
    assert classify_document("examples/nodes/sop/attribwrangle/Example.txt") == "example"
    assert classify_document("basics/network.txt") == "concept"


def test_document_indexer_is_incremental_and_removes_stale_documents(tmp_path: Path) -> None:
    source = tmp_path / "help"
    source.mkdir()
    document_path = source / "concept.txt"
    document_path.write_text("= Concept =\n\nOne.\n", encoding="utf-8")
    repository = DocumentRepository(tmp_path / "docs.db")
    indexer = DocumentIndexer(
        repository=repository,
        parser=BookishDocumentParser(),
        cache_directory=tmp_path / "cache",
    )

    first = indexer.index_all(source, houdini_version="22.0.429")
    second = indexer.index_all(source, houdini_version="22.0.429")
    document_path.write_text("= Concept =\n\nTwo.\n", encoding="utf-8")
    third = indexer.index_all(source, houdini_version="22.0.429")
    document_path.unlink()
    fourth = indexer.index_all(source, houdini_version="22.0.429")

    assert first == {"total": 1, "indexed": 1, "skipped": 0, "removed": 0, "failed": 0}
    assert second == {"total": 1, "indexed": 0, "skipped": 1, "removed": 0, "failed": 0}
    assert third == {"total": 1, "indexed": 1, "skipped": 0, "removed": 0, "failed": 0}
    assert fourth == {"total": 0, "indexed": 0, "skipped": 0, "removed": 1, "failed": 0}
    assert repository.all_documents() == []


def test_parse_failure_is_reported_and_does_not_leave_old_body(tmp_path: Path) -> None:
    class FailingParser(BookishDocumentParser):
        def parse(self, source: str, *, document_id: str, kind: str):
            raise ValueError("broken bookish")

    source = tmp_path / "help"
    source.mkdir()
    document_path = source / "page.txt"
    document_path.write_text("= Page =\n\nGood.\n", encoding="utf-8")
    repository = DocumentRepository(tmp_path / "docs.db")
    good = DocumentIndexer(
        repository=repository,
        parser=BookishDocumentParser(),
        cache_directory=tmp_path / "cache",
    )
    good.index_all(source, houdini_version="22.0.429")
    document_path.write_text("changed", encoding="utf-8")
    issues: list[tuple[str, str, str | None]] = []
    failing = DocumentIndexer(
        repository=repository,
        parser=FailingParser(),
        cache_directory=tmp_path / "cache",
    )

    result = failing.index_all(
        source,
        houdini_version="22.0.429",
        on_error=lambda kind, detail, document: issues.append((kind, detail, document)),
    )

    assert result["failed"] == 1
    assert repository.all_documents() == []
    assert issues == [("bookish_parse_error", "ValueError: broken bookish", "page.txt")]


def test_docs_database_contains_documents_and_sections_schema(tmp_path: Path) -> None:
    repository = DocumentRepository(tmp_path / "docs.db")
    assert repository.all_documents() == []
    with sqlite3.connect(tmp_path / "docs.db") as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
        }
    assert {"documents", "sections"}.issubset(tables)
