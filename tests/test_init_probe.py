from __future__ import annotations

from pathlib import Path

import pytest

from houdocs.errors import HouDocsError
from houdocs.init.probe import (
    RuntimeNodeSnapshot,
    RuntimeParameterSnapshot,
    RuntimeSnapshot,
    parse_probe_payload,
)


def test_runtime_snapshot_counts_parameters_and_errors(tmp_path: Path) -> None:
    snapshot = RuntimeSnapshot(
        houdini_version="22.0.429",
        help_directories=(tmp_path,),
        node_types=(
            RuntimeNodeSnapshot(
                category="Sop",
                internal_name="a",
                canonical_name="Sop/a",
                min_inputs=None,
                max_inputs=None,
                max_outputs=None,
                parameters=(
                    RuntimeParameterSnapshot(0, "a", "A", (), "Float", False),
                    RuntimeParameterSnapshot(1, "b", "B", (), "Float", False),
                ),
                parameter_error=None,
            ),
            RuntimeNodeSnapshot(
                category="Sop",
                internal_name="b",
                canonical_name="Sop/b",
                min_inputs=None,
                max_inputs=None,
                max_outputs=None,
                parameters=(),
                parameter_error="boom",
            ),
        ),
        payload={},
    )

    assert snapshot.parameter_count == 2
    assert snapshot.parameter_error_count == 1


def test_runtime_payload_is_typed_at_the_runtime_boundary(tmp_path: Path) -> None:
    help_root = tmp_path / "help"
    help_root.mkdir()
    payload = {
        "houdini_version": "22.0.429",
        "help_directories": [str(help_root)],
        "node_types": [
            {
                "category": "Sop",
                "name": "example",
                "canonical_name": "Sop/example",
                "min_inputs": 1,
                "max_inputs": 4,
                "max_outputs": 2,
                "parameters": [
                    {
                        "parameter_ordinal": 0,
                        "id": "strength",
                        "label": "Strength",
                        "folder_path": ["Main"],
                        "type": "Float",
                        "is_multiparm": False,
                    },
                    {
                        "parameter_ordinal": None,
                        "id": "separator",
                        "label": "",
                        "folder_path": [],
                        "type": "Separator",
                        "is_multiparm": False,
                    },
                ],
                "parameter_error": None,
            }
        ],
    }

    snapshot = parse_probe_payload(payload)

    node = snapshot.node_types[0]
    assert isinstance(node, RuntimeNodeSnapshot)
    assert node.category == "Sop"
    assert node.internal_name == "example"
    assert node.parameters[0] == RuntimeParameterSnapshot(
        0, "strength", "Strength", ("Main",), "Float", False
    )
    assert node.parameters[1].ordinal is None
    assert snapshot.parameter_count == 2
    assert snapshot.payload is payload


def test_runtime_payload_rejects_invalid_nested_node_metadata(tmp_path: Path) -> None:
    help_root = tmp_path / "help"
    help_root.mkdir()
    payload = {
        "houdini_version": "22.0.429",
        "help_directories": [str(help_root)],
        "node_types": [
            {
                "category": "Sop",
                "name": "example",
                "canonical_name": "Sop/example",
                "parameters": [
                    {
                        "parameter_ordinal": 0,
                        "id": "strength",
                        "label": "Strength",
                        "folder_path": "Main",
                        "type": "Float",
                        "is_multiparm": False,
                    }
                ],
                "parameter_error": None,
            }
        ],
    }

    with pytest.raises(HouDocsError) as caught:
        parse_probe_payload(payload)

    assert caught.value.error.code == "runtime_probe_invalid"
    assert "node_types[0].parameters[0]" in (caught.value.error.detail or "")
    assert "folder_path" in (caught.value.error.detail or "")
