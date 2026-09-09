from __future__ import annotations

import sqlite3
import zipfile
from pathlib import Path

from houdocs.db.schema import initialize_docs_database
from houdocs.docs.bookish import BookishDocumentParser
from houdocs.docs.index import DocumentIndexer, classify_document
from houdocs.docs.repository import DocumentRepository
from houdocs.docs.source import cache_bookish_trees


def _repository(database: Path) -> DocumentRepository:
    initialize_docs_database(database)
    return DocumentRepository(database)


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


def test_invalid_archive_is_reported_and_other_documents_continue(
    tmp_path: Path,
) -> None:
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
    assert (
        classify_document("examples/nodes/sop/attribwrangle/Example.txt") == "example"
    )
    assert classify_document("basics/network.txt") == "concept"


def test_document_indexer_indexes_every_cached_document(tmp_path: Path) -> None:
    source = tmp_path / "help"
    source.mkdir()
    document_path = source / "concept.txt"
    document_path.write_text("= Concept =\n\nOne.\n", encoding="utf-8")
    repository = _repository(tmp_path / "docs.db")
    indexer = DocumentIndexer(
        repository=repository,
        parser=BookishDocumentParser(),
        cache_directory=tmp_path / "cache",
        token_counter=len,
    )

    first = indexer.index_all(source, houdini_version="22.0.429")
    document_path.write_text("= Concept =\n\nTwo.\n", encoding="utf-8")
    second = indexer.index_all(source, houdini_version="22.0.429")

    assert first == {"total": 1, "indexed": 1, "failed": 0}
    assert second == {"total": 1, "indexed": 1, "failed": 0}
    assert "Two." in repository.all_sections()[0].text


def test_parse_failure_is_reported_without_partial_document(tmp_path: Path) -> None:
    class FailingParser(BookishDocumentParser):
        def parse(self, source: str, *, document_id: str, kind: str):
            raise ValueError("broken bookish")

    source = tmp_path / "help"
    source.mkdir()
    document_path = source / "page.txt"
    document_path.write_text("broken", encoding="utf-8")
    repository = _repository(tmp_path / "docs.db")
    issues: list[tuple[str, str, str | None]] = []
    failing = DocumentIndexer(
        repository=repository,
        parser=FailingParser(),
        cache_directory=tmp_path / "cache",
        token_counter=len,
    )

    result = failing.index_all(
        source,
        houdini_version="22.0.429",
        on_error=lambda kind, detail, document: issues.append((kind, detail, document)),
    )

    assert result["failed"] == 1
    assert repository.all_documents() == []
    assert issues == [("bookish_parse_error", "ValueError: broken bookish", "page.txt")]


def test_initialize_docs_database_contains_documents_and_sections_schema(tmp_path: Path) -> None:
    repository = _repository(tmp_path / "docs.db")
    assert repository.all_documents() == []
    with sqlite3.connect(tmp_path / "docs.db") as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
        }
        section_columns = {
            row[1]: row
            for row in connection.execute("PRAGMA table_info(sections)")
        }
    assert {"documents", "sections"}.issubset(tables)
    assert "token_count" in section_columns
    assert section_columns["token_count"][3] == 1


def test_document_indexer_persists_injected_token_count(tmp_path: Path) -> None:
    source = tmp_path / "help"
    source.mkdir()
    (source / "page.txt").write_text(
        "= Page =\n\nIntro.\n\n== Details ==\n\nMore.\n",
        encoding="utf-8",
    )
    repository = _repository(tmp_path / "docs.db")
    seen: list[str] = []

    def count_tokens(text: str) -> int:
        seen.append(text)
        return 1000 + len(seen)

    DocumentIndexer(
        repository=repository,
        parser=BookishDocumentParser(),
        cache_directory=tmp_path / "cache",
        token_counter=count_tokens,
    ).index_all(source)

    document = repository.documents_for_title("Page")[0]
    sections = repository.sections_for_document(document.document_id)
    assert [section.token_count for section in sections] == [1001, 1002]
    assert seen == [section.text for section in sections]


def test_document_indexer_reports_bounded_progress(tmp_path: Path) -> None:
    source = tmp_path / "help"
    source.mkdir()
    (source / "a.txt").write_text("= A =\n", encoding="utf-8")
    (source / "b.txt").write_text("= B =\n", encoding="utf-8")
    progress: list[tuple[int, int]] = []
    indexer = DocumentIndexer(
        repository=_repository(tmp_path / "docs.db"),
        parser=BookishDocumentParser(),
        cache_directory=tmp_path / "cache",
        token_counter=len,
    )

    indexer.index_all(
        source, progress=lambda current, total: progress.append((current, total))
    )

    assert progress == [(0, 2), (1, 2), (2, 2)]
