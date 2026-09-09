from __future__ import annotations

import ntpath
import os
import posixpath
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Mapping

from houdocs.errors import HouDocsError

if TYPE_CHECKING:
    from houdocs.houdini.runtime import HoudiniInstallation


class HoudiniSession:
    """Own one temporary local Houdini process and its hcommand port."""

    def __init__(
        self,
        installation: HoudiniInstallation,
        *,
        popen: Callable[..., subprocess.Popen[bytes]] = subprocess.Popen,
        run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        startup_timeout_seconds: float = 30.0,
        startup_poll_interval_seconds: float = 0.5,
        command_timeout_seconds: float = 15.0,
        platform: str | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self.installation = installation
        self._popen = popen
        self._run = run
        self._sleep = sleep
        self._monotonic = monotonic
        self.startup_timeout_seconds = startup_timeout_seconds
        self.startup_poll_interval_seconds = startup_poll_interval_seconds
        self.command_timeout_seconds = command_timeout_seconds
        self.platform = sys.platform if platform is None else platform
        self._base_environ = os.environ if environ is None else environ
        self._temporary: tempfile.TemporaryDirectory[str] | None = None
        self._process: subprocess.Popen[bytes] | None = None
        self._port: int | None = None

    @property
    def port(self) -> int:
        if self._port is None:
            raise RuntimeError("Houdini session is not started.")
        return self._port

    def __enter__(self) -> HoudiniSession:
        self.start()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def start(self) -> None:
        if self._process is not None:
            return

        self._temporary = tempfile.TemporaryDirectory(prefix="houdocs-houdini-")
        root = Path(self._temporary.name)
        port_path = root / "port"
        startup_script = root / "startup.py"
        startup_script.write_text(_startup_script(port_path), encoding="utf-8")

        try:
            process = self._launch(startup_script)
            self._process = process
            deadline = self._monotonic() + self.startup_timeout_seconds
            self._port = self._wait_for_port(port_path, process, deadline)
            self._wait_until_reachable(process, deadline)
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        process = self._process
        self._process = None
        self._port = None
        if process is not None:
            _terminate_process(process)
        temporary = self._temporary
        self._temporary = None
        if temporary is not None:
            temporary.cleanup()

    def temporary_path(self, name: str) -> Path:
        if self._temporary is None:
            raise RuntimeError("Houdini session is not started.")
        if not name or Path(name).name != name:
            raise ValueError("Session temporary path must be a file name.")
        return Path(self._temporary.name) / name

    def execute_hscript(self, command: str) -> subprocess.CompletedProcess[str]:
        if self._port is None:
            raise RuntimeError("Houdini session is not started.")
        return self._execute_hcommand(command)

    def execute_python(
        self,
        source: str,
        *,
        filename: str = "command.py",
    ) -> subprocess.CompletedProcess[str]:
        script_path = self.temporary_path(filename)
        script_path.write_text(source, encoding="utf-8")
        quoted = script_path.resolve().as_posix().replace('"', '\\"')
        return self.execute_hscript(f'python "{quoted}"')

    def _launch(self, startup_script: Path) -> subprocess.Popen[bytes]:
        args = [str(self.installation.houdini)]
        if not self.platform.startswith("win"):
            args.append("-foreground")
        args.append(str(startup_script))

        kwargs: dict[str, object] = {
            "cwd": str(self.installation.root),
            "env": subprocess_environment_for(
                self.installation,
                environ=self._base_environ,
                platform=self.platform,
            ),
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }
        if self.platform.startswith("win"):
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

        try:
            return self._popen(args, **kwargs)
        except OSError as exc:
            raise HouDocsError(
                "houdini_launch_failed",
                f"Failed to launch Houdini {self.installation.version_string}.",
                detail=str(exc),
            ) from exc

    def _wait_for_port(
        self,
        port_path: Path,
        process: subprocess.Popen[bytes],
        deadline: float,
    ) -> int:
        while self._monotonic() < deadline:
            self._raise_if_exited(process)
            if port_path.is_file():
                try:
                    value = port_path.read_text(encoding="utf-8").strip()
                except OSError:
                    value = ""
                if value.isdigit() and 0 < int(value) <= 65535:
                    return int(value)
                raise HouDocsError(
                    "houdini_launch_failed",
                    "Houdini returned an invalid local command port.",
                    detail=value or None,
                )
            self._sleep(self.startup_poll_interval_seconds)

        raise HouDocsError(
            "houdini_startup_timeout",
            "Houdini was launched but did not publish its local command port.",
        )

    def _wait_until_reachable(
        self,
        process: subprocess.Popen[bytes],
        deadline: float,
    ) -> None:
        last_detail: str | None = None
        while self._monotonic() < deadline:
            self._raise_if_exited(process)
            completed = self._execute_hcommand("echo houdocs-ready")
            if completed.returncode == 0 and "houdocs-ready" in completed.stdout.splitlines():
                return
            last_detail = _clip((completed.stderr or completed.stdout or "").strip()) or None
            self._sleep(self.startup_poll_interval_seconds)

        raise HouDocsError(
            "houdini_startup_timeout",
            "Houdini was launched but its local command port did not become reachable.",
            detail=last_detail,
        )

    def _raise_if_exited(self, process: subprocess.Popen[bytes]) -> None:
        return_code = process.poll()
        if return_code is not None:
            raise HouDocsError(
                "houdini_launch_failed",
                f"Houdini exited before the local session became ready (status {return_code}).",
            )

    def _execute_hcommand(self, command: str) -> subprocess.CompletedProcess[str]:
        if self._port is None:
            raise RuntimeError("Houdini session port is not available.")
        try:
            return self._run(
                [str(self.installation.hcommand), str(self._port), command],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.command_timeout_seconds,
                env=subprocess_environment_for(
                    self.installation,
                    environ=self._base_environ,
                    platform=self.platform,
                ),
            )
        except subprocess.TimeoutExpired as exc:
            return subprocess.CompletedProcess(
                args=exc.cmd,
                returncode=124,
                stdout=exc.stdout or "",
                stderr=exc.stderr or "",
            )
        except OSError as exc:
            raise HouDocsError(
                "hcommand_failed",
                f"Failed to execute hcommand: {self.installation.hcommand}",
                detail=str(exc),
            ) from exc


def subprocess_environment_for(
    installation: HoudiniInstallation,
    *,
    environ: Mapping[str, str] | None = None,
    platform: str | None = None,
) -> dict[str, str]:
    env = dict(os.environ if environ is None else environ)
    platform_name = sys.platform if platform is None else platform
    env["HFS"] = str(installation.root)

    selected = str(installation.bin_dir)
    path_separator = ";" if platform_name.startswith("win") else ":"
    current_path = env.get("PATH", "")
    parts = [part for part in current_path.split(path_separator) if part]
    selected_key = _path_key(selected, platform_name)
    remainder = [part for part in parts if _path_key(part, platform_name) != selected_key]
    env["PATH"] = path_separator.join([selected, *remainder])
    return env


def _path_key(value: str, platform_name: str) -> str:
    if platform_name.startswith("win"):
        return ntpath.normpath(value).casefold()
    return posixpath.normpath(value)


def _startup_script(port_path: Path) -> str:
    target = repr(str(port_path))
    return f'''from pathlib import Path\n\nimport hou\n\noutput, errors = hou.hscript("openport -a -q")\nif errors.strip():\n    raise RuntimeError(errors.strip())\nport = output.strip()\nif not port.isdigit():\n    raise RuntimeError(f"Invalid port returned by openport: {{port!r}}")\ntarget = Path({target})\ntemporary = target.with_suffix(".tmp")\ntemporary.write_text(port, encoding="utf-8")\ntemporary.replace(target)\n'''


def _terminate_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        process.terminate()
        process.wait(timeout=5)
        return
    except (OSError, subprocess.TimeoutExpired):
        pass
    try:
        process.kill()
        process.wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        pass


def _clip(value: str, limit: int = 4096) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + "…"
