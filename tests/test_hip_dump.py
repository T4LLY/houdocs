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


class FakeRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[Path, tuple[object, ...], float | None]] = []

    def execute_script(self, script, arguments=(), *, timeout_seconds=None):
        args = tuple(arguments)
        self.calls.append((Path(script), args, timeout_seconds))
        values = {str(args[index]): Path(args[index + 1]) for index in range(0, len(args), 2)}
        output = values["--output"]
        output.joinpath("search").mkdir(parents=True, exist_ok=True)
        output.joinpath("raw.json").write_text("{}", encoding="utf-8")
        values["--status"].write_text('{"ok":true}', encoding="utf-8")
        return subprocess.CompletedProcess([], 0, "", "")


class FakeRuntime:
    def __init__(self, tmp_path: Path) -> None:
        root = tmp_path / "Houdini22.0.429"
        self.installation = HoudiniInstallation(
            root=root,
            bin_dir=root / "bin",
            hython=root / "bin" / "hython.exe",
            version=(22, 0, 429),
        )
        self.selected: list[str | None] = []
        self.runner_instance = FakeRunner()

    def select(self, requested_version: str | None) -> HoudiniInstallation:
        self.selected.append(requested_version)
        return self.installation

    def runner(self, installation: HoudiniInstallation) -> FakeRunner:
        assert installation == self.installation
        return self.runner_instance


def test_hip_dump_uses_selected_houdini_runner_and_explicit_output(tmp_path: Path) -> None:
    hip = tmp_path / "scene.hip"
    hip.write_bytes(b"hip")
    output = tmp_path / "dump"
    runtime = FakeRuntime(tmp_path)

    result = HipDumpService(runtime=runtime).dump(
        hip,
        requested_version="22.0.429",
        output=output,
    )

    assert result.output == output.resolve()
    assert runtime.selected == ["22.0.429"]
    assert (output / "raw.json").is_file()
    assert (output / "search").is_dir()
    assert len(runtime.runner_instance.calls) == 1
    script, arguments, _timeout = runtime.runner_instance.calls[0]
    assert script.name == "worker.py"
    assert "--hip" in arguments
    assert str(hip.resolve()) in [str(value) for value in arguments]


def test_hip_dump_defaults_to_persistent_temp_output(tmp_path: Path) -> None:
    hip = tmp_path / "scene.hip"
    hip.write_bytes(b"hip")
    runtime = FakeRuntime(tmp_path)

    result = HipDumpService(runtime=runtime).dump(
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
