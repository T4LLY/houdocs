from __future__ import annotations

import json
from pathlib import Path

from houdocs.config import load_config
from houdocs.init.runtime import HoudiniInstallation, RuntimeSnapshot
from houdocs.init.service import InitService
from houdocs.node.models import RuntimeNodeSnapshot, RuntimeParameterSnapshot


class FakeRuntime:
    def __init__(self, installation: HoudiniInstallation, snapshot: RuntimeSnapshot) -> None:
        self.installation = installation
        self.snapshot = snapshot
        self.selected: list[str | None] = []
        self.probed: list[tuple[HoudiniInstallation, str | None]] = []

    def select(self, requested_version: str | None) -> HoudiniInstallation:
        self.selected.append(requested_version)
        return self.installation

    def probe(
        self,
        installation: HoudiniInstallation,
        *,
        requested_version: str | None,
    ) -> RuntimeSnapshot:
        self.probed.append((installation, requested_version))
        return self.snapshot


def test_init_service_persists_report_and_assist_compatible_node_dump(tmp_path: Path) -> None:
    help_root = tmp_path / "help"
    help_root.mkdir()
    install_root = tmp_path / "Houdini22.0.429"
    installation = HoudiniInstallation(
        root=install_root,
        bin_dir=install_root / "bin",
        houdini=install_root / "bin" / "houdini.exe",
        hcommand=install_root / "bin" / "hcommand.exe",
        version=(22, 0, 429),
    )
    payload = {
        "schema_version": 1,
        "houdini_version": "22.0.429",
        "help_directories": [str(help_root)],
        "node_type_count": 2,
        "node_types": [
            {
                "canonical_name": "Sop/good",
                "parameters": [{"id": "strength"}],
                "parameter_error": None,
            },
            {
                "canonical_name": "Sop/bad",
                "parameters": [],
                "parameter_error": "RuntimeError: broken template",
            },
        ],
    }
    snapshot = RuntimeSnapshot(
        houdini_version="22.0.429",
        help_directories=(help_root,),
        node_types=(
            RuntimeNodeSnapshot(
                category="Sop",
                internal_name="good",
                canonical_name="Sop/good",
                min_inputs=None,
                max_inputs=None,
                max_outputs=None,
                parameters=(
                    RuntimeParameterSnapshot(0, "strength", "", (), "", False),
                ),
                parameter_error=None,
            ),
            RuntimeNodeSnapshot(
                category="Sop",
                internal_name="bad",
                canonical_name="Sop/bad",
                min_inputs=None,
                max_inputs=None,
                max_outputs=None,
                parameters=(),
                parameter_error="RuntimeError: broken template",
            ),
        ),
        payload=payload,
    )
    runtime = FakeRuntime(installation, snapshot)

    config = load_config(tmp_path / "config.toml", cwd=tmp_path)
    result = InitService(runtime=runtime, data_root=tmp_path / "data").run(
        "22.0.429", config=config
    )

    version_root = tmp_path / "data" / "versions" / "22.0.429"
    report_path = version_root / "reports" / "init-report.json"
    dump_path = version_root / "reports" / "houdini-node-types-22.0.429.json"
    assert report_path.is_file()
    assert dump_path.is_file()
    assert (version_root / "docs.db").is_file()
    assert (version_root / "search.db").is_file()

    persisted_report = json.loads(report_path.read_text(encoding="utf-8"))
    persisted_dump = json.loads(dump_path.read_text(encoding="utf-8"))
    assert result == persisted_report
    assert persisted_dump == payload
    assert result["documents"] == {
        "total": 0,
        "indexed": 0,
        "failed": 0,
    }
    assert result["runtime"] == {
        "node_types": 2,
        "parameters": 1,
        "parameter_errors": 1,
    }
    assert result["node"]["documents"] == 0
    assert result["python"] == {
        "documents": 0,
        "symbols": 0,
        "duplicates": 0,
        "failed": 0,
    }
    assert result["vex"] == {
        "documents": 0,
        "functions": 0,
        "duplicates": 0,
        "failed": 0,
    }
    assert result["search"] == {"entries": 0}
    assert Path(result["artifacts"]["node_unresolved"]).is_file()
    assert result["issue_counts"] == {"warnings": 1, "errors": 0}
    assert result["issues"][0]["kind"] == "node_parameter_introspection_error"
    assert result["issues"][0]["symbol"] == "Sop/bad"
    assert runtime.selected == ["22.0.429"]
    assert runtime.probed == [(installation, "22.0.429")]


def _empty_runtime(tmp_path: Path) -> tuple[FakeRuntime, HoudiniInstallation]:
    help_root = tmp_path / "help"
    help_root.mkdir(exist_ok=True)
    install_root = tmp_path / "Houdini22.0.429"
    installation = HoudiniInstallation(
        root=install_root,
        bin_dir=install_root / "bin",
        houdini=install_root / "bin" / "houdini.exe",
        hcommand=install_root / "bin" / "hcommand.exe",
        version=(22, 0, 429),
    )
    payload = {
        "schema_version": 1,
        "houdini_version": "22.0.429",
        "help_directories": [str(help_root)],
        "node_type_count": 0,
        "node_types": [],
    }
    snapshot = RuntimeSnapshot(
        houdini_version="22.0.429",
        help_directories=(help_root,),
        node_types=(),
        payload=payload,
    )
    return FakeRuntime(installation, snapshot), installation


def test_init_service_rebuilds_existing_databases_from_current_schema(tmp_path: Path) -> None:
    import sqlite3

    from houdocs.paths import VersionPaths

    runtime, _installation = _empty_runtime(tmp_path)
    data_root = tmp_path / "data"
    paths = VersionPaths.for_version("22.0.429", data_root=data_root)
    paths.ensure()

    connection = sqlite3.connect(paths.database)
    try:
        connection.execute("CREATE TABLE legacy_marker(value TEXT)")
        connection.execute(
            "CREATE TABLE sections(id TEXT PRIMARY KEY, document_id TEXT, ordinal INTEGER, text TEXT)"
        )
        connection.commit()
    finally:
        connection.close()
    paths.search_database.write_bytes(b"not-a-current-search-database")
    (paths.docs / "stale-cache.txt").write_text("stale", encoding="utf-8")
    (paths.reports / "node-document-unresolved-22.0.429.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "houdini_version": "22.0.429",
                "overrides": {"parameters": [], "related": []},
                "unresolved": {"node_types": [], "parameters": [], "related": []},
            }
        ),
        encoding="utf-8",
    )
    (paths.reports / "init-report.json").write_text("stale", encoding="utf-8")

    config = load_config(tmp_path / "config.toml", cwd=tmp_path)
    InitService(runtime=runtime, data_root=data_root).run("22.0.429", config=config)

    connection = sqlite3.connect(paths.database)
    try:
        section_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(sections)").fetchall()
        }
        legacy = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='legacy_marker'"
        ).fetchone()
    finally:
        connection.close()
    assert "token_count" in section_columns
    assert legacy is None

    connection = sqlite3.connect(paths.search_database)
    try:
        search_table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='search_entries'"
        ).fetchone()
    finally:
        connection.close()
    assert search_table is not None
    assert not (paths.docs / "stale-cache.txt").exists()
    assert json.loads((paths.reports / "init-report.json").read_text(encoding="utf-8"))[
        "houdini_version"
    ] == "22.0.429"


def test_init_service_invalid_assist_report_preserves_existing_databases(tmp_path: Path) -> None:
    import pytest

    from houdocs.errors import HouDocsError
    from houdocs.paths import VersionPaths

    runtime, _installation = _empty_runtime(tmp_path)
    data_root = tmp_path / "data"
    paths = VersionPaths.for_version("22.0.429", data_root=data_root)
    paths.ensure()
    paths.database.write_bytes(b"existing-docs")
    paths.search_database.write_bytes(b"existing-search")
    (paths.reports / "node-document-unresolved-22.0.429.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "houdini_version": "22.0.429",
                "overrides": {"parameters": [], "related": []},
            }
        ),
        encoding="utf-8",
    )

    config = load_config(tmp_path / "config.toml", cwd=tmp_path)
    with pytest.raises(HouDocsError) as raised:
        InitService(runtime=runtime, data_root=data_root).run("22.0.429", config=config)

    assert raised.value.error.code == "node_assist_invalid"
    assert paths.database.read_bytes() == b"existing-docs"
    assert paths.search_database.read_bytes() == b"existing-search"


def test_init_service_failure_preserves_existing_initialized_state(
    tmp_path: Path, monkeypatch,
) -> None:
    import pytest

    from houdocs.docs.index import DocumentIndexer
    from houdocs.paths import VersionPaths

    runtime, _installation = _empty_runtime(tmp_path)
    data_root = tmp_path / "data"
    paths = VersionPaths.for_version("22.0.429", data_root=data_root)
    paths.ensure()
    paths.database.write_bytes(b"old-docs")
    paths.search_database.write_bytes(b"old-search")
    unresolved_path = paths.reports / "node-document-unresolved-22.0.429.json"
    unresolved_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "houdini_version": "22.0.429",
                "overrides": {"parameters": [], "related": []},
                "unresolved": {"node_types": [], "parameters": [], "related": []},
            }
        ),
        encoding="utf-8",
    )
    unresolved_before = unresolved_path.read_bytes()
    (paths.reports / "init-report.json").write_text("old-report", encoding="utf-8")
    (paths.docs / "old-cache.txt").write_text("old-cache", encoding="utf-8")

    def fail_index(self, *args, **kwargs):
        del self, args, kwargs
        raise RuntimeError("forced indexing failure")

    monkeypatch.setattr(DocumentIndexer, "index_all", fail_index)
    config = load_config(tmp_path / "config.toml", cwd=tmp_path)

    with pytest.raises(RuntimeError, match="forced indexing failure"):
        InitService(runtime=runtime, data_root=data_root).run("22.0.429", config=config)

    assert paths.database.read_bytes() == b"old-docs"
    assert paths.search_database.read_bytes() == b"old-search"
    assert (paths.reports / "init-report.json").read_text(encoding="utf-8") == "old-report"
    assert unresolved_path.read_bytes() == unresolved_before
    assert (paths.docs / "old-cache.txt").read_text(encoding="utf-8") == "old-cache"
    assert not Path(str(paths.database) + ".init-new").exists()
    assert not Path(str(paths.search_database) + ".init-new").exists()
    assert not (paths.root / ".init-staging-docs").exists()
    assert not (paths.root / ".init-staging-reports").exists()


def test_init_service_preserves_manual_overrides_across_full_rebuild(tmp_path: Path, monkeypatch) -> None:
    from houdocs.docs.bookish import BookishDocumentParser
    from houdocs.docs.index import DocumentIndexer
    from houdocs.docs.repository import DocumentRepository
    from houdocs.node.index import NodeIndexer
    from houdocs.node.repository import NodeRepository
    from houdocs.paths import VersionPaths

    help_root = tmp_path / "help"
    node_source = help_root / "nodes" / "sop" / "example.txt"
    node_source.parent.mkdir(parents=True)
    node_source.write_text(
        "#type: node\n#context: sop\n#internal: example\n= Example =\n\n"
        "@parameters\nLegacy Label:\n    Documentation.\n",
        encoding="utf-8",
    )
    install_root = tmp_path / "Houdini22.0.429"
    installation = HoudiniInstallation(
        root=install_root,
        bin_dir=install_root / "bin",
        houdini=install_root / "bin" / "houdini.exe",
        hcommand=install_root / "bin" / "hcommand.exe",
        version=(22, 0, 429),
    )
    runtime_row = {
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
    }
    runtime_node = RuntimeNodeSnapshot(
        category="Sop",
        internal_name="example",
        canonical_name="Sop/example",
        min_inputs=None,
        max_inputs=None,
        max_outputs=None,
        parameters=(
            RuntimeParameterSnapshot(
                0, "current_name", "Current Label", (), "String", False
            ),
        ),
        parameter_error=None,
    )
    payload = {
        "schema_version": 1,
        "houdini_version": "22.0.429",
        "help_directories": [str(help_root)],
        "node_type_count": 1,
        "node_types": [runtime_row],
    }
    snapshot = RuntimeSnapshot(
        houdini_version="22.0.429",
        help_directories=(help_root,),
        node_types=(runtime_node,),
        payload=payload,
    )
    runtime = FakeRuntime(installation, snapshot)
    data_root = tmp_path / "data"
    paths = VersionPaths.for_version("22.0.429", data_root=data_root)
    paths.ensure()

    from houdocs.db.schema import initialize_docs_database

    initialize_docs_database(paths.database)
    documents = DocumentRepository(paths.database)
    DocumentIndexer(
        repository=documents,
        parser=BookishDocumentParser(),
        cache_directory=paths.docs,
        token_counter=len,
    ).index_all(help_root, houdini_version="22.0.429")
    NodeIndexer(
        documents=documents,
        repository=NodeRepository(paths.database),
        docs_directory=paths.docs,
        report_directory=paths.reports,
    ).index_all((runtime_node,), houdini_version="22.0.429")

    unresolved_path = paths.reports / "node-document-unresolved-22.0.429.json"
    unresolved = json.loads(unresolved_path.read_text(encoding="utf-8"))
    target = unresolved["unresolved"]["parameters"][0]
    override = {
        "node": target["node"],
        "document": target["document"],
        "doc_ordinal": target["doc_ordinal"],
        "parm_ids": ["current_name"],
    }
    unresolved["overrides"]["parameters"] = [override]
    unresolved_path.write_text(json.dumps(unresolved), encoding="utf-8")

    monkeypatch.setattr("houdocs.init.service.count_openai_tokens", len)
    monkeypatch.setattr(
        "houdocs.init.service.SearchIndexer.index_all",
        lambda self, **kwargs: {"entries": 0},
    )
    config = load_config(tmp_path / "config.toml", cwd=tmp_path)
    result = InitService(runtime=runtime, data_root=data_root).run(
        "22.0.429", config=config
    )

    assert result["node"]["parameter_resolved_by_manual"] == 1
    refreshed = json.loads(unresolved_path.read_text(encoding="utf-8"))
    assert refreshed["overrides"]["parameters"] == [override]


def test_init_artifact_promotion_rolls_back_all_existing_outputs(
    tmp_path: Path, monkeypatch,
) -> None:
    import sqlite3

    import pytest

    from houdocs.init.staging import InitStaging
    from houdocs.paths import VersionPaths

    paths = VersionPaths.for_version("22.0.429", data_root=tmp_path / "data")
    paths.ensure()

    for path, marker in (
        (paths.database, "old-docs"),
        (paths.search_database, "old-search"),
    ):
        connection = sqlite3.connect(path)
        try:
            connection.execute("CREATE TABLE marker(value TEXT)")
            connection.execute("INSERT INTO marker(value) VALUES (?)", (marker,))
            connection.commit()
        finally:
            connection.close()

    (paths.docs / "state.txt").write_text("old-cache", encoding="utf-8")
    final_report = paths.reports / "init-report.json"
    final_unresolved = paths.reports / "node-document-unresolved.json"
    final_report.write_text("old-report", encoding="utf-8")
    final_unresolved.write_text("old-assist", encoding="utf-8")

    original_replace = Path.replace

    with InitStaging(paths) as staging:
        for path, marker in (
            (staging.database, "new-docs"),
            (staging.search_database, "new-search"),
        ):
            connection = sqlite3.connect(path)
            try:
                connection.execute("CREATE TABLE marker(value TEXT)")
                connection.execute("INSERT INTO marker(value) VALUES (?)", (marker,))
                connection.commit()
            finally:
                connection.close()

        (staging.docs / "state.txt").write_text("new-cache", encoding="utf-8")
        staged_report = staging.reports / "init-report.json"
        staged_unresolved = staging.reports / "node-document-unresolved.json"
        staged_report.write_text("new-report", encoding="utf-8")
        staged_unresolved.write_text("new-assist", encoding="utf-8")

        def fail_second_database(self: Path, target: Path) -> Path:
            if self == staging.search_database and Path(target) == paths.search_database:
                raise OSError("forced promotion failure")
            return original_replace(self, target)

        monkeypatch.setattr(Path, "replace", fail_second_database)

        with pytest.raises(OSError, match="forced promotion failure"):
            staging.promote(
                artifacts=(
                    (staged_unresolved, final_unresolved),
                    (staged_report, final_report),
                )
            )

    def marker(path: Path) -> str:
        connection = sqlite3.connect(path)
        try:
            return str(connection.execute("SELECT value FROM marker").fetchone()[0])
        finally:
            connection.close()

    assert marker(paths.database) == "old-docs"
    assert marker(paths.search_database) == "old-search"
    assert (paths.docs / "state.txt").read_text(encoding="utf-8") == "old-cache"
    assert final_unresolved.read_text(encoding="utf-8") == "old-assist"
    assert final_report.read_text(encoding="utf-8") == "old-report"
    assert not staging.database.exists()
    assert not staging.search_database.exists()
    assert not staging.docs.exists()
    assert not staging.reports.exists()
