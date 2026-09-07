from __future__ import annotations

import json
import re
from pathlib import Path

from houdocs.errors import HouDocsError

_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def unresolved_path(directory: Path, houdini_version: str | None) -> Path:
    version = _FILENAME_RE.sub("_", houdini_version or "unknown").strip("_") or "unknown"
    return directory / f"node-document-unresolved-{version}.json"


def load_overrides(path: Path) -> dict[str, list[dict[str, object]]]:
    if not path.is_file():
        return {"parameters": [], "related": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise HouDocsError(
            "node_assist_invalid",
            f"Unable to read node assist report: {path}",
            detail=str(exc),
        ) from exc
    except json.JSONDecodeError as exc:
        raise HouDocsError(
            "node_assist_invalid",
            f"Node assist report is invalid JSON: {path}",
            detail=str(exc),
        ) from exc

    if not isinstance(payload, dict) or payload.get("schema_version") != 2:
        raise HouDocsError(
            "node_assist_invalid",
            f"Node assist report has an unsupported schema: {path}",
        )

    overrides = payload.get("overrides")
    if not isinstance(overrides, dict):
        raise HouDocsError(
            "node_assist_invalid",
            f"Node assist report is missing overrides: {path}",
        )

    result: dict[str, list[dict[str, object]]] = {}
    for key in ("parameters", "related"):
        rows = overrides.get(key)
        if not isinstance(rows, list) or any(not isinstance(item, dict) for item in rows):
            raise HouDocsError(
                "node_assist_invalid",
                f"Node assist report has invalid overrides.{key}: {path}",
            )
        result[key] = list(rows)
    return result


def write_unresolved(
    path: Path,
    *,
    houdini_version: str | None,
    overrides: dict[str, list[dict[str, object]]],
    unresolved: dict[str, list[dict[str, object]]],
) -> None:
    payload = {
        "schema_version": 2,
        "houdini_version": houdini_version,
        "overrides": {
            "parameters": list(overrides.get("parameters", [])),
            "related": list(overrides.get("related", [])),
        },
        "unresolved": unresolved,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
