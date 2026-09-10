from __future__ import annotations

import ntpath
import os
import posixpath
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Mapping, Sequence

if TYPE_CHECKING:
    from houdocs.houdini.runtime import HoudiniInstallation


class HythonExecutionError(RuntimeError):
    def __init__(self, message: str, *, detail: str | None = None) -> None:
        super().__init__(message)
        self.detail = detail


class HythonRunner:
    """Run one-shot Python work inside a selected Houdini installation."""

    def __init__(
        self,
        installation: HoudiniInstallation,
        *,
        run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        environ: Mapping[str, str] | None = None,
        platform: str | None = None,
        timeout_seconds: float = 120.0,
    ) -> None:
        self.installation = installation
        self._run = run
        self._base_environ = os.environ if environ is None else environ
        self.platform = sys.platform if platform is None else platform
        self.timeout_seconds = timeout_seconds

    def execute_script(
        self,
        script: Path,
        arguments: Sequence[str | Path] = (),
        *,
        timeout_seconds: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        args = [
            str(self.installation.hython),
            "-u",
            str(script),
            *(str(argument) for argument in arguments),
        ]
        timeout = self.timeout_seconds if timeout_seconds is None else timeout_seconds
        try:
            return self._run(
                args,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                cwd=str(self.installation.root),
                env=subprocess_environment_for(
                    self.installation,
                    environ=self._base_environ,
                    platform=self.platform,
                ),
            )
        except subprocess.TimeoutExpired as exc:
            detail = _combined_output(exc.stdout, exc.stderr)
            raise HythonExecutionError(
                f"Hython execution timed out after {timeout:g} seconds.",
                detail=detail or None,
            ) from exc
        except OSError as exc:
            raise HythonExecutionError(
                f"Failed to start hython: {self.installation.hython}",
                detail=str(exc),
            ) from exc

    def execute_source(
        self,
        source: str,
        *,
        filename: str = "command.py",
        arguments: Sequence[str | Path] = (),
        timeout_seconds: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        if not filename or Path(filename).name != filename:
            raise ValueError("Hython source filename must be a file name.")
        with tempfile.TemporaryDirectory(prefix="houdocs-hython-") as temporary:
            script = Path(temporary) / filename
            script.write_text(source, encoding="utf-8")
            return self.execute_script(
                script,
                arguments,
                timeout_seconds=timeout_seconds,
            )


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
    remainder = [
        part for part in parts if _path_key(part, platform_name) != selected_key
    ]
    env["PATH"] = path_separator.join([selected, *remainder])
    return env


def _path_key(value: str, platform_name: str) -> str:
    if platform_name.startswith("win"):
        return ntpath.normpath(value).casefold()
    return posixpath.normpath(value)


def _combined_output(stdout: object, stderr: object) -> str:
    parts: list[str] = []
    for value in (stderr, stdout):
        if isinstance(value, bytes):
            text = value.decode("utf-8", errors="replace")
        elif isinstance(value, str):
            text = value
        else:
            text = ""
        if text.strip():
            parts.append(text.strip())
    return "\n".join(parts)
