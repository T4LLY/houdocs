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




def test_probe_session_executes_init_worker_through_houdini_session(tmp_path: Path) -> None:
    import json
    import subprocess

    from houdocs.init.probe import probe_session

    help_root = tmp_path / "help-session"
    help_root.mkdir()

    class Session:
        def __init__(self) -> None:
            self.root = tmp_path / "session"
            self.root.mkdir()
            self.source = ""

        def temporary_path(self, name: str) -> Path:
            return self.root / name

        def execute_python(self, source: str, *, filename: str = "command.py"):
            self.source = source
            assert filename == "init-probe.py"
            self.temporary_path("runtime.json").write_text(
                json.dumps(
                    {
                        "houdini_version": "22.0.429",
                        "help_directories": [str(help_root)],
                        "node_types": [],
                    }
                ),
                encoding="utf-8",
            )
            return subprocess.CompletedProcess([], 0, "", "")

    session = Session()
    snapshot = probe_session(session, requested_version="22.0.429")

    assert snapshot.houdini_version == "22.0.429"
    assert snapshot.help_directories == (help_root.resolve(),)
    assert "worker.py" in session.source
    assert "write_payload" in session.source


def test_probe_session_rejects_runtime_version_mismatch(tmp_path: Path) -> None:
    import json
    import subprocess

    from houdocs.init.probe import probe_session

    help_root = tmp_path / "help-version"
    help_root.mkdir()

    class Session:
        def temporary_path(self, name: str) -> Path:
            return tmp_path / name

        def execute_python(self, source: str, *, filename: str = "command.py"):
            del source, filename
            self.temporary_path("runtime.json").write_text(
                json.dumps(
                    {
                        "houdini_version": "22.0.430",
                        "help_directories": [str(help_root)],
                        "node_types": [],
                    }
                ),
                encoding="utf-8",
            )
            return subprocess.CompletedProcess([], 0, "", "")

    with pytest.raises(HouDocsError) as caught:
        probe_session(Session(), requested_version="22.0.429")

    assert caught.value.error.code == "houdini_version_mismatch"


def test_probe_session_maps_command_failure_to_runtime_probe_error(tmp_path: Path) -> None:
    import subprocess

    from houdocs.init.probe import probe_session

    class Session:
        def temporary_path(self, name: str) -> Path:
            return tmp_path / name

        def execute_python(self, source: str, *, filename: str = "command.py"):
            del source, filename
            return subprocess.CompletedProcess([], 1, "", "worker failed")

    with pytest.raises(HouDocsError) as caught:
        probe_session(Session(), requested_version=None)

    assert caught.value.error.code == "runtime_probe_failed"
    assert caught.value.error.detail == "worker failed"
