from __future__ import annotations

import argparse
import json
import posixpath
import traceback
from pathlib import Path
from typing import Any, TextIO
from urllib.parse import quote


ROOT_PATHS = ("/obj", "/stage", "/mat", "/out", "/tasks")
AI_FLAG_KEYS = frozenset({"display", "render", "bypass", "template", "material"})
PARM_NOISE_KEYS = frozenset({"metadata", "visible"})


def raw_capture_options(
    *,
    children: bool,
    metadata: bool = True,
    parms: bool = True,
) -> dict[str, bool]:
    return {
        "children": children,
        "editables": False,
        "inputs": True,
        "position": True,
        "flags": True,
        "parms": parms,
        "default_parmvalues": False,
        "evaluate_parmvalues": False,
        "metadata": metadata,
    }


def minimal_raw_node_data(node: Any) -> dict[str, Any]:
    data: dict[str, Any] = {"type": node.type().name()}
    try:
        position = node.position()
        data["position"] = [float(position[0]), float(position[1])]
    except Exception:
        pass
    return data


def capture_raw_node_shallow(
    node: Any,
    degraded_nodes: list[dict[str, str]],
) -> dict[str, Any]:
    try:
        return node.asData(
            nodes_only=True,
            **raw_capture_options(children=False, metadata=False),
        )
    except Exception:
        try:
            data = node.asData(
                nodes_only=True,
                **raw_capture_options(children=False, metadata=False, parms=False),
            )
            degraded_nodes.append({"path": node.path(), "mode": "parms_off"})
            return data
        except Exception:
            degraded_nodes.append({"path": node.path(), "mode": "minimal"})
            return minimal_raw_node_data(node)


def capture_raw_node_segmented(
    node: Any,
    degraded_nodes: list[dict[str, str]],
) -> dict[str, Any]:
    data = capture_raw_node_shallow(node, degraded_nodes)
    nested = {
        child.name(): capture_raw_node_segmented(child, degraded_nodes)
        for child in node.children()
    }
    if nested:
        data["children"] = nested
    return data


def capture_raw_children_segmented(
    node: Any,
    degraded_nodes: list[dict[str, str]],
) -> dict[str, Any]:
    return {
        child.name(): capture_raw_node_segmented(child, degraded_nodes)
        for child in node.children()
    }


def capture_raw_root(
    node: Any,
    degraded_nodes: list[dict[str, str]],
) -> tuple[dict[str, Any], str | None]:
    try:
        return node.childrenAsData(
            nodes_only=False,
            **raw_capture_options(children=True),
        ), None
    except Exception as primary_error:
        try:
            return node.childrenAsData(
                nodes_only=False,
                **raw_capture_options(children=True, metadata=False),
            ), "metadata_off"
        except Exception:
            try:
                return node.childrenAsData(
                    nodes_only=True,
                    **raw_capture_options(children=True, metadata=False),
                ), "nodes_only"
            except Exception:
                try:
                    return capture_raw_children_segmented(
                        node, degraded_nodes
                    ), "segmented"
                except Exception:
                    raise primary_error


def _trim_flags(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    kept = {
        str(key): flag
        for key, flag in value.items()
        if key in AI_FLAG_KEYS and flag is True
    }
    return kept or None


def _normalize_node_path(base_node_path: str, source: str) -> str:
    if source.startswith("/"):
        return posixpath.normpath(source)
    parent = posixpath.dirname(base_node_path) or "/"
    return posixpath.normpath(posixpath.join(parent, source))


def _trim_inputs(node_path: str, value: Any) -> list[dict[str, Any]] | None:
    if not isinstance(value, list):
        return None

    kept: list[dict[str, Any]] = []
    for connection in value:
        if not isinstance(connection, dict):
            continue
        source = connection.get("from")
        if not isinstance(source, str) or not source:
            continue

        item: dict[str, Any] = {"from": _normalize_node_path(node_path, source)}
        if "from_index" in connection:
            item["from_index"] = connection["from_index"]
        if "to_index" in connection:
            item["to_index"] = connection["to_index"]
        kept.append(item)

    return kept or None


def _prune_parm_value(value: Any) -> Any | None:
    if not isinstance(value, dict):
        return value

    payload = {
        str(key): item
        for key, item in value.items()
        if key not in PARM_NOISE_KEYS
    }
    if not payload:
        return None
    if set(payload) == {"value"}:
        return payload["value"]
    return payload


def _trim_parms(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None

    kept: dict[str, Any] = {}
    for name, parm_value in value.items():
        pruned = _prune_parm_value(parm_value)
        if pruned is not None:
            kept[str(name)] = pruned
    return kept or None


def _prune_ai_raw_node(node: Any, raw_data: Any) -> dict[str, Any]:
    if not isinstance(raw_data, dict):
        return {"path": node.path(), "type": node.type().name()}

    result: dict[str, Any] = {
        "path": node.path(),
        "type": raw_data.get("type", node.type().name()),
    }

    inputs = _trim_inputs(node.path(), raw_data.get("inputs"))
    if inputs:
        result["inputs"] = inputs

    flags = _trim_flags(raw_data.get("flags"))
    if flags:
        result["flags"] = flags

    parms = _trim_parms(raw_data.get("parms"))
    if parms:
        result["parms"] = parms

    return result


def should_recurse_ai(node: Any) -> bool:
    try:
        return bool(node.isNetwork() and node.isEditable())
    except Exception:
        return False


def _network_json_filename(network_path: str) -> str:
    parts = [part for part in network_path.split("/") if part]
    if not parts:
        return "root.json"

    encoded = [quote(part, safe="-_.()") for part in parts]
    if len(encoded) == 1:
        return encoded[0] + ".json"
    return "/".join(encoded[:-1] + [encoded[-1] + ".json"])


def _raw_children(raw_node: Any) -> dict[str, Any]:
    if not isinstance(raw_node, dict):
        return {}
    children = raw_node.get("children")
    return children if isinstance(children, dict) else {}


def _write_ai_network_shards(
    network: Any,
    raw_network: Any,
    search_root: Path,
    emitted: set[str],
) -> None:
    filename = _network_json_filename(network.path())
    if filename in emitted:
        return
    emitted.add(filename)

    raw_nodes = raw_network if isinstance(raw_network, dict) else {}
    nodes: dict[str, Any] = {}
    child_networks: list[tuple[Any, dict[str, Any]]] = []

    for child in network.children():
        child_raw = raw_nodes.get(child.name())
        data = _prune_ai_raw_node(child, child_raw)

        if should_recurse_ai(child):
            try:
                has_children = bool(child.children())
            except Exception:
                has_children = False

            if has_children:
                child_filename = _network_json_filename(child.path())
                data["file"] = child_filename
                child_networks.append((child, _raw_children(child_raw)))

        nodes[child.name()] = data

    _write_json(
        search_root / filename,
        {"network": network.path(), "nodes": nodes},
    )

    for child_network, child_raw_nodes in child_networks:
        _write_ai_network_shards(
            child_network,
            child_raw_nodes,
            search_root,
            emitted,
        )


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


def _write_raw_member(handle: TextIO, key: str, value: Any, *, first: bool) -> bool:
    if not first:
        handle.write(",")
    json.dump(key, handle, ensure_ascii=False, separators=(",", ":"))
    handle.write(":")
    json.dump(value, handle, ensure_ascii=False, separators=(",", ":"))
    return False


def run_worker(
    *,
    hip_path: Path,
    output_dir: Path,
    status_path: Path,
    error_path: Path,
) -> int:
    current_root: str | None = None
    try:
        import hou  # type: ignore

        hou.hipFile.load(str(hip_path), ignore_load_warnings=True)
        search_root = output_dir / "search"
        search_root.mkdir(parents=True, exist_ok=True)

        fallback_roots: list[dict[str, str]] = []
        degraded_nodes: list[dict[str, str]] = []
        emitted: set[str] = set()

        raw_path = output_dir / "raw.json"
        with raw_path.open("w", encoding="utf-8") as raw_handle:
            raw_handle.write("{")
            first = True
            for root_path in ROOT_PATHS:
                current_root = root_path
                root = hou.node(root_path)
                if root is None:
                    continue

                root_data, fallback = capture_raw_root(root, degraded_nodes)
                first = _write_raw_member(
                    raw_handle,
                    root_path,
                    root_data,
                    first=first,
                )
                if fallback is not None:
                    fallback_roots.append({"root": root_path, "mode": fallback})

                _write_ai_network_shards(
                    root,
                    root_data,
                    search_root,
                    emitted,
                )
                del root_data
            raw_handle.write("}")

        _write_json(
            status_path,
            {
                "ok": True,
                "fallback_roots": fallback_roots,
                "degraded_nodes": degraded_nodes,
            },
        )
        return 0
    except Exception:
        detail = traceback.format_exc()
        if current_root is not None:
            detail = f"root={current_root}\n" + detail
        try:
            error_path.parent.mkdir(parents=True, exist_ok=True)
            error_path.write_text(detail, encoding="utf-8")
        finally:
            status_path.parent.mkdir(parents=True, exist_ok=True)
            _write_json(status_path, {"ok": False})
        return 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--hip", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--status", required=True, type=Path)
    parser.add_argument("--error", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    return run_worker(
        hip_path=args.hip,
        output_dir=args.output,
        status_path=args.status,
        error_path=args.error,
    )


if __name__ == "__main__":
    raise SystemExit(main())
