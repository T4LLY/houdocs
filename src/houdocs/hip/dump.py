from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from houdocs.errors import HouDocsError
from houdocs.houdini.hython import HythonExecutionError
from houdocs.houdini.runtime import HoudiniRuntime


HIP_DUMP_TIMEOUT_SECONDS = 120.0
_ERROR_DETAIL_LIMIT = 4096


@dataclass(frozen=True)
class HipDumpResult:
    output: Path


class HipDumpService:
    def __init__(self, *, runtime: HoudiniRuntime | None = None) -> None:
        self.runtime = runtime or HoudiniRuntime()

    def dump(
        self,
        hip_file: Path,
        *,
        requested_version: str | None,
        output: Path | None = None,
    ) -> HipDumpResult:
        source = hip_file.expanduser().resolve()
        if not source.is_file():
            raise HouDocsError(
                "hip_file_not_found",
                f"HIP file does not exist: {hip_file}",
            )

        target = _create_output_directory(output)
        success = False
        try:
            installation = self.runtime.select(requested_version)
            runner = self.runtime.runner(installation)
            with tempfile.TemporaryDirectory(prefix="houdocs-hip-control-") as control:
                control_root = Path(control)
                status_path = control_root / "status.json"
                error_path = control_root / "error.txt"
                worker = Path(__file__).with_name("worker.py")
                try:
                    completed = runner.execute_script(
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
                        timeout_seconds=HIP_DUMP_TIMEOUT_SECONDS,
                    )
                except HythonExecutionError as exc:
                    raise HouDocsError(
                        "hip_dump_failed",
                        "Failed to dump HIP in headless Houdini.",
                        detail=exc.detail or str(exc),
                    ) from exc

                _validate_worker_result(
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
            return HipDumpResult(output=target)
        finally:
            if not success:
                shutil.rmtree(target, ignore_errors=True)


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
) -> None:
    status = _read_status(status_path)
    if returncode == 0 and status.get("ok") is True:
        return

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
