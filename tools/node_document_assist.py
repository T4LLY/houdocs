#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

try:
    from houdocs.config import load_config, validate_version
    from houdocs.paths import VersionPaths, resolve_initialized_version
except ModuleNotFoundError:
    _repo_src = Path(__file__).resolve().parents[1] / "src"
    if _repo_src.is_dir():
        sys.path.insert(0, str(_repo_src))
    from houdocs.config import load_config, validate_version
    from houdocs.paths import VersionPaths, resolve_initialized_version

SCHEMA_VERSION = 2
STATE_SCHEMA_VERSION = 1
LIFECYCLE_SCHEMA_VERSION = 1

NODE_VERSION_SUFFIX_RE = re.compile(r"::\d+(?:\.\d+)*$")

# Version-specific candidate hints documented in
# node-document-obsolete-tagging-22.0.429.md. These are review candidates,
# not confirmed replacement mappings.
REPLACED_CANDIDATE_HINTS: dict[str, set[str]] = {
    "22.0.429": {
        "Sop/remesh::1.0",
        "Vop/texturemap",
        "Dop/solidsolver::2.0",
    }
}

def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SystemExit(f"Unable to read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SystemExit(f"Expected a JSON object in {path}")
    return value


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _normalize(value: object) -> str:
    return " ".join(str(value or "").casefold().split())


def _selected_paths(version: str | None) -> tuple[VersionPaths, str]:
    config = load_config()
    requested = validate_version(version) if version else config.houdini.version
    selected = resolve_initialized_version(requested)
    return VersionPaths.for_version(selected), selected


def _discover_pair(version: str | None) -> tuple[Path, Path, str]:
    paths, selected = _selected_paths(version)
    root = paths.reports
    unresolved = root / f"node-document-unresolved-{selected}.json"
    nodes = root / f"houdini-node-types-{selected}.json"
    missing = [str(path) for path in (unresolved, nodes) if not path.is_file()]
    if missing:
        raise SystemExit(
            "HouDocs assist inputs are missing for Houdini "
            f"{selected}. Run `houdocs init --houdini-version {selected}` first. "
            f"Missing: {', '.join(missing)}"
        )
    return unresolved, nodes, selected


def _report_dir(version: str) -> Path:
    return VersionPaths.for_version(version).reports


def _state_path(version: str) -> Path:
    return _report_dir(version) / f"node-document-assist-state-{version}.json"

def _load_state(version: str) -> dict[str, Any]:
    path = _state_path(version)
    if not path.is_file():
        return {
            "schema_version": STATE_SCHEMA_VERSION,
            "houdini_version": version,
            "skipped": [],
            "current": None,
        }
    payload = _load_json(path)
    if not isinstance(payload.get("skipped"), list):
        payload["skipped"] = []
    payload.setdefault("schema_version", STATE_SCHEMA_VERSION)
    payload.setdefault("houdini_version", version)
    payload.setdefault("current", None)
    return payload


def _write_state(version: str, state: dict[str, Any]) -> None:
    _write_json_atomic(_state_path(version), state)


def _lifecycle_path(version: str) -> Path:
    return _report_dir(version) / f"node-document-assist-lifecycle-{version}.json"


def _load_lifecycle(version: str) -> dict[str, Any]:
    path = _lifecycle_path(version)
    if not path.is_file():
        return {
            "schema_version": LIFECYCLE_SCHEMA_VERSION,
            "houdini_version": version,
            "parameters": [],
        }
    payload = _load_json(path)
    if not isinstance(payload.get("parameters"), list):
        payload["parameters"] = []
    payload.setdefault("schema_version", LIFECYCLE_SCHEMA_VERSION)
    payload.setdefault("houdini_version", version)
    return payload


def _write_lifecycle(version: str, lifecycle: dict[str, Any]) -> None:
    _write_json_atomic(_lifecycle_path(version), lifecycle)


def _lifecycle_records(lifecycle: dict[str, Any]) -> list[dict[str, Any]]:
    rows = lifecycle.get("parameters")
    if not isinstance(rows, list):
        return []
    return [item for item in rows if isinstance(item, dict)]


def _lifecycle_keys(lifecycle: dict[str, Any]) -> set[tuple[str, int]]:
    result: set[tuple[str, int]] = set()
    for item in _lifecycle_records(lifecycle):
        document = item.get("document")
        ordinal = item.get("doc_ordinal")
        if isinstance(document, str) and isinstance(ordinal, int):
            result.add((document, ordinal))
    return result


def _remove_lifecycle_key(
    lifecycle: dict[str, Any],
    document: str,
    ordinal: int,
) -> bool:
    before = _lifecycle_records(lifecycle)
    after = [
        item
        for item in before
        if not (
            item.get("document") == document
            and item.get("doc_ordinal") == ordinal
        )
    ]
    lifecycle["parameters"] = after
    return len(after) != len(before)


def _parameter_overrides(payload: dict[str, Any]) -> list[dict[str, Any]]:
    overrides = payload.get("overrides")
    if not isinstance(overrides, dict):
        overrides = {}
        payload["overrides"] = overrides
    parameters = overrides.get("parameters")
    if not isinstance(parameters, list):
        parameters = []
        overrides["parameters"] = parameters
    return [item for item in parameters if isinstance(item, dict)]


def _override_keys(payload: dict[str, Any]) -> set[tuple[str, int]]:
    result: set[tuple[str, int]] = set()
    for item in _parameter_overrides(payload):
        document = item.get("document")
        ordinal = item.get("doc_ordinal")
        if isinstance(document, str) and isinstance(ordinal, int):
            result.add((document, ordinal))
    return result


def _skipped_keys(state: dict[str, Any]) -> set[tuple[str, int]]:
    result: set[tuple[str, int]] = set()
    for item in state.get("skipped", []):
        if not isinstance(item, dict):
            continue
        document = item.get("document")
        ordinal = item.get("doc_ordinal")
        if isinstance(document, str) and isinstance(ordinal, int):
            result.add((document, ordinal))
    return result


def _unresolved_parameters(payload: dict[str, Any]) -> list[dict[str, Any]]:
    unresolved = payload.get("unresolved")
    if not isinstance(unresolved, dict):
        return []
    parameters = unresolved.get("parameters")
    if not isinstance(parameters, list):
        return []
    return [item for item in parameters if isinstance(item, dict)]


def _unresolved_keys(payload: dict[str, Any]) -> set[tuple[str, int]]:
    result: set[tuple[str, int]] = set()
    for item in _unresolved_parameters(payload):
        document = item.get("document")
        ordinal = item.get("doc_ordinal")
        if isinstance(document, str) and isinstance(ordinal, int):
            result.add((document, ordinal))
    return result


def _progress_counts(
    payload: dict[str, Any],
    state: dict[str, Any],
    lifecycle: dict[str, Any] | None = None,
) -> dict[str, int]:
    lifecycle = lifecycle or {"parameters": []}
    unresolved_keys = _unresolved_keys(payload)
    resolved_keys = _override_keys(payload) & unresolved_keys
    skipped_keys = (_skipped_keys(state) & unresolved_keys) - resolved_keys
    lifecycle_keys = (
        _lifecycle_keys(lifecycle) & unresolved_keys
    ) - resolved_keys - skipped_keys
    remaining_keys = unresolved_keys - resolved_keys - skipped_keys - lifecycle_keys

    lifecycle_counts = {
        "orphaned": 0,
        "obsolete": 0,
        "replaced": 0,
        "obsolete_candidate": 0,
        "replaced_candidate": 0,
        "lifecycle_pending": 0,
    }
    for item in _lifecycle_records(lifecycle):
        key = (item.get("document"), item.get("doc_ordinal"))
        if key not in lifecycle_keys:
            continue
        info = item.get("lifecycle")
        if not isinstance(info, dict):
            continue
        status = info.get("status")
        candidate_status = info.get("candidate_status")
        if status in {"orphaned", "obsolete", "replaced"}:
            lifecycle_counts[str(status)] += 1
        if candidate_status in {"obsolete_candidate", "replaced_candidate"}:
            lifecycle_counts[str(candidate_status)] += 1
            lifecycle_counts["lifecycle_pending"] += 1
        elif status == "unresolved":
            lifecycle_counts["lifecycle_pending"] += 1

    return {
        "resolved": len(resolved_keys),
        "skipped": len(skipped_keys),
        **lifecycle_counts,
        "unresolved": len(remaining_keys),
    }


def _same_category_version_candidates(
    node_name: str,
    nodes: dict[str, dict[str, Any]],
) -> list[str]:
    if "/" not in node_name:
        return []
    category, raw_name = node_name.split("/", 1)
    if NODE_VERSION_SUFFIX_RE.search(raw_name) is None:
        return []
    base_name = NODE_VERSION_SUFFIX_RE.sub("", raw_name).casefold()

    candidates: set[str] = set()
    seen_rows: set[tuple[str, str]] = set()
    for row in nodes.values():
        row_category = row.get("category")
        row_name = row.get("name")
        if not isinstance(row_category, str) or not isinstance(row_name, str):
            continue
        row_key = (row_category, row_name)
        if row_key in seen_rows:
            continue
        seen_rows.add(row_key)
        if row_category.casefold() != category.casefold():
            continue
        if NODE_VERSION_SUFFIX_RE.sub("", row_name).casefold() != base_name:
            continue
        candidate = f"{row_category}/{row_name}"
        if _normalize(candidate) != _normalize(node_name):
            candidates.add(candidate)
    return sorted(candidates)


def _classify_lifecycle_entries(
    payload: dict[str, Any],
    state: dict[str, Any],
    nodes: dict[str, dict[str, Any]],
    version: str,
    lifecycle: dict[str, Any],
) -> dict[str, int]:
    unresolved_keys = _unresolved_keys(payload)
    resolved_keys = _override_keys(payload) & unresolved_keys
    skipped_keys = (_skipped_keys(state) & unresolved_keys) - resolved_keys
    lifecycle_keys = _lifecycle_keys(lifecycle)

    rows = _lifecycle_records(lifecycle)
    added = {
        "orphaned": 0,
        "obsolete_candidate": 0,
        "replaced_candidate": 0,
    }

    for entry in _unresolved_parameters(payload):
        document = entry.get("document")
        ordinal = entry.get("doc_ordinal")
        if not isinstance(document, str) or not isinstance(ordinal, int):
            continue
        key = (document, ordinal)
        if (
            key in resolved_keys
            or key in skipped_keys
            or key in lifecycle_keys
        ):
            continue

        node = entry.get("node")
        if not isinstance(node, str) or not node.strip():
            lifecycle_info = {
                "status": "orphaned",
                "reason": "missing_node_identity",
                "houdini_version": version,
                "replacement_node": None,
                "replacement_parameter_ids": [],
                "reviewed": True,
            }
            added["orphaned"] += 1
        elif nodes.get(_normalize(node)) is None:
            replacements = _same_category_version_candidates(node, nodes)
            hinted_replacement = node in REPLACED_CANDIDATE_HINTS.get(version, set())
            candidate_status = (
                "replaced_candidate"
                if replacements or hinted_replacement
                else "obsolete_candidate"
            )
            lifecycle_info = {
                "status": "unresolved",
                "candidate_status": candidate_status,
                "reason": (
                    "legacy_node_version_candidate"
                    if replacements
                    else (
                        "replacement_candidate_review"
                        if hinted_replacement
                        else "node_absent_from_runtime"
                    )
                ),
                "houdini_version": version,
                "replacement_node": replacements[0] if len(replacements) == 1 else None,
                "replacement_node_candidates": replacements,
                "replacement_parameter_ids": [],
                "reviewed": False,
            }
            added[candidate_status] += 1
        else:
            # Runtime node exists: leave it in the normal AI resolver queue.
            continue

        rows.append(
            {
                "document": document,
                "doc_ordinal": ordinal,
                "node": node,
                "label": entry.get("label"),
                "lifecycle": lifecycle_info,
            }
        )
        lifecycle_keys.add(key)

    lifecycle["parameters"] = rows
    return {
        **added,
        "classified": sum(added.values()),
    }


def _node_dump(nodes_path: Path) -> tuple[dict[str, dict[str, Any]], str | None]:
    payload = _load_json(nodes_path)
    rows = payload.get("node_types")
    if not isinstance(rows, list):
        raise SystemExit(f"Missing node_types array in {nodes_path}")

    nodes: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue

        category = row.get("category")
        name = row.get("name")
        if isinstance(category, str) and category and isinstance(name, str) and name:
            nodes[_normalize(f"{category}/{name}")] = row

        canonical = row.get("canonical_name")
        if isinstance(canonical, str) and canonical:
            nodes.setdefault(_normalize(canonical), row)

    version = payload.get("houdini_version")
    return nodes, str(version) if isinstance(version, str) else None


def _runtime_parameters(node: dict[str, Any]) -> list[dict[str, Any]]:
    rows = node.get("parameters")
    if not isinstance(rows, list):
        return []

    result: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        parm_id = row.get("id")
        if not isinstance(parm_id, str) or not parm_id:
            continue
        result.append(
            {
                "ordinal": row.get("parameter_ordinal"),
                "id": parm_id,
                "label": row.get("label") or "",
                "folder_path": (
                    row.get("folder_path")
                    if isinstance(row.get("folder_path"), list)
                    else []
                ),
                "type": row.get("type") or "",
                "num_components": row.get("num_components"),
                "multiparm": bool(row.get("is_multiparm")),
            }
        )
    return result


def _assist_item(
    entry: dict[str, Any],
    runtime: list[dict[str, Any]],
) -> dict[str, Any]:
    label = str(entry.get("label") or "")
    label_key = _normalize(label)
    candidates = [
        row["id"]
        for row in runtime
        if _normalize(row.get("label")) == label_key
    ]
    return {
        "doc_ordinal": int(entry["doc_ordinal"]),
        "label": label,
        "group_path": (
            entry.get("group_path")
            if isinstance(entry.get("group_path"), list)
            else []
        ),
        "reason": entry.get("reason"),
        "explicit_ids": (
            entry.get("explicit_ids")
            if isinstance(entry.get("explicit_ids"), list)
            else []
        ),
        "resolved_ids": (
            entry.get("resolved_ids")
            if isinstance(entry.get("resolved_ids"), list)
            else []
        ),
        "missing_ids": (
            entry.get("missing_ids")
            if isinstance(entry.get("missing_ids"), list)
            else []
        ),
        "candidate_ids": candidates,
    }


def _load_inputs(version: str | None) -> tuple[
    Path,
    Path,
    str,
    dict[str, Any],
    dict[str, dict[str, Any]],
    dict[str, Any],
]:
    unresolved_path, nodes_path, selected_version = _discover_pair(version)
    unresolved_payload = _load_json(unresolved_path)
    nodes, dump_version = _node_dump(nodes_path)

    unresolved_version = unresolved_payload.get("houdini_version")
    if (
        isinstance(unresolved_version, str)
        and dump_version
        and unresolved_version != dump_version
    ):
        raise SystemExit(
            f"Houdini version mismatch: unresolved={unresolved_version}, "
            f"nodes={dump_version}"
        )

    state = _load_state(selected_version)
    return (
        unresolved_path,
        nodes_path,
        selected_version,
        unresolved_payload,
        nodes,
        state,
    )


def _target_entries(
    payload: dict[str, Any],
    state: dict[str, Any],
    node: str,
    ordinal: int,
) -> list[dict[str, Any]]:
    entries = [
        item
        for item in _unresolved_parameters(payload)
        if item.get("node") == node and item.get("doc_ordinal") == ordinal
    ]

    current = state.get("current")
    if isinstance(current, dict) and current.get("node") == node:
        document = current.get("document")
        current_matches = [
            item for item in entries if item.get("document") == document
        ]
        if current_matches:
            entries = current_matches

    return entries


def command_next(args: argparse.Namespace) -> int:
    (
        _unresolved_path,
        _nodes_path,
        version,
        payload,
        nodes,
        state,
    ) = _load_inputs(args.version)

    lifecycle = _load_lifecycle(version)
    excluded = _override_keys(payload) | _skipped_keys(state) | _lifecycle_keys(lifecycle)

    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    order: list[tuple[str, str]] = []

    for entry in _unresolved_parameters(payload):
        document = entry.get("document")
        node = entry.get("node")
        ordinal = entry.get("doc_ordinal")
        if (
            not isinstance(document, str)
            or not isinstance(node, str)
            or not isinstance(ordinal, int)
        ):
            continue
        if (document, ordinal) in excluded:
            continue

        key = (node, document)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(entry)

    selected: tuple[str, str] | None = None
    runtime_node: dict[str, Any] | None = None
    for key in order:
        candidate = nodes.get(_normalize(key[0]))
        if candidate is not None:
            selected = key
            runtime_node = candidate
            break

    if selected is None or runtime_node is None:
        state["current"] = None
        _write_state(version, state)
        print(
            json.dumps(
                {
                    "schema_version": SCHEMA_VERSION,
                    "done": True,
                    "houdini_version": version,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
        return 0

    node, document = selected
    runtime = _runtime_parameters(runtime_node)
    unresolved = [
        _assist_item(entry, runtime)
        for entry in groups[selected]
    ]

    state["current"] = {"node": node, "document": document}
    _write_state(version, state)

    output = {
        "schema_version": SCHEMA_VERSION,
        "done": False,
        "houdini_version": version,
        "node": node,
        "document": document,
        "unresolved": unresolved,
        "runtime_parameters": runtime,
    }
    print(json.dumps(output, ensure_ascii=False, separators=(",", ":")))
    return 0


def command_resolve(args: argparse.Namespace) -> int:
    (
        unresolved_path,
        _nodes_path,
        version,
        payload,
        nodes,
        state,
    ) = _load_inputs(args.version)

    node = args.node
    ordinal = args.doc_ordinal
    parm_ids = list(dict.fromkeys(args.parm_ids))

    matches = _target_entries(payload, state, node, ordinal)
    if not matches:
        raise SystemExit(
            f"No unresolved parameter matches node={node} doc_ordinal={ordinal}"
        )
    if len(matches) != 1:
        documents = sorted(
            {
                str(item.get("document"))
                for item in matches
                if isinstance(item.get("document"), str)
            }
        )
        raise SystemExit(
            "Ambiguous unresolved target. Run `python node_document_assist.py next` "
            "first so the current document is known. "
            f"Matching documents: {', '.join(documents)}"
        )

    entry = matches[0]
    document = str(entry["document"])

    runtime_node = nodes.get(_normalize(node))
    if runtime_node is None:
        raise SystemExit(f"Node is not present in the Houdini dump: {node}")

    runtime_ids = {row["id"] for row in _runtime_parameters(runtime_node)}
    unknown = [parm_id for parm_id in parm_ids if parm_id not in runtime_ids]
    if unknown:
        raise SystemExit(
            f"Unknown runtime parameter id(s) for {node}: {', '.join(unknown)}"
        )

    override = {
        "node": node,
        "document": document,
        "doc_ordinal": ordinal,
        "parm_ids": parm_ids,
    }

    overrides = _parameter_overrides(payload)
    key = (document, ordinal)
    merged: list[dict[str, Any]] = []
    replaced = False

    for item in overrides:
        item_key = (item.get("document"), item.get("doc_ordinal"))
        if item_key == key:
            merged.append(override)
            replaced = True
        else:
            merged.append(item)
    if not replaced:
        merged.append(override)

    payload.setdefault("overrides", {})["parameters"] = merged
    _write_json_atomic(unresolved_path, payload)

    lifecycle = _load_lifecycle(version)
    if _remove_lifecycle_key(lifecycle, document, ordinal):
        _write_lifecycle(version, lifecycle)

    skipped = [
        item
        for item in state.get("skipped", [])
        if not (
            isinstance(item, dict)
            and item.get("document") == document
            and item.get("doc_ordinal") == ordinal
        )
    ]
    state["skipped"] = skipped
    _write_state(version, state)

    print(
        json.dumps(
            {
                "resolved": True,
                "node": node,
                "document": document,
                "doc_ordinal": ordinal,
                "parm_ids": parm_ids,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )
    return 0


def command_skip(args: argparse.Namespace) -> int:
    (
        _unresolved_path,
        _nodes_path,
        version,
        payload,
        _nodes,
        state,
    ) = _load_inputs(args.version)

    skipped = [
        item for item in state.get("skipped", [])
        if isinstance(item, dict)
    ]
    skipped_keys = _skipped_keys(state)
    added: list[dict[str, Any]] = []

    for ordinal in args.doc_ordinals:
        matches = _target_entries(payload, state, args.node, ordinal)
        if not matches:
            raise SystemExit(
                f"No unresolved parameter matches node={args.node} "
                f"doc_ordinal={ordinal}"
            )
        if len(matches) != 1:
            raise SystemExit(
                "Ambiguous unresolved target. Run `python node_document_assist.py next` "
                "first so the current document is known."
            )

        entry = matches[0]
        document = str(entry["document"])
        key = (document, ordinal)
        if key in skipped_keys:
            continue

        record = {
            "node": args.node,
            "document": document,
            "doc_ordinal": ordinal,
            "label": entry.get("label"),
            "reason": entry.get("reason"),
        }
        skipped.append(record)
        skipped_keys.add(key)
        added.append(record)

    state["skipped"] = skipped
    _write_state(version, state)

    print(
        json.dumps(
            {
                "skipped": len(added),
                "node": args.node,
                "doc_ordinals": [item["doc_ordinal"] for item in added],
                "total_skipped": len(skipped),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )
    return 0


def command_reset_skip(args: argparse.Namespace) -> int:
    (
        _unresolved_path,
        _nodes_path,
        version,
        payload,
        nodes,
        state,
    ) = _load_inputs(args.version)

    # Before releasing skipped work, isolate currently untouched records whose
    # node is missing from the current runtime. This prevents them from being
    # mixed into a second-model retry after reset-skip.
    lifecycle = _load_lifecycle(version)
    classified = _classify_lifecycle_entries(
        payload, state, nodes, version, lifecycle
    )
    if classified["classified"]:
        _write_lifecycle(version, lifecycle)

    before = len(_skipped_keys(state))
    state["skipped"] = []
    state["current"] = None
    _write_state(version, state)

    counts = _progress_counts(payload, state, lifecycle)
    print(
        json.dumps(
            {
                "reset_skipped": before,
                "auto_classified": classified["classified"],
                **counts,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )
    return 0


def command_classify_lifecycle(args: argparse.Namespace) -> int:
    (
        _unresolved_path,
        _nodes_path,
        version,
        payload,
        nodes,
        state,
    ) = _load_inputs(args.version)

    lifecycle = _load_lifecycle(version)
    added = _classify_lifecycle_entries(
        payload, state, nodes, version, lifecycle
    )
    if added["classified"]:
        _write_lifecycle(version, lifecycle)

    counts = _progress_counts(payload, state, lifecycle)
    print(
        json.dumps(
            {
                "houdini_version": version,
                **added,
                **counts,
                "lifecycle_file": str(_lifecycle_path(version)),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )
    return 0


def command_stats(args: argparse.Namespace) -> int:
    (
        _unresolved_path,
        _nodes_path,
        version,
        payload,
        _nodes,
        state,
    ) = _load_inputs(args.version)

    lifecycle = _load_lifecycle(version)
    counts = _progress_counts(payload, state, lifecycle)
    print(
        json.dumps(
            {
                "houdini_version": version,
                **counts,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )
    return 0



def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "AI-assisted HouDocs node-document parameter override helper. "
            "Inputs are auto-detected from the selected initialized Houdini version."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    next_parser = subparsers.add_parser(
        "next",
        help="Emit one unresolved node as compact AI input JSON.",
    )
    next_parser.add_argument(
        "--version",
        help="Only needed when multiple Houdini version pairs exist beside the script.",
    )
    next_parser.set_defaults(func=command_next)

    resolve_parser = subparsers.add_parser(
        "resolve",
        help="Validate and persist one parameter mapping.",
    )
    resolve_parser.add_argument("node", help="HouDocs canonical node type")
    resolve_parser.add_argument("doc_ordinal", type=int)
    resolve_parser.add_argument("parm_ids", nargs="+")
    resolve_parser.add_argument(
        "--version",
        help="Only needed when multiple Houdini version pairs exist beside the script.",
    )
    resolve_parser.set_defaults(func=command_resolve)

    skip_parser = subparsers.add_parser(
        "skip",
        help="Skip one or more unresolved document parameters for this assist run.",
    )
    skip_parser.add_argument("node", help="HouDocs canonical node type")
    skip_parser.add_argument("doc_ordinals", nargs="+", type=int)
    skip_parser.add_argument(
        "--version",
        help="Only needed when multiple Houdini version pairs exist beside the script.",
    )
    skip_parser.set_defaults(func=command_skip)

    reset_skip_parser = subparsers.add_parser(
        "reset-skip",
        help="Clear all skipped parameter entries so they become eligible for next again.",
    )
    reset_skip_parser.add_argument(
        "--version",
        help="Only needed when multiple Houdini version pairs exist beside the script.",
    )
    reset_skip_parser.set_defaults(func=command_reset_skip)

    lifecycle_parser = subparsers.add_parser(
        "classify-lifecycle",
        help=(
            "Isolate unresolved records whose node is absent from the current "
            "Houdini runtime into a lifecycle sidecar."
        ),
    )
    lifecycle_parser.add_argument(
        "--version",
        help="Only needed when multiple Houdini version pairs exist beside the script.",
    )
    lifecycle_parser.set_defaults(func=command_classify_lifecycle)

    stats_parser = subparsers.add_parser(
        "stats",
        help=(
            "Show resolved, skipped, lifecycle-classified, and remaining "
            "unresolved parameter counts."
        ),
    )
    stats_parser.add_argument(
        "--version",
        help="Only needed when multiple Houdini version pairs exist beside the script.",
    )
    stats_parser.set_defaults(func=command_stats)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
