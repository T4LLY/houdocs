from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from houdocs.errors import HouDocsError
from houdocs.hip.dump import HipDumpService
from houdocs.hip.worker import _trim_parms, run_worker
from houdocs.houdini.runtime import HoudiniInstallation


class FakeRuntime:
    def __init__(self, tmp_path: Path) -> None:
        root = tmp_path / "Houdini22.0.429"
        self.installation = HoudiniInstallation(
            root=root,
            bin_dir=root / "bin",
            hython=root / "bin" / "hython.exe",
            hcommand=root / "bin" / "hcommand.exe",
            houdini=root / "bin" / "houdini.exe",
            version=(22, 0, 429),
        )
        self.selected: list[str | None] = []

    def select(self, requested_version: str | None) -> HoudiniInstallation:
        self.selected.append(requested_version)
        return self.installation


class FakeHythonRun:
    def __init__(self, *, errors: dict[str, object] | None = None) -> None:
        self.calls: list[tuple[list[str], dict[str, object]]] = []
        self.errors = errors or {"fallback_roots": [], "degraded_nodes": []}

    def __call__(self, args, **kwargs):
        command = [str(value) for value in args]
        self.calls.append((command, kwargs))
        worker_args = command[3:]
        values = {worker_args[index]: Path(worker_args[index + 1]) for index in range(0, len(worker_args), 2)}
        output = values["--output"]
        output.joinpath("search").mkdir(parents=True, exist_ok=True)
        output.joinpath("raw.json").write_text("{}", encoding="utf-8")
        values["--status"].write_text(
            json.dumps({"ok": True, "errors": self.errors}),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, "", "")


def test_hip_dump_uses_selected_hython_for_explicit_output(tmp_path: Path) -> None:
    hip = tmp_path / "scene.hip"
    hip.write_bytes(b"hip")
    output = tmp_path / "dump"
    runtime = FakeRuntime(tmp_path)
    fake_run = FakeHythonRun()

    result = HipDumpService(runtime=runtime, run=fake_run).dump(
        hip,
        requested_version="22.0.429",
        output=output,
    )

    assert result.output == output.resolve()
    assert result.errors == 0
    assert runtime.selected == ["22.0.429"]
    assert (output / "raw.json").is_file()
    assert (output / "search").is_dir()
    assert len(fake_run.calls) == 1
    command, kwargs = fake_run.calls[0]
    assert command[0] == str(runtime.installation.hython)
    assert Path(command[2]).name == "worker.py"
    assert "--hip" in command
    assert str(hip.resolve()) in command
    assert kwargs["env"]["HFS"] == str(runtime.installation.root)
    assert kwargs["timeout"] == 120.0


def test_hip_dump_passes_timeout_and_reports_degradation_count(tmp_path: Path) -> None:
    hip = tmp_path / "scene.hip"
    hip.write_bytes(b"hip")
    runtime = FakeRuntime(tmp_path)
    fake_run = FakeHythonRun(
        errors={
            "fallback_roots": [{"root": "/stage", "mode": "metadata_off"}],
            "degraded_nodes": [
                {"path": "/obj/geo1/a", "mode": "parms_off"},
                {"path": "/obj/geo1/b", "mode": "minimal"},
            ],
        }
    )

    result = HipDumpService(runtime=runtime, run=fake_run).dump(
        hip,
        requested_version="22.0.429",
        timeout_seconds=45.0,
    )

    try:
        assert result.errors == 3
        assert fake_run.calls[0][1]["timeout"] == 45.0
    finally:
        import shutil

        shutil.rmtree(result.output, ignore_errors=True)


def test_hip_dump_rejects_invalid_timeout_before_creating_output(tmp_path: Path) -> None:
    hip = tmp_path / "scene.hip"
    hip.write_bytes(b"hip")
    output = tmp_path / "dump"
    runtime = FakeRuntime(tmp_path)

    with pytest.raises(HouDocsError) as caught:
        HipDumpService(runtime=runtime).dump(
            hip,
            requested_version=None,
            output=output,
            timeout_seconds=0,
        )

    assert caught.value.error.code == "hip_dump_timeout_invalid"
    assert not output.exists()
    assert runtime.selected == []


def test_hip_dump_defaults_to_persistent_temp_output(tmp_path: Path) -> None:
    hip = tmp_path / "scene.hip"
    hip.write_bytes(b"hip")
    runtime = FakeRuntime(tmp_path)
    fake_run = FakeHythonRun()

    result = HipDumpService(runtime=runtime, run=fake_run).dump(
        hip,
        requested_version=None,
    )

    try:
        assert result.output.is_dir()
        assert result.output.name.startswith("houdocs-hip-")
        assert (result.output / "raw.json").is_file()
    finally:
        import shutil

        shutil.rmtree(result.output, ignore_errors=True)


def test_hip_dump_rejects_existing_output_before_starting_houdini(tmp_path: Path) -> None:
    hip = tmp_path / "scene.hip"
    hip.write_bytes(b"hip")
    output = tmp_path / "dump"
    output.mkdir()
    runtime = FakeRuntime(tmp_path)

    with pytest.raises(HouDocsError) as caught:
        HipDumpService(runtime=runtime).dump(
            hip,
            requested_version="22.0.429",
            output=output,
        )

    assert caught.value.error.code == "hip_dump_output_exists"
    assert runtime.selected == []


def test_worker_preserves_large_parameter_values_without_token_omission() -> None:
    value = "setpointattrib(" + "x" * 100_000 + ")"

    assert _trim_parms({"snippet": {"value": value, "metadata": {"x": 1}}}) == {
        "snippet": value
    }


def test_worker_writes_raw_and_search_tree_from_loaded_hip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class NodeType:
        def name(self) -> str:
            return "attribwrangle"

    class Child:
        def name(self) -> str:
            return "wrangle1"

        def path(self) -> str:
            return "/obj/wrangle1"

        def type(self) -> NodeType:
            return NodeType()

        def isNetwork(self) -> bool:
            return False

        def isEditable(self) -> bool:
            return True

        def children(self) -> list[object]:
            return []

    child = Child()
    raw_child = {
        "type": "attribwrangle",
        "inputs": [],
        "flags": {"display": True, "selected": True},
        "parms": {"snippet": {"value": "setpointattrib(0, 'x', 0, 1);"}},
    }

    class Root:
        def path(self) -> str:
            return "/obj"

        def children(self) -> list[Child]:
            return [child]

        def childrenAsData(self, **kwargs):
            return {"wrangle1": raw_child}

    loaded: list[str] = []
    fake_hou = SimpleNamespace(
        hipFile=SimpleNamespace(load=lambda path, ignore_load_warnings: loaded.append(path)),
        node=lambda path: Root() if path == "/obj" else None,
    )
    monkeypatch.setitem(sys.modules, "hou", fake_hou)

    hip = tmp_path / "scene.hip"
    hip.write_bytes(b"hip")
    output = tmp_path / "dump"
    status = tmp_path / "control" / "status.json"
    error = tmp_path / "control" / "error.txt"

    assert run_worker(
        hip_path=hip,
        output_dir=output,
        status_path=status,
        error_path=error,
    ) == 0

    assert loaded == [str(hip)]
    raw = json.loads((output / "raw.json").read_text(encoding="utf-8"))
    shard = json.loads((output / "search" / "obj.json").read_text(encoding="utf-8"))
    assert raw["/obj"]["wrangle1"]["parms"]["snippet"]["value"].startswith(
        "setpointattrib"
    )
    assert raw["errors"] == {"fallback_roots": [], "degraded_nodes": []}
    assert shard == {
        "network": "/obj",
        "nodes": {
            "wrangle1": {
                "path": "/obj/wrangle1",
                "type": "attribwrangle",
                "flags": {"display": True},
                "parms": {"snippet": "setpointattrib(0, 'x', 0, 1);"},
            }
        },
    }


def test_worker_records_capture_degradation_in_raw_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Root:
        def path(self) -> str:
            return "/obj"

        def children(self) -> list[object]:
            return []

        def childrenAsData(self, **kwargs):
            if kwargs.get("metadata") is True:
                raise RuntimeError("metadata capture failed")
            return {}

    fake_hou = SimpleNamespace(
        hipFile=SimpleNamespace(load=lambda path, ignore_load_warnings: None),
        node=lambda path: Root() if path == "/obj" else None,
    )
    monkeypatch.setitem(sys.modules, "hou", fake_hou)

    output = tmp_path / "dump"
    status = tmp_path / "control" / "status.json"
    error = tmp_path / "control" / "error.txt"

    assert run_worker(
        hip_path=tmp_path / "scene.hip",
        output_dir=output,
        status_path=status,
        error_path=error,
    ) == 0

    raw = json.loads((output / "raw.json").read_text(encoding="utf-8"))
    worker_status = json.loads(status.read_text(encoding="utf-8"))
    expected = {
        "fallback_roots": [{"root": "/obj", "mode": "metadata_off"}],
        "degraded_nodes": [],
    }
    assert raw["errors"] == expected
    assert worker_status == {"ok": True, "errors": expected}
