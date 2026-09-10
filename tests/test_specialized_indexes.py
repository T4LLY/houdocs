from __future__ import annotations

from contextlib import closing
import json
import sqlite3
from pathlib import Path

from houdocs.db.schema import initialize_docs_database
from houdocs.docs.bookish import BookishDocumentParser
from houdocs.docs.header import parse_page_properties
from houdocs.docs.index import DocumentIndexer
from houdocs.docs.repository import DocumentRepository
from houdocs.init.probe import RuntimeNodeSnapshot, RuntimeParameterSnapshot
from houdocs.node.index import NodeIndexer
from houdocs.node.repository import NodeRepository
from houdocs.python_docs.index import PythonIndexer
from houdocs.python_docs.parser import _group_signatures
from houdocs.python_docs.signature import parse_python_signature
from houdocs.python_docs.repository import PythonRepository
from houdocs.vex_docs.index import VexIndexer
from houdocs.vex_docs.read import VexDocumentReader
from houdocs.vex_docs.repository import VexRepository



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

def _index_base_documents(source: Path, state: Path) -> DocumentRepository:
    initialize_docs_database(state / "docs.db")
    repository = DocumentRepository(state / "docs.db")
    DocumentIndexer(
        repository=repository,
        parser=BookishDocumentParser(),
        cache_directory=state / "docs",
        token_counter=len,
    ).index_all(source, houdini_version="22.0.429")
    return repository


def test_specialized_schema_is_created_in_docs_database(tmp_path: Path) -> None:
    initialize_docs_database(tmp_path / "docs.db")
    with closing(sqlite3.connect(tmp_path / "docs.db")) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    assert {"node_documents", "python_documents", "vex_documents"}.issubset(tables)


def test_node_index_resolves_runtime_parameters_and_writes_unresolved(
    tmp_path: Path,
) -> None:
    source = tmp_path / "help"
    source.mkdir()
    node_path = source / "nodes" / "sop"
    node_path.mkdir(parents=True)
    (node_path / "example.txt").write_text(
        """#type: node
#context: sop
#internal: example
= Example =

@parameters
Group:
    Geometry group.
Strength:
    #id: strength
    Strength amount.
Unknown:
    Not in runtime.

@related
- [Other|Node:sop/other]
""",
        encoding="utf-8",
    )
    state = tmp_path / "state"
    documents = _index_base_documents(source, state)
    warnings: list[tuple[str, str | None]] = []
    runtime_rows = (
        {
            "category": "Sop",
            "name": "example",
            "canonical_name": "Sop/example",
            "parameters": [
                {
                    "parameter_ordinal": 0,
                    "id": "group",
                    "label": "Group",
                    "folder_path": ["Main"],
                    "type": "String",
                    "is_multiparm": False,
                },
                {
                    "parameter_ordinal": 1,
                    "id": "strength",
                    "label": "Strength",
                    "folder_path": ["Main"],
                    "type": "Float",
                    "is_multiparm": False,
                },
            ],
        },
        {
            "category": "Sop",
            "name": "other",
            "canonical_name": "Sop/other",
            "parameters": [],
        },
    )

    result = NodeIndexer(
        documents=documents,
        repository=NodeRepository(state / "docs.db"),
        docs_directory=state / "docs",
        report_directory=state / "reports",
    ).index_all(
        _runtime_nodes(runtime_rows),
        houdini_version="22.0.429",
        on_warning=lambda kind, detail, document, symbol: warnings.append(
            (kind, symbol)
        ),
    )

    assert result["documents"] == 1
    assert result["parameter_total"] == 3
    assert result["parameter_resolved"] == 2
    assert result["parameter_resolved_by_doc_id"] == 1
    assert result["parameter_resolved_by_houdini"] == 1
    assert result["parameter_unresolved"] == 1
    assert result["related_resolved"] == 1
    assert warnings == [("node_parameter_unresolved", "Sop/example")]

    unresolved = json.loads(
        Path(str(result["unresolved_file"])).read_text(encoding="utf-8")
    )
    assert unresolved["unresolved"]["parameters"][0]["label"] == "Unknown"
    assert unresolved["unresolved"]["parameters"][0]["reason"] == "no_houdini_match"


def test_node_index_reuses_manual_override_in_fresh_build(tmp_path: Path) -> None:
    source = tmp_path / "help"
    source.mkdir()
    node_path = source / "nodes" / "sop"
    node_path.mkdir(parents=True)
    (node_path / "example.txt").write_text(
        """#type: node
#context: sop
#internal: example
= Example =

@parameters
Legacy Label:
    Needs manual mapping.
""",
        encoding="utf-8",
    )
    state = tmp_path / "state"
    documents = _index_base_documents(source, state)
    indexer = NodeIndexer(
        documents=documents,
        repository=NodeRepository(state / "docs.db"),
        docs_directory=state / "docs",
        report_directory=state / "reports",
    )
    runtime_rows = (
        {
            "category": "Sop",
            "name": "example",
            "canonical_name": "Sop/example",
            "parameters": [
                {
                    "parameter_ordinal": 0,
                    "id": "newname",
                    "label": "Current Label",
                    "folder_path": [],
                    "type": "String",
                    "is_multiparm": False,
                }
            ],
        },
    )

    first = indexer.index_all(_runtime_nodes(runtime_rows), houdini_version="22.0.429")
    unresolved_path = Path(str(first["unresolved_file"]))
    payload = json.loads(unresolved_path.read_text(encoding="utf-8"))
    payload["overrides"]["parameters"] = [
        {
            "document": "nodes/sop/example.txt",
            "doc_ordinal": 0,
            "parm_ids": ["newname"],
        }
    ]
    unresolved_path.write_text(json.dumps(payload), encoding="utf-8")

    from houdocs.node.unresolved import load_overrides

    second_state = tmp_path / "second-state"
    second_documents = _index_base_documents(source, second_state)
    second = NodeIndexer(
        documents=second_documents,
        repository=NodeRepository(second_state / "docs.db"),
        docs_directory=second_state / "docs",
        report_directory=second_state / "reports",
    ).index_all(
        _runtime_nodes(runtime_rows),
        houdini_version="22.0.429",
        overrides=load_overrides(unresolved_path),
    )

    assert second["parameter_resolved"] == 1
    assert second["parameter_resolved_by_manual"] == 1
    assert second["parameter_unresolved"] == 0
    persisted = json.loads(
        Path(str(second["unresolved_file"])).read_text(encoding="utf-8")
    )
    assert persisted["overrides"]["parameters"][0]["parm_ids"] == ["newname"]
    assert persisted["unresolved"]["parameters"] == []


def test_specialized_page_properties_accept_real_and_legacy_header_order() -> None:
    assert parse_page_properties("= xyzdist =\n\n#type: vex\n#context: all\n\nBody.") == {
        "type": "vex",
        "context": "all",
    }
    assert parse_page_properties("#type: vex\n#context: all\n= xyzdist =\n\nBody.") == {
        "type": "vex",
        "context": "all",
    }
    assert parse_page_properties(
        "= accessframe =\n\nIntro.\n\n#type: vex\n#context: cop2\n\n@related\n#type: ignored"
    ) == {
        "type": "vex",
        "context": "cop2",
    }


def test_python_signature_accepts_real_hom_method_syntax() -> None:
    assert parse_python_signature(
        "::`setInput(self, input_index, item_to_become_input, output_index=0)`:"
    ) == (
        "setInput",
        "setInput(self, input_index, item_to_become_input, output_index=0)",
    )


def test_python_signature_grouping_ignores_bookish_code_blocks() -> None:
    grouped = _group_signatures("method(value)\n{{{\nprint('example')\n}}}")

    assert grouped == {"method": ["method(value)"]}


def test_python_index_builds_direct_symbol_rows_without_body_duplication(
    tmp_path: Path,
) -> None:
    source = tmp_path / "help"
    hom = source / "hom" / "hou"
    hom.mkdir(parents=True)
    (hom / "Node.txt").write_text(
        """= hou.Node =
#type: homclass

== Methods ==
::`setInput(self, input_index, item_to_become_input, output_index=0)`:
    Connect another node.
::`setInput(self, input_index, item_to_become_input)`:
    Alternate overload.
::`setNamedInput(self, input_name, item_to_become_input, output_name_or_index)`:
    Connect by name.
""",
        encoding="utf-8",
    )
    (hom / "node_.txt").write_text(
        "= hou.node =\n\n#type: homfunction\n\n:usage: `node(path)`\n    Return a node.\n",
        encoding="utf-8",
    )
    state = tmp_path / "state"
    documents = _index_base_documents(source, state)

    result = PythonIndexer(
        documents=documents,
        repository=PythonRepository(state / "docs.db"),
        docs_directory=state / "docs",
    ).index_all()

    assert result == {"documents": 2, "symbols": 4, "duplicates": 0, "failed": 0}
    with closing(sqlite3.connect(state / "docs.db")) as connection:
        connection.row_factory = sqlite3.Row
        method = connection.execute(
            "SELECT * FROM python_documents WHERE symbol = ?", ("hou.Node.setInput",)
        ).fetchone()
        function = connection.execute(
            "SELECT * FROM python_documents WHERE symbol = ?", ("hou.node",)
        ).fetchone()
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(python_documents)")
        }
    assert method["kind"] == "method"
    assert method["parent_symbol"] == "hou.Node"
    assert len(json.loads(method["signatures_json"])) == 2
    assert function["kind"] == "function"
    assert "text" not in columns
    assert "metadata_json" not in columns


def test_vex_index_preserves_overloads_context_group_tags_and_status(
    tmp_path: Path,
) -> None:
    source = tmp_path / "help"
    vex = source / "vex" / "functions"
    vex.mkdir(parents=True)
    (vex / "xyzdist.txt").write_text(
        """= xyzdist =

#type: vex
#context: sop surface
#group: geometry
#tags: distance, geometry
#status: stable

float xyzdist(int geometry, vector origin):
    Find closest point.
float xyzdist(int geometry, vector origin, int &prim, vector &uv):
    Return primitive and uv.
{{{
xyzdist(0, P);
}}}
""",
        encoding="utf-8",
    )
    state = tmp_path / "state"
    documents = _index_base_documents(source, state)

    result = VexIndexer(
        documents=documents,
        repository=VexRepository(state / "docs.db"),
        docs_directory=state / "docs",
    ).index_all()

    assert result == {"documents": 1, "functions": 1, "duplicates": 0, "failed": 0}
    with closing(sqlite3.connect(state / "docs.db")) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            "SELECT * FROM vex_documents WHERE function_name = 'xyzdist'"
        ).fetchone()
        columns = {
            item[1] for item in connection.execute("PRAGMA table_info(vex_documents)")
        }
    assert json.loads(row["signatures_json"]) == [
        "float xyzdist(int geometry, vector origin)",
        "float xyzdist(int geometry, vector origin, int &prim, vector &uv)",
    ]
    assert json.loads(row["contexts_json"]) == ["sop", "surface"]
    assert row["group_name"] == "geometry"
    assert json.loads(row["tags_json"]) == ["distance", "geometry"]
    assert row["status"] == "stable"
    assert "text" not in columns
    assert "metadata_json" not in columns

def test_vex_index_uses_filename_when_real_page_title_is_stale(tmp_path: Path) -> None:
    source = tmp_path / "help"
    vex = source / "vex" / "functions"
    vex.mkdir(parents=True)
    (vex / "pxnoise.txt").write_text(
        "= xnoise =\n\n#type: vex\n#context: all\n\n:usage: `float|vector pxnoise(float x, int xp)`\n",
        encoding="utf-8",
    )
    (vex / "xnoise.txt").write_text(
        "= xnoise =\n\n#type: vex\n#context: all\n\n:usage: `float xnoise(float x)`\n",
        encoding="utf-8",
    )
    state = tmp_path / "state"
    documents = _index_base_documents(source, state)

    result = VexIndexer(
        documents=documents,
        repository=VexRepository(state / "docs.db"),
        docs_directory=state / "docs",
    ).index_all()

    assert result == {"documents": 2, "functions": 2, "duplicates": 0, "failed": 0}
    pxnoise = VexRepository(state / "docs.db").get("pxnoise")
    xnoise = VexRepository(state / "docs.db").get("xnoise")
    assert pxnoise is not None
    assert xnoise is not None
    assert pxnoise.signatures == ("float|vector pxnoise(float x, int xp)",)
    assert xnoise.signatures == ("float xnoise(float x)",)

    article = VexDocumentReader(
        documents=documents,
        repository=VexRepository(state / "docs.db"),
    ).read("pxnoise")
    assert article["text"].startswith("pxnoise\n")
    assert ":usage:" not in article["text"]
