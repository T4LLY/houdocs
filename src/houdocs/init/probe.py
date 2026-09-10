"""Houdini-side initialization probe contract and payload decoding."""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from pathlib import Path

from houdocs.errors import HouDocsError
from houdocs.houdini.hython import HythonExecutionError, HythonRunner


@dataclass(frozen=True)
class RuntimeParameterSnapshot:
    ordinal: int | None
    parm_id: str
    label: str
    folder_path: tuple[str, ...]
    parm_type: str
    multiparm: bool


@dataclass(frozen=True)
class RuntimeNodeSnapshot:
    category: str
    internal_name: str
    canonical_name: str
    min_inputs: int | None
    max_inputs: int | None
    max_outputs: int | None
    parameters: tuple[RuntimeParameterSnapshot, ...]
    parameter_error: str | None


@dataclass(frozen=True)
class RuntimeSnapshot:
    houdini_version: str
    help_directories: tuple[Path, ...]
    node_types: tuple[RuntimeNodeSnapshot, ...]
    payload: dict[str, object]

    @property
    def parameter_count(self) -> int:
        total = 0
        for node in self.node_types:
            total += len(node.parameters)
        return total

    @property
    def parameter_error_count(self) -> int:
        return sum(1 for node in self.node_types if node.parameter_error)


def probe_hython(
    runner: HythonRunner,
    *,
    requested_version: str | None,
) -> RuntimeSnapshot:
    with tempfile.TemporaryDirectory(prefix="houdocs-init-probe-") as temporary:
        result_path = Path(temporary) / "runtime.json"
        worker = Path(__file__).with_name("worker.py")
        try:
            completed = runner.execute_script(
                worker,
                ("--output", result_path),
            )
        except HythonExecutionError as exc:
            raise HouDocsError(
                "runtime_probe_failed",
                "Houdini initialization probe failed.",
                detail=exc.detail or str(exc),
            ) from exc
        if completed.returncode != 0 or not result_path.is_file():
            detail = (completed.stderr or completed.stdout or "").strip() or None
            raise HouDocsError(
                "runtime_probe_failed",
                "Houdini initialization probe failed.",
                detail=detail,
            )
        snapshot = load_probe_snapshot(result_path)
    _validate_requested_runtime_version(requested_version, snapshot.houdini_version)
    return snapshot


def load_probe_snapshot(path: Path) -> RuntimeSnapshot:
    return parse_probe_payload(_read_probe_payload(path))


def _read_probe_payload(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HouDocsError(
            "runtime_probe_invalid",
            "Houdini initialization probe returned invalid JSON.",
        ) from exc
    if not isinstance(payload, dict):
        raise HouDocsError(
            "runtime_probe_invalid",
            "Houdini initialization probe payload is not an object.",
        )
    return payload


def parse_probe_payload(payload: dict[str, object]) -> RuntimeSnapshot:
    version = payload.get("houdini_version")
    help_directories = payload.get("help_directories")
    node_types = payload.get("node_types")
    if not isinstance(version, str) or not version:
        raise HouDocsError(
            "runtime_probe_invalid",
            "Houdini initialization probe is missing houdini_version.",
        )
    if not isinstance(help_directories, list) or not all(
        isinstance(value, str) and value for value in help_directories
    ):
        raise HouDocsError(
            "runtime_probe_invalid",
            "Houdini initialization probe returned invalid help_directories.",
        )
    if not isinstance(node_types, list):
        raise HouDocsError(
            "runtime_probe_invalid",
            "Houdini initialization probe returned invalid node_types.",
        )
    parsed_node_types = tuple(
        _parse_runtime_node_type(value, index=index)
        for index, value in enumerate(node_types)
    )

    roots = tuple(Path(value).expanduser().resolve() for value in help_directories)
    roots = tuple(path for path in roots if path.is_dir())
    if not roots:
        raise HouDocsError(
            "docs_source_missing",
            "Houdini did not report an accessible help directory.",
        )

    return RuntimeSnapshot(
        houdini_version=version,
        help_directories=roots,
        node_types=parsed_node_types,
        payload=payload,
    )


def _parse_runtime_node_type(value: object, *, index: int) -> RuntimeNodeSnapshot:
    if not isinstance(value, dict):
        _invalid_runtime_node(index, "node record is not an object")

    category = _required_string(value.get("category"), index=index, field="category")
    internal_name = _required_string(value.get("name"), index=index, field="name")
    canonical_name = _required_string(
        value.get("canonical_name"), index=index, field="canonical_name"
    )
    parameters = value.get("parameters")
    if not isinstance(parameters, list):
        _invalid_runtime_node(index, "parameters is not an array")

    parameter_error = value.get("parameter_error")
    if parameter_error is not None and not isinstance(parameter_error, str):
        _invalid_runtime_node(index, "parameter_error is not a string or null")

    return RuntimeNodeSnapshot(
        category=category,
        internal_name=internal_name,
        canonical_name=canonical_name,
        min_inputs=_optional_integer(
            value.get("min_inputs"), index=index, field="min_inputs"
        ),
        max_inputs=_optional_integer(
            value.get("max_inputs"), index=index, field="max_inputs"
        ),
        max_outputs=_optional_integer(
            value.get("max_outputs"), index=index, field="max_outputs"
        ),
        parameters=tuple(
            _parse_runtime_parameter(
                parameter,
                node_index=index,
                parameter_index=parameter_index,
            )
            for parameter_index, parameter in enumerate(parameters)
        ),
        parameter_error=parameter_error or None,
    )


def _parse_runtime_parameter(
    value: object,
    *,
    node_index: int,
    parameter_index: int,
) -> RuntimeParameterSnapshot:
    location = f"node_types[{node_index}].parameters[{parameter_index}]"
    if not isinstance(value, dict):
        _invalid_runtime_field(location, "record is not an object")

    ordinal = value.get("parameter_ordinal")
    if ordinal is not None and (
        not isinstance(ordinal, int) or isinstance(ordinal, bool)
    ):
        _invalid_runtime_field(location, "parameter_ordinal is not an integer or null")

    parm_id = value.get("id")
    if not isinstance(parm_id, str):
        _invalid_runtime_field(location, "id is not a string")
    label = value.get("label")
    if label is not None and not isinstance(label, str):
        _invalid_runtime_field(location, "label is not a string or null")
    parm_type = value.get("type")
    if parm_type is not None and not isinstance(parm_type, str):
        _invalid_runtime_field(location, "type is not a string or null")

    folder_path = value.get("folder_path")
    if not isinstance(folder_path, list) or not all(
        isinstance(item, str) for item in folder_path
    ):
        _invalid_runtime_field(location, "folder_path is not an array of strings")

    multiparm = value.get("is_multiparm")
    if not isinstance(multiparm, bool):
        _invalid_runtime_field(location, "is_multiparm is not a boolean")

    return RuntimeParameterSnapshot(
        ordinal=ordinal,
        parm_id=parm_id,
        label=label or "",
        folder_path=tuple(folder_path),
        parm_type=parm_type or "",
        multiparm=multiparm,
    )


def _required_string(value: object, *, index: int, field: str) -> str:
    if not isinstance(value, str) or not value:
        _invalid_runtime_node(index, f"{field} is missing or not a string")
    return value


def _optional_integer(value: object, *, index: int, field: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        _invalid_runtime_node(index, f"{field} is not an integer or null")
    return value


def _invalid_runtime_node(index: int, detail: str) -> None:
    _invalid_runtime_field(f"node_types[{index}]", detail)


def _invalid_runtime_field(location: str, detail: str) -> None:
    raise HouDocsError(
        "runtime_probe_invalid",
        "Houdini initialization probe returned invalid node metadata.",
        detail=f"{location}: {detail}",
    )


def _validate_requested_runtime_version(requested: str | None, actual: str) -> None:
    if requested is None:
        return
    requested_parts = requested.split(".")
    actual_parts = actual.split(".")
    if actual_parts[: len(requested_parts)] != requested_parts:
        raise HouDocsError(
            "houdini_version_mismatch",
            f"Requested Houdini {requested}, but runtime reported {actual}.",
        )
