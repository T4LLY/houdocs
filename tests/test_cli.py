from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from typer.testing import CliRunner

from houdocs.cli import _init_summary, app
from houdocs.docs.repository import DocumentRepository
from houdocs.paths import VersionPaths


runner = CliRunner()


@pytest.fixture(autouse=True)
def isolate_cli_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import houdocs.config as config_module
    import houdocs.paths as paths_module

    monkeypatch.setattr(
        config_module,
        "default_config_path",
        lambda: tmp_path / "config.toml",
    )
    monkeypatch.setattr(
        config_module,
        "local_config_path",
        lambda cwd=None: tmp_path / ".houdocs.toml",
    )
    monkeypatch.setattr(
        paths_module,
        "default_data_root",
        lambda: tmp_path / "data",
    )


def test_cli_exposes_only_the_planned_top_level_commands() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    for command in ("init", "search", "read", "node", "hom", "vex"):
        assert command in result.stdout
    assert "python" not in result.stdout


def test_init_exposes_version_but_not_connection_target_options() -> None:
    result = runner.invoke(app, ["init", "--help"])

    assert result.exit_code == 0
    assert "--houdini-version" in result.stdout
    assert "--progress" in result.stdout
    assert "--host" not in result.stdout
    assert "--port" not in result.stdout
    assert "--executable" not in result.stdout


def test_offline_command_without_index_fails_with_machine_readable_error() -> None:
    result = runner.invoke(app, ["search", "packed primitive"])

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["error"] is True
    assert payload["code"] == "docs_index_missing"


def test_offline_command_serializes_raw_sqlite_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = VersionPaths.for_version("22.0.429")
    paths.ensure()
    DocumentRepository(paths.database)

    def fail_read(self, title):
        del self, title
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(DocumentRepository, "documents_for_title", fail_read)

    result = runner.invoke(app, ["read", "Page"])

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["code"] == "docs_database_error"
    assert payload["detail"] == "database is locked"


def test_ambiguous_read_error_emits_native_choices(tmp_path: Path) -> None:
    source = tmp_path / "help"
    (source / "nodes" / "lop").mkdir(parents=True)
    (source / "nodes" / "sop").mkdir(parents=True)
    (source / "nodes" / "lop" / "copytopoints.txt").write_text(
        "= Copy to Points =\n\nLOP.\n", encoding="utf-8"
    )
    (source / "nodes" / "sop" / "copytopoints.txt").write_text(
        "= Copy to Points =\n\nSOP.\n", encoding="utf-8"
    )

    from houdocs.docs.bookish import BookishDocumentParser
    from houdocs.docs.index import DocumentIndexer
    from houdocs.paths import VersionPaths

    paths = VersionPaths.for_version("22.0.429")
    paths.ensure()
    repository = DocumentRepository(paths.database)
    DocumentIndexer(
        repository=repository,
        parser=BookishDocumentParser(),
        cache_directory=paths.docs,
    ).index_all(source, houdini_version="22.0.429")

    result = runner.invoke(app, ["read", "Copy to Points"])

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload == {
        "error": True,
        "code": "document_ambiguous",
        "message": "Document title is ambiguous: Copy to Points. Re-run with --pick N.",
        "choices": ["LOP / Copy to Points", "SOP / Copy to Points"],
    }


def test_search_and_reader_commands_do_not_expose_extra_options() -> None:
    search = runner.invoke(app, ["search", "--help"])
    read = runner.invoke(app, ["read", "--help"])
    node = runner.invoke(app, ["node", "--help"])
    hom = runner.invoke(app, ["hom", "--help"])
    vex = runner.invoke(app, ["vex", "--help"])

    assert (
        search.exit_code
        == read.exit_code
        == node.exit_code
        == hom.exit_code
        == vex.exit_code
        == 0
    )
    assert "QUERY" in search.stdout
    assert "--domain" in search.stdout
    assert "node" in search.stdout
    assert "vex" in search.stdout
    assert "hom" in search.stdout
    assert "document" in search.stdout
    assert "PAGE" in read.stdout and "[SECTION]" in read.stdout
    assert "--pick" in read.stdout
    for output in (search.stdout, read.stdout, node.stdout, hom.stdout, vex.stdout):
        assert "--houdini-version" not in output
        assert "--top-k" not in output
        assert "--rebuild" not in output


def test_init_summary_omits_full_issue_details() -> None:
    summary = _init_summary(
        {
            "houdini_version": "22.0.429",
            "documents": {"total": 11731},
            "node": {"documents": 4846},
            "python": {"symbols": 35},
            "vex": {"functions": 932},
            "search": {"entries": 40213},
            "issue_counts": {"warnings": 3895, "errors": 2},
            "issues": [{"kind": "node_parameter_unresolved"}],
            "artifacts": {"report": "C:/houdocs/reports/init-report.json"},
        }
    )

    assert summary == {
        "houdini_version": "22.0.429",
        "documents": 11731,
        "node_documents": 4846,
        "python_symbols": 35,
        "vex_functions": 932,
        "search_entries": 40213,
        "warnings": 3895,
        "errors": 2,
    }
    assert "issues" not in summary
