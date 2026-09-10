from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from houdocs.houdini.hython import (
    HythonExecutionError,
    HythonRunner,
    subprocess_environment_for,
)
from houdocs.houdini.runtime import HoudiniInstallation


def _installation(tmp_path: Path) -> HoudiniInstallation:
    root = tmp_path / "Houdini22.0.429"
    bin_dir = root / "bin"
    bin_dir.mkdir(parents=True)
    hython = bin_dir / "hython.exe"
    hython.write_bytes(b"")
    return HoudiniInstallation(
        root=root,
        bin_dir=bin_dir,
        hython=hython,
        version=(22, 0, 429),
    )


def test_hython_environment_forces_selected_hfs_and_bin_first(tmp_path: Path) -> None:
    installation = _installation(tmp_path)
    old_bin = tmp_path / "Houdini21.0.777" / "bin"
    environ = {
        "HFS": str(old_bin.parent),
        "PATH": ";".join(
            [str(old_bin), str(installation.bin_dir), str(tmp_path / "tools")]
        ),
    }

    env = subprocess_environment_for(
        installation,
        environ=environ,
        platform="win32",
    )

    assert env["HFS"] == str(installation.root)
    parts = env["PATH"].split(";")
    assert parts[0] == str(installation.bin_dir)
    assert parts.count(str(installation.bin_dir)) == 1
    assert str(old_bin) in parts[1:]


def test_hython_runner_executes_selected_hython_with_shared_environment(
    tmp_path: Path,
) -> None:
    installation = _installation(tmp_path)
    script = tmp_path / "worker.py"
    script.write_text("print('ok')", encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(args, 0, "ok\n", "")

    runner = HythonRunner(
        installation,
        run=fake_run,
        environ={"PATH": "", "HFS": "wrong"},
        platform="win32",
    )
    completed = runner.execute_script(script, ("--value", "x"))

    assert completed.returncode == 0
    assert captured["args"] == [
        str(installation.hython),
        "-u",
        str(script),
        "--value",
        "x",
    ]
    kwargs = captured["kwargs"]
    assert kwargs["cwd"] == str(installation.root)
    assert kwargs["env"]["HFS"] == str(installation.root)
    assert kwargs["env"]["PATH"].split(";")[0] == str(installation.bin_dir)


def test_hython_runner_executes_temporary_source(tmp_path: Path) -> None:
    installation = _installation(tmp_path)
    captured: dict[str, object] = {}

    def fake_run(args, **kwargs):
        script = Path(args[2])
        captured["source"] = script.read_text(encoding="utf-8")
        captured["name"] = script.name
        return subprocess.CompletedProcess(args, 0, "", "")

    runner = HythonRunner(installation, run=fake_run, platform="win32")
    runner.execute_source("VALUE = 1", filename="probe.py")

    assert captured == {"source": "VALUE = 1", "name": "probe.py"}


def test_hython_runner_normalizes_timeout_to_shared_error(tmp_path: Path) -> None:
    installation = _installation(tmp_path)
    script = tmp_path / "worker.py"
    script.write_text("pass", encoding="utf-8")

    def fake_run(args, **kwargs):
        raise subprocess.TimeoutExpired(args, kwargs["timeout"], output="partial")

    runner = HythonRunner(installation, run=fake_run, timeout_seconds=3.0)

    with pytest.raises(HythonExecutionError) as caught:
        runner.execute_script(script)

    assert "3" in str(caught.value)
    assert caught.value.detail == "partial"
