from __future__ import annotations

import importlib.util
import json
from argparse import Namespace
from pathlib import Path


def _load_tool():
    path = Path(__file__).parents[1] / "tools" / "node_document_assist.py"
    spec = importlib.util.spec_from_file_location("houdocs_node_document_assist", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _assist_files(tmp_path: Path) -> tuple[Path, Path]:
    reports = tmp_path / "reports"
    reports.mkdir()
    unresolved = reports / "node-document-unresolved-22.0.429.json"
    nodes = reports / "houdini-node-types-22.0.429.json"
    unresolved.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "houdini_version": "22.0.429",
                "overrides": {"parameters": [], "related": []},
                "unresolved": {
                    "node_types": [],
                    "parameters": [
                        {
                            "document": "nodes/sop/example.txt",
                            "node": "Sop/example",
                            "doc_ordinal": 0,
                            "label": "Legacy Label",
                            "group_path": ["Main"],
                            "reason": "no_houdini_match",
                            "explicit_ids": [],
                            "resolved_ids": [],
                            "missing_ids": [],
                        }
                    ],
                    "related": [],
                },
            }
        ),
        encoding="utf-8",
    )
    nodes.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "houdini_version": "22.0.429",
                "node_types": [
                    {
                        "category": "Sop",
                        "name": "example",
                        "canonical_name": "Sop/example",
                        "parameters": [
                            {
                                "parameter_ordinal": 0,
                                "id": "current_name",
                                "label": "Current Label",
                                "folder_path": ["Main"],
                                "type": "String",
                                "num_components": 1,
                                "is_multiparm": False,
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return unresolved, nodes


def _bind_paths(tool, tmp_path: Path, unresolved: Path, nodes: Path) -> None:
    reports = tmp_path / "reports"
    tool._discover_pair = lambda version: (unresolved, nodes, "22.0.429")
    tool._report_dir = lambda version: reports


def test_assist_next_emits_compact_runtime_grounded_json(tmp_path: Path, capsys) -> None:
    tool = _load_tool()
    unresolved, nodes = _assist_files(tmp_path)
    _bind_paths(tool, tmp_path, unresolved, nodes)

    assert tool.command_next(Namespace(version=None)) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["done"] is False
    assert payload["houdini_version"] == "22.0.429"
    assert payload["node"] == "Sop/example"
    assert payload["unresolved"][0]["doc_ordinal"] == 0
    assert payload["runtime_parameters"][0]["id"] == "current_name"


def test_assist_resolve_validates_runtime_id_and_persists_override(tmp_path: Path, capsys) -> None:
    tool = _load_tool()
    unresolved, nodes = _assist_files(tmp_path)
    _bind_paths(tool, tmp_path, unresolved, nodes)
    tool.command_next(Namespace(version=None))
    capsys.readouterr()

    args = Namespace(
        version=None,
        node="Sop/example",
        doc_ordinal=0,
        parm_ids=["current_name"],
    )
    assert tool.command_resolve(args) == 0

    payload = json.loads(unresolved.read_text(encoding="utf-8"))
    assert payload["overrides"]["parameters"] == [
        {
            "node": "Sop/example",
            "document": "nodes/sop/example.txt",
            "doc_ordinal": 0,
            "parm_ids": ["current_name"],
        }
    ]
    result = json.loads(capsys.readouterr().out)
    assert result["resolved"] is True


def test_assist_skip_persists_state_without_editing_unresolved(tmp_path: Path, capsys) -> None:
    tool = _load_tool()
    unresolved, nodes = _assist_files(tmp_path)
    original = unresolved.read_text(encoding="utf-8")
    _bind_paths(tool, tmp_path, unresolved, nodes)
    tool.command_next(Namespace(version=None))
    capsys.readouterr()

    assert tool.command_skip(
        Namespace(version=None, node="Sop/example", doc_ordinals=[0])
    ) == 0

    state = json.loads(
        (tmp_path / "reports" / "node-document-assist-state-22.0.429.json").read_text(
            encoding="utf-8"
        )
    )
    assert state["skipped"][0]["doc_ordinal"] == 0
    assert unresolved.read_text(encoding="utf-8") == original


def test_assist_rejects_parameter_ids_missing_from_runtime(tmp_path: Path) -> None:
    tool = _load_tool()
    unresolved, nodes = _assist_files(tmp_path)
    _bind_paths(tool, tmp_path, unresolved, nodes)

    try:
        tool.command_resolve(
            Namespace(
                version=None,
                node="Sop/example",
                doc_ordinal=0,
                parm_ids=["invented"],
            )
        )
    except SystemExit as exc:
        assert "Unknown runtime parameter id" in str(exc)
    else:
        raise AssertionError("resolve accepted a parameter ID absent from the runtime dump")
