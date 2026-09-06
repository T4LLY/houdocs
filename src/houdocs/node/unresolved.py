from __future__ import annotations

import json
import re
from pathlib import Path

_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def unresolved_path(directory: Path, houdini_version: str | None) -> Path:
    version = _FILENAME_RE.sub("_", houdini_version or "unknown").strip("_") or "unknown"
    return directory / f"node-document-unresolved-{version}.json"


def load_overrides(path: Path) -> dict[str, list[dict[str, object]]]:
    if not path.is_file():
        return {"parameters": [], "related": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"parameters": [], "related": []}
    overrides = payload.get("overrides") if isinstance(payload, dict) else None
    if not isinstance(overrides, dict):
        return {"parameters": [], "related": []}
    return {
        "parameters": [item for item in overrides.get("parameters", []) if isinstance(item, dict)],
        "related": [item for item in overrides.get("related", []) if isinstance(item, dict)],
    }


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
