from __future__ import annotations

import subprocess
from pathlib import Path

from houdocs.houdini.runtime import HoudiniInstallation
from houdocs.houdini.session import HoudiniSession, subprocess_environment_for


def _installation(tmp_path: Path) -> HoudiniInstallation:
    root = tmp_path / "Houdini22.0.429"
    bin_dir = root / "bin"
    bin_dir.mkdir(parents=True)
    houdini = bin_dir / "houdini.exe"
    hcommand = bin_dir / "hcommand.exe"
    houdini.write_bytes(b"")
    hcommand.write_bytes(b"")
    return HoudiniInstallation(
        root=root,
        bin_dir=bin_dir,
        houdini=houdini,
        hcommand=hcommand,
        version=(22, 0, 429),
    )


def test_session_environment_forces_selected_hfs_and_bin_first(tmp_path: Path) -> None:
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


def test_session_lets_houdini_choose_port_and_owns_process(
    tmp_path: Path,
    monkeypatch,
) -> None:
    installation = _installation(tmp_path)

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

    monkeypatch.setattr(
        "houdocs.houdini.session._startup_script",
        lambda port_path: f"PORT={port_path}",
    )

    def fake_popen(args, **kwargs):
        captured["launch_args"] = args
        captured["launch_kwargs"] = kwargs
        startup = Path(args[-1]).read_text(encoding="utf-8")
        port_path = Path(startup.removeprefix("PORT="))
        port_path.write_text("18888", encoding="utf-8")
        return process

    ready_attempts = 0

    def fake_run(args, **kwargs):
        nonlocal ready_attempts
        captured["hcommand_args"] = args
        if args[2] == "echo houdocs-ready":
            ready_attempts += 1
            if ready_attempts == 1:
                return subprocess.CompletedProcess(args, 1, "", "not ready")
            return subprocess.CompletedProcess(args, 0, "houdocs-ready\n", "")
        return subprocess.CompletedProcess(args, 0, "", "")

    session = HoudiniSession(
        installation,
        popen=fake_popen,
        run=fake_run,
        sleep=lambda _seconds: None,
        startup_timeout_seconds=1.0,
        platform="win32",
        environ={"PATH": "", "HFS": "wrong"},
    )

    with session:
        assert session.port == 18888
        result = session.execute_python("VALUE = 1", filename="test.py")
        assert result.returncode == 0
        assert str(captured["hcommand_args"][0]) == str(installation.hcommand)
        assert captured["hcommand_args"][1] == "18888"
        assert captured["hcommand_args"][2].startswith('python "')

    assert process.terminated is True
    assert captured["launch_args"][0] == str(installation.houdini)
    assert "-foreground" not in captured["launch_args"]
    launch_env = captured["launch_kwargs"]["env"]
    assert launch_env["HFS"] == str(installation.root)


def test_posix_session_keeps_houdini_in_foreground(tmp_path: Path, monkeypatch) -> None:
    installation = _installation(tmp_path)

    class Process:
        def poll(self):
            return None

        def terminate(self):
            pass

        def wait(self, timeout=None):
            return 0

        def kill(self):
            pass

    captured: dict[str, object] = {}
    monkeypatch.setattr(
        "houdocs.houdini.session._startup_script",
        lambda port_path: f"PORT={port_path}",
    )

    def fake_popen(args, **kwargs):
        captured["args"] = args
        startup = Path(args[-1]).read_text(encoding="utf-8")
        Path(startup.removeprefix("PORT=")).write_text("18888", encoding="utf-8")
        return Process()

    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(args, 0, "houdocs-ready\n", "")

    with HoudiniSession(
        installation,
        popen=fake_popen,
        run=fake_run,
        sleep=lambda _seconds: None,
        startup_timeout_seconds=1.0,
        platform="linux",
        environ={"PATH": ""},
    ):
        pass

    assert captured["args"] == [
        str(installation.houdini),
        "-foreground",
        captured["args"][-1],
    ]


def test_startup_script_lets_houdini_choose_and_publish_port(tmp_path: Path) -> None:
    from houdocs.houdini.session import _startup_script

    port_path = tmp_path / "port"
    source = _startup_script(port_path)

    assert 'hou.hscript("openport -a -q")' in source
    assert repr(str(port_path)) in source
    assert "temporary.replace(target)" in source
