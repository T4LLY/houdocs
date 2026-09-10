from __future__ import annotations

import json
import math
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from houdocs.errors import HouDocsError
from houdocs.houdini.environment import subprocess_environment_for
from houdocs.houdini.runtime import HoudiniInstallation, HoudiniRuntime


HIP_DUMP_TIMEOUT_SECONDS = 120.0
_ERROR_DETAIL_LIMIT = 4096


@dataclass(frozen=True)
class HipDumpResult:
    output: Path
    errors: int


class HipDumpService:
    def __init__(
        self,
        *,
        runtime: HoudiniRuntime | None = None,
        run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ) -> None:
        self.runtime = runtime or HoudiniRuntime()
        self._run = run

    def dump(
        self,
        hip_file: Path,
        *,
        requested_version: str | None,
        output: Path | None = None,
        timeout_seconds: float = HIP_DUMP_TIMEOUT_SECONDS,
    ) -> HipDumpResult:
        source = hip_file.expanduser().resolve()
        if not source.is_file():
            raise HouDocsError(
                "hip_file_not_found",
                f"HIP file does not exist: {hip_file}",
            )

        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise HouDocsError(
                "hip_dump_timeout_invalid",
                "HIP dump timeout must be a positive finite number of seconds.",
            )

        target = _create_output_directory(output)
        success = False
        try:
            installation = self.runtime.select(requested_version)
            with tempfile.TemporaryDirectory(prefix="houdocs-hip-control-") as control:
                control_root = Path(control)
                status_path = control_root / "status.json"
                error_path = control_root / "error.txt"
                worker = Path(__file__).with_name("worker.py")
                completed = _run_worker(
                    installation,
                    worker,
                    (
                        "--hip",
                        source,
                        "--output",
                        target,
                        "--status",
                        status_path,
                        "--error",
                        error_path,
                    ),
                    run=self._run,
                    timeout_seconds=timeout_seconds,
                )

                status = _validate_worker_result(
                    completed.returncode,
                    completed.stdout,
                    completed.stderr,
                    status_path,
                    error_path,
                )

            if not (target / "raw.json").is_file() or not (target / "search").is_dir():
                raise HouDocsError(
                    "hip_dump_failed",
                    "HIP dump completed without the required output files.",
                )
            success = True
            return HipDumpResult(output=target, errors=_worker_error_count(status))
        finally:
            if not success:
                shutil.rmtree(target, ignore_errors=True)


def _run_worker(
    installation: HoudiniInstallation,
    worker: Path,
    arguments: tuple[str | Path, ...],
    *,
    run: Callable[..., subprocess.CompletedProcess[str]],
    timeout_seconds: float,
) -> subprocess.CompletedProcess[str]:
    args = [
        str(installation.hython),
        "-u",
        str(worker),
        *(str(argument) for argument in arguments),
    ]
    try:
        return run(
            args,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            env=subprocess_environment_for(installation),
        )
    except subprocess.TimeoutExpired as exc:
        detail = _combined_output(exc.stdout, exc.stderr)
        raise HouDocsError(
            "hip_dump_failed",
            "Failed to dump HIP in headless Houdini.",
            detail=detail or f"Hython timed out after {timeout_seconds:g} seconds.",
        ) from exc
    except OSError as exc:
        raise HouDocsError(
            "hip_dump_failed",
            "Failed to dump HIP in headless Houdini.",
            detail=str(exc),
        ) from exc


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


def _create_output_directory(output: Path | None) -> Path:
    if output is None:
        return Path(tempfile.mkdtemp(prefix="houdocs-hip-")).resolve()

    target = output.expanduser().resolve()
    if target.exists():
        raise HouDocsError(
            "hip_dump_output_exists",
            f"HIP dump output already exists: {target}",
        )
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.mkdir()
    except FileExistsError as exc:
        raise HouDocsError(
            "hip_dump_output_exists",
            f"HIP dump output already exists: {target}",
        ) from exc
    except OSError as exc:
        raise HouDocsError(
            "hip_dump_output_failed",
            f"Unable to create HIP dump output directory: {target}",
            detail=str(exc),
        ) from exc
    return target


def _validate_worker_result(
    returncode: int,
    stdout: str,
    stderr: str,
    status_path: Path,
    error_path: Path,
) -> dict[str, object]:
    status = _read_status(status_path)
    if returncode == 0 and status.get("ok") is True:
        return status

    detail = ""
    if error_path.is_file():
        detail = error_path.read_text(encoding="utf-8", errors="replace").strip()
    if not detail:
        detail = (stderr or stdout or "").strip()
    raise HouDocsError(
        "hip_dump_failed",
        "Failed to dump HIP in headless Houdini.",
        detail=_clip(detail) or None,
    )


def _worker_error_count(status: dict[str, object]) -> int:
    errors = status.get("errors")
    if not isinstance(errors, dict):
        return 0
    fallback_roots = errors.get("fallback_roots")
    degraded_nodes = errors.get("degraded_nodes")
    return (len(fallback_roots) if isinstance(fallback_roots, list) else 0) + (
        len(degraded_nodes) if isinstance(degraded_nodes, list) else 0
    )


def _read_status(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _clip(value: str) -> str:
    if len(value) <= _ERROR_DETAIL_LIMIT:
        return value
    marker = "\n...<snip>...\n"
    half = max(1, (_ERROR_DETAIL_LIMIT - len(marker)) // 2)
    return value[:half] + marker + value[-half:]
