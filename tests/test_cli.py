from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

import pytest
from typer.testing import CliRunner

from houdocs.cli import _init_summary, app
from houdocs.db.schema import initialize_docs_database
from houdocs.docs.repository import DocumentRepository
from houdocs.node.models import RuntimeNodeSnapshot, RuntimeParameterSnapshot
from houdocs.paths import VersionPaths


def _runtime_nodes(rows: tuple[dict[str, object], ...]) -> tuple[RuntimeNodeSnapshot, ...]:
    result: list[RuntimeNodeSnapshot] = []
    for row in rows:
        parameters = tuple(
            RuntimeParameterSnapshot(
                ordinal=raw.get("parameter_ordinal") if isinstance(raw.get("parameter_ordinal"), int) else None,
                parm_id=str(raw.get("id") or ""),
                label=str(raw.get("label") or ""),
                folder_path=tuple(raw.get("folder_path") or ()),
                parm_type=str(raw.get("type") or ""),
                multiparm=bool(raw.get("is_multiparm")),
            )
            for raw in row.get("parameters", [])
            if isinstance(raw, dict)
        )
        result.append(
            RuntimeNodeSnapshot(
                category=str(row.get("category") or ""),
                internal_name=str(row.get("name") or ""),
                canonical_name=str(row.get("canonical_name") or ""),
                min_inputs=row.get("min_inputs") if isinstance(row.get("min_inputs"), int) else None,
                max_inputs=row.get("max_inputs") if isinstance(row.get("max_inputs"), int) else None,
                max_outputs=row.get("max_outputs") if isinstance(row.get("max_outputs"), int) else None,
                parameters=parameters,
                parameter_error=(
                    str(row["parameter_error"]) if row.get("parameter_error") else None
                ),
            )
        )
    return tuple(result)


runner = CliRunner()


def _docs_repository(database: Path) -> DocumentRepository:
    initialize_docs_database(database)
    return DocumentRepository(database)


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
    for command in ("init", "search", "read", "sections", "node", "hom", "vex"):
        assert command in result.stdout
    assert "python" not in result.stdout


def test_init_exposes_version_but_not_connection_target_options() -> None:
    result = runner.invoke(app, ["init", "--help"])

    assert result.exit_code == 0
    assert "--houdini-version" in result.stdout
    assert "--progress" in result.stdout
    assert "--import-assist" in result.stdout
    assert "--yes" not in result.stdout
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
    _docs_repository(paths.database)

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
    repository = _docs_repository(paths.database)
    DocumentIndexer(
        repository=repository,
        parser=BookishDocumentParser(),
        cache_directory=paths.docs,
        token_counter=len,
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


def test_sections_command_lists_paths_tokens_and_supports_pick(tmp_path: Path) -> None:
    source = tmp_path / "help"
    (source / "nodes" / "lop").mkdir(parents=True)
    (source / "nodes" / "sop").mkdir(parents=True)
    (source / "nodes" / "lop" / "same.txt").write_text(
        "= Same =\n\nLOP.\n\n== Details ==\n\nLOP details.\n",
        encoding="utf-8",
    )
    (source / "nodes" / "sop" / "same.txt").write_text(
        "= Same =\n\nSOP.\n\n== Details ==\n\nSOP details.\n",
        encoding="utf-8",
    )

    from houdocs.docs.bookish import BookishDocumentParser
    from houdocs.docs.index import DocumentIndexer
    from houdocs.paths import VersionPaths

    paths = VersionPaths.for_version("22.0.429")
    paths.ensure()
    DocumentIndexer(
        repository=_docs_repository(paths.database),
        parser=BookishDocumentParser(),
        cache_directory=paths.docs,
        token_counter=len,
    ).index_all(source, houdini_version="22.0.429")

    ambiguous = runner.invoke(app, ["sections", "Same"])
    assert ambiguous.exit_code == 1
    assert json.loads(ambiguous.stdout)["choices"] == ["LOP / Same", "SOP / Same"]

    selected = runner.invoke(app, ["sections", "Same", "--pick", "2"])
    assert selected.exit_code == 0
    payload = json.loads(selected.stdout)
    assert [item["path"] for item in payload["sections"]] == [
        ["Same"],
        ["Details"],
    ]
    assert all(isinstance(item["tokens"], int) for item in payload["sections"])


def test_search_and_reader_commands_do_not_expose_extra_options() -> None:
    search = runner.invoke(app, ["search", "--help"])
    read = runner.invoke(app, ["read", "--help"])
    sections = runner.invoke(app, ["sections", "--help"])
    node = runner.invoke(app, ["node", "--help"])
    hom = runner.invoke(app, ["hom", "--help"])
    vex = runner.invoke(app, ["vex", "--help"])

    assert (
        search.exit_code
        == read.exit_code
        == sections.exit_code
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
    assert "PAGE" in sections.stdout and "--pick" in sections.stdout
    for output in (
        search.stdout,
        read.stdout,
        sections.stdout,
        node.stdout,
        hom.stdout,
        vex.stdout,
    ):
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
        "report": "C:/houdocs/reports/init-report.json",
    }
    assert "issues" not in summary


def test_init_existing_database_requires_explicit_y_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from houdocs.init.runtime import HoudiniInstallation, HoudiniRuntime
    from houdocs.init.service import InitService

    installation_root = Path("/fake/Houdini 22.0.429")
    installation = HoudiniInstallation(
        root=installation_root,
        bin_dir=installation_root / "bin",
        houdini=installation_root / "bin" / "houdini",
        hcommand=installation_root / "bin" / "hcommand",
        version=(22, 0, 429),
    )
    monkeypatch.setattr(
        HoudiniRuntime,
        "select",
        lambda self, requested_version: installation,
    )

    paths = VersionPaths.for_version("22.0.429")
    paths.ensure()
    paths.database.write_bytes(b"existing")

    calls = {"run": 0}

    def fake_run(self, requested_version, *, config, progress):
        del self, requested_version, config, progress
        calls["run"] += 1
        return {
            "houdini_version": "22.0.429",
            "documents": {"total": 0},
            "node": {"documents": 0},
            "python": {"symbols": 0},
            "vex": {"functions": 0},
            "search": {"entries": 0},
            "issue_counts": {"warnings": 0, "errors": 0},
        }

    monkeypatch.setattr(InitService, "run", fake_run)

    rejected = runner.invoke(app, ["init"], input="n\n")
    assert rejected.exit_code == 0
    assert calls["run"] == 0
    assert "houdini_version" not in rejected.stdout
    assert "Continue? [y/N]" in rejected.stderr

    accepted = runner.invoke(app, ["init"], input="y\n")
    assert accepted.exit_code == 0
    assert calls["run"] == 1
    assert "Continue? [y/N]" in accepted.stderr
    payload = json.loads(accepted.stdout.splitlines()[-1])
    assert payload["houdini_version"] == "22.0.429"


def test_init_import_assist_updates_existing_node_metadata_without_cached_sources(
    tmp_path: Path,
) -> None:
    from houdocs.docs.bookish import BookishDocumentParser
    from houdocs.docs.index import DocumentIndexer
    from houdocs.node.index import NodeIndexer
    from houdocs.node.read import NodeReader
    from houdocs.node.repository import NodeRepository

    paths = VersionPaths.for_version("22.0.429")
    paths.ensure()
    source = tmp_path / "help"
    (source / "nodes" / "sop").mkdir(parents=True)
    (source / "nodes" / "sop" / "example.txt").write_text(
        "#type: node\n#context: sop\n#internal: example\n= Example =\n\n"
        "@parameters\nLegacy Label:\n    Documentation.\n",
        encoding="utf-8",
    )

    documents = _docs_repository(paths.database)
    DocumentIndexer(
        repository=documents,
        parser=BookishDocumentParser(),
        cache_directory=paths.docs,
        token_counter=len,
    ).index_all(source, houdini_version="22.0.429")

    runtime_rows = (
        {
            "category": "Sop",
            "name": "example",
            "canonical_name": "Sop/example",
            "parameters": [
                {
                    "parameter_ordinal": 0,
                    "id": "current_name",
                    "label": "Current Label",
                    "folder_path": [],
                    "type": "String",
                    "is_multiparm": False,
                }
            ],
        },
    )
    NodeIndexer(
        documents=documents,
        repository=NodeRepository(paths.database),
        docs_directory=paths.docs,
        report_directory=paths.reports,
    ).index_all(_runtime_nodes(runtime_rows), houdini_version="22.0.429")

    unresolved_path = paths.reports / "node-document-unresolved-22.0.429.json"
    unresolved = json.loads(unresolved_path.read_text(encoding="utf-8"))
    unresolved["overrides"]["parameters"] = [
        {
            "node": "Sop/example",
            "document": "nodes/sop/example.txt",
            "doc_ordinal": 0,
            "parm_ids": ["current_name"],
        }
    ]
    unresolved_path.write_text(
        json.dumps(unresolved, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    assist_report_before = unresolved_path.read_bytes()
    shutil.rmtree(paths.docs)

    assert NodeReader(
        documents=documents,
        repository=NodeRepository(paths.database),
        token_counter=len,
    ).read("Sop/example") == {
        "parameters": [
            {
                "id": "current_name",
                "label": "Current Label",
                "tokens": 0,
                "type": "String",
            },
            {
                "ordinal": 0,
                "label": "Legacy Label",
                "tokens": 14,
            },
        ]
    }
    paths.search_database.write_bytes(b"search-index-sentinel")

    result = runner.invoke(
        app,
        ["init", "--houdini-version", "22.0.429", "--import-assist"],
    )

    assert result.exit_code == 0
    assert result.stdout == "Imported 1 assist overrides.\n"
    assert unresolved_path.read_bytes() == assist_report_before
    assert paths.search_database.read_bytes() == b"search-index-sentinel"
    assert NodeReader(
        documents=_docs_repository(paths.database),
        repository=NodeRepository(paths.database),
        token_counter=len,
    ).read("Sop/example") == {
        "parameters": [
            {
                "id": "current_name",
                "label": "Current Label",
                "tokens": 14,
                "type": "String",
            }
        ]
    }
    metadata_after_first_import = NodeRepository(paths.database).resolve("Sop/example")

    repeated = runner.invoke(
        app,
        ["init", "--houdini-version", "22.0.429", "--import-assist"],
    )

    assert repeated.exit_code == 0
    assert repeated.stdout == "Imported 1 assist overrides.\n"
    assert (
        NodeRepository(paths.database).resolve("Sop/example")
        == metadata_after_first_import
    )


def test_init_confirmation_also_guards_existing_search_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from houdocs.init.runtime import HoudiniInstallation, HoudiniRuntime
    from houdocs.init.service import InitService

    installation_root = Path("/fake/Houdini 22.0.429")
    installation = HoudiniInstallation(
        root=installation_root,
        bin_dir=installation_root / "bin",
        houdini=installation_root / "bin" / "houdini",
        hcommand=installation_root / "bin" / "hcommand",
        version=(22, 0, 429),
    )
    monkeypatch.setattr(
        HoudiniRuntime,
        "select",
        lambda self, requested_version: installation,
    )

    paths = VersionPaths.for_version("22.0.429")
    paths.ensure()
    paths.search_database.write_bytes(b"existing-search")

    calls = {"run": 0}

    def fake_run(self, requested_version, *, config, progress):
        del self, requested_version, config, progress
        calls["run"] += 1
        return {}

    monkeypatch.setattr(InitService, "run", fake_run)

    result = runner.invoke(app, ["init"], input="\n")

    assert result.exit_code == 0
    assert calls["run"] == 0
    assert "Continue? [y/N]" in result.stderr
    assert paths.search_database.read_bytes() == b"existing-search"


def test_init_import_assist_failure_preserves_report_and_node_metadata(
    tmp_path: Path,
) -> None:
    from houdocs.docs.bookish import BookishDocumentParser
    from houdocs.docs.index import DocumentIndexer
    from houdocs.errors import HouDocsError
    from houdocs.init.service import InitService
    from houdocs.node.index import NodeIndexer
    from houdocs.node.repository import NodeRepository

    paths = VersionPaths.for_version("22.0.429")
    paths.ensure()
    source = tmp_path / "help"
    node_source = source / "nodes" / "sop" / "example.txt"
    node_source.parent.mkdir(parents=True)
    node_source.write_text(
        "#type: node\n#context: sop\n#internal: example\n= Example =\n\n"
        "@parameters\nLegacy Label:\n    Documentation.\n",
        encoding="utf-8",
    )

    documents = _docs_repository(paths.database)
    DocumentIndexer(
        repository=documents,
        parser=BookishDocumentParser(),
        cache_directory=paths.docs,
        token_counter=len,
    ).index_all(source, houdini_version="22.0.429")
    runtime_rows = (
        {
            "category": "Sop",
            "name": "example",
            "canonical_name": "Sop/example",
            "parameters": [],
        },
    )
    NodeIndexer(
        documents=documents,
        repository=NodeRepository(paths.database),
        docs_directory=paths.docs,
        report_directory=paths.reports,
    ).index_all(_runtime_nodes(runtime_rows), houdini_version="22.0.429")

    unresolved_path = paths.reports / "node-document-unresolved-22.0.429.json"
    unresolved = json.loads(unresolved_path.read_text(encoding="utf-8"))
    unresolved["overrides"]["parameters"] = [
        {
            "document": "nodes/sop/example.txt",
            "doc_ordinal": 0,
            "parm_ids": ["missing"],
        }
    ]
    unresolved_path.write_text(json.dumps(unresolved), encoding="utf-8")
    report_before = unresolved_path.read_bytes()
    metadata_before = NodeRepository(paths.database).resolve("Sop/example")

    with pytest.raises(HouDocsError) as raised:
        InitService().import_assist("22.0.429")

    assert raised.value.error.code == "node_assist_target_missing"
    assert unresolved_path.read_bytes() == report_before
    assert NodeRepository(paths.database).resolve("Sop/example") == metadata_before


def test_node_command_lists_token_costs_and_reads_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import houdocs.cli as cli_module
    from houdocs.docs.models import Document
    from houdocs.node.models import (
        NodeParameter,
        NodeParameterDoc,
        NodeParameterLink,
        NodeTypeDocument,
    )
    from houdocs.node.repository import NodeRepository

    paths = VersionPaths.for_version("22.0.429")
    paths.ensure()
    documents = _docs_repository(paths.database)
    documents.replace_document(
        Document(
            "node-doc",
            "Example",
            "nodes/sop/example.txt",
            "node-doc",
            "22.0.429",
            "Example body",
        ),
        [],
    )
    NodeRepository(paths.database).replace_all(
        [
            (
                NodeTypeDocument(
                    "Sop/example",
                    "node-doc",
                    "sop",
                    None,
                    "example",
                    None,
                    "Sop",
                    "Sop/example",
                    1000,
                    "houdini",
                    None,
                ),
                (
                    NodeParameter(
                        "p0",
                        "Sop/example",
                        0,
                        "strength",
                        "Strength",
                        (),
                        "parmTemplateType.Float",
                        False,
                        True,
                    ),
                ),
                (
                    NodeParameterDoc(
                        "d0",
                        "Sop/example",
                        0,
                        "Strength",
                        (),
                        "Amount.",
                        (),
                        None,
                    ),
                ),
                (NodeParameterLink("d0", "p0", 0, "houdini-label"),),
                (),
                (),
            )
        ]
    )
    monkeypatch.setattr(cli_module, "count_openai_tokens", len)

    listing = runner.invoke(app, ["node", "sop/example"])
    detail = runner.invoke(app, ["node", "sop/example/parameters/strength"])

    assert listing.exit_code == 0
    assert json.loads(listing.stdout) == {
        "parameters": [
            {"id": "strength", "label": "Strength", "tokens": 7, "type": "Float"}
        ]
    }
    assert detail.exit_code == 0
    assert json.loads(detail.stdout) == {"description": "Amount."}
