from __future__ import annotations

from pathlib import Path

import pytest

from houdocs.errors import HouDocsError
from houdocs.node.models import RuntimeNodeSnapshot, RuntimeParameterSnapshot
from houdocs.init.runtime import (
    HoudiniInstallation,
    HoudiniRuntime,
    RuntimeSnapshot,
    _parse_runtime_snapshot,
    select_houdini_installation,
)


def _installation(root: Path, version: tuple[int, int, int]) -> HoudiniInstallation:
    bin_dir = root / "bin"
    return HoudiniInstallation(
        root=root,
        bin_dir=bin_dir,
        houdini=bin_dir / "houdini.exe",
        hcommand=bin_dir / "hcommand.exe",
        version=version,
    )


def test_selects_latest_installation_when_version_is_unspecified(tmp_path: Path) -> None:
    installs = (
        _installation(tmp_path / "Houdini22.0.429", (22, 0, 429)),
        _installation(tmp_path / "Houdini21.0.777", (21, 0, 777)),
    )

    assert select_houdini_installation(None, installations=installs).version == (22, 0, 429)


def test_selects_latest_build_for_major_minor_request(tmp_path: Path) -> None:
    installs = (
        _installation(tmp_path / "Houdini22.0.429", (22, 0, 429)),
        _installation(tmp_path / "Houdini22.0.400", (22, 0, 400)),
    )

    selected = select_houdini_installation("22.0", installations=installs)

    assert selected.version == (22, 0, 429)


def test_requires_exact_build_for_three_part_request(tmp_path: Path) -> None:
    installs = (
        _installation(tmp_path / "Houdini22.0.429", (22, 0, 429)),
        _installation(tmp_path / "Houdini22.0.400", (22, 0, 400)),
    )

    selected = select_houdini_installation("22.0.400", installations=installs)

    assert selected.version == (22, 0, 400)


def test_missing_requested_version_reports_available_versions(tmp_path: Path) -> None:
    installs = (_installation(tmp_path / "Houdini22.0.429", (22, 0, 429)),)

    with pytest.raises(HouDocsError) as caught:
        select_houdini_installation("21.0.777", installations=installs)

    assert caught.value.error.code == "houdini_version_not_found"
    assert "22.0.429" in (caught.value.error.detail or "")


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


def test_discovery_finds_windows_sidefx_installations(tmp_path: Path) -> None:
    sidefx = tmp_path / "Side Effects Software"
    root = sidefx / "Houdini 22.0.429"
    bin_dir = root / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "houdini.exe").write_bytes(b"")
    (bin_dir / "hcommand.exe").write_bytes(b"")

    from houdocs.init.runtime import discover_houdini_installations

    installs = discover_houdini_installations(
        environ={"ProgramFiles": str(tmp_path), "PATH": ""},
        platform="win32",
    )

    assert len(installs) == 1
    assert installs[0].version == (22, 0, 429)
    assert installs[0].houdini == (bin_dir / "houdini.exe").resolve()



def test_runtime_probe_uses_temporary_local_session_and_terminates_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    help_root = tmp_path / "help"
    help_root.mkdir()
    install_root = tmp_path / "Houdini22.0.429"
    bin_dir = install_root / "bin"
    bin_dir.mkdir(parents=True)
    houdini = bin_dir / "houdini.exe"
    hcommand = bin_dir / "hcommand.exe"
    houdini.write_bytes(b"")
    hcommand.write_bytes(b"")
    installation = HoudiniInstallation(
        root=install_root,
        bin_dir=bin_dir,
        houdini=houdini,
        hcommand=hcommand,
        version=(22, 0, 429),
    )

    class Process:
        pid = 1234

        def __init__(self) -> None:
            self.terminated = False

        def poll(self):
            return None

        def terminate(self):
            self.terminated = True

        def wait(self, timeout=None):
            return 0

        def kill(self):
            raise AssertionError("terminate should be sufficient")

    process = Process()
    captured: dict[str, object] = {}

    def fake_popen(args, **kwargs):
        captured["launch_args"] = args
        captured["launch_kwargs"] = kwargs
        captured["startup_script"] = Path(args[1]).read_text(encoding="utf-8")
        return process

    monkeypatch.setattr(
        "houdocs.init.runtime._runtime_probe_script",
        lambda result_path: f"RESULT={result_path}",
    )

    attempts = 0

    def fake_run(args, **kwargs):
        nonlocal attempts
        attempts += 1
        captured["hcommand_args"] = args
        if attempts == 1:
            import subprocess

            return subprocess.CompletedProcess(args, 1, "", "not ready")
        probe_path = Path(str(args[2]).split('"', 2)[1])
        marker = probe_path.read_text(encoding="utf-8")
        result_path = Path(marker.removeprefix("RESULT="))
        result_path.write_text(
            __import__("json").dumps(
                {
                    "houdini_version": "22.0.429",
                    "help_directories": [str(help_root)],
                    "node_types": [],
                }
            ),
            encoding="utf-8",
        )
        import subprocess

        return subprocess.CompletedProcess(args, 0, "", "")

    clock = iter([0.0, 0.0, 0.1, 0.2])
    runtime = HoudiniRuntime(
        popen=fake_popen,
        run=fake_run,
        sleep=lambda _seconds: None,
        monotonic=lambda: next(clock),
        startup_timeout_seconds=1.0,
    )

    snapshot = runtime.probe(installation, requested_version="22.0.429")

    assert snapshot.houdini_version == "22.0.429"
    assert snapshot.help_directories == (help_root.resolve(),)
    assert attempts == 2
    assert process.terminated is True
    assert captured["launch_args"][0] == str(houdini)
    assert str(captured["hcommand_args"][0]) == str(hcommand)
    assert str(captured["hcommand_args"][1]).isdigit()
    assert str(captured["startup_script"]).startswith("openport -q ")


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

    snapshot = _parse_runtime_snapshot(payload)

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
        _parse_runtime_snapshot(payload)

    assert caught.value.error.code == "runtime_probe_invalid"
    assert "node_types[0].parameters[0]" in (caught.value.error.detail or "")
    assert "folder_path" in (caught.value.error.detail or "")
