from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field

from houdocs.node.models import (
    DocumentedField,
    NodeParameter,
    NodeParameterDoc,
    NodeParameterLink,
    RuntimeNodeType,
    RuntimeParameter,
)
from houdocs.node.text import clean_label


def resolve_parameters(
    *,
    node_type_id: str,
    relative_path: str,
    canonical_name: str | None,
    documented: tuple[DocumentedField, ...],
    runtime: RuntimeNodeType | None,
    overrides: list[dict[str, object]],
) -> tuple[
    list[NodeParameter],
    list[NodeParameterDoc],
    list[NodeParameterLink],
    dict[str, int],
    list[dict[str, object]],
]:
    runtime_parameters = list(runtime.parameters if runtime else ())
    by_id, by_id_without_hash, by_label = _index_runtime_parameters(runtime_parameters)

    parameters: list[NodeParameter] = [
        NodeParameter(
            parameter_id=_parameter_id(node_type_id, f"runtime:{parameter.parm_id}"),
            node_type_id=node_type_id,
            ordinal=parameter.ordinal,
            parm_id=parameter.parm_id,
            label=parameter.label,
            folder_path=parameter.folder_path,
            parm_type=parameter.parm_type,
            multiparm=parameter.multiparm,
            runtime_present=True,
        )
        for parameter in runtime_parameters
    ]
    parameter_by_parm_id = {parameter.parm_id: parameter for parameter in parameters}
    synthetic_ordinal = len(parameters)

    def parameter_for_id(parm_id: str, field: DocumentedField) -> NodeParameter:
        nonlocal synthetic_ordinal
        existing = parameter_by_parm_id.get(parm_id)
        if existing is not None:
            return existing
        created = NodeParameter(
            parameter_id=_parameter_id(node_type_id, f"documented:{parm_id}"),
            node_type_id=node_type_id,
            ordinal=synthetic_ordinal,
            parm_id=parm_id,
            label=field.label,
            folder_path=field.group_path,
            parm_type=None,
            multiparm="#" in parm_id,
            runtime_present=False,
        )
        synthetic_ordinal += 1
        parameters.append(created)
        parameter_by_parm_id[parm_id] = created
        return created

    decisions: dict[int, _ParameterDecision] = {}
    ambiguous_candidates: dict[int, list[RuntimeParameter]] = {}
    for field in documented:
        decision, ambiguous = _resolve_parameter(
            field=field,
            relative_path=relative_path,
            runtime=runtime,
            overrides=overrides,
            by_id=by_id,
            by_id_without_hash=by_id_without_hash,
            by_label=by_label,
        )
        decisions[field.ordinal] = decision
        if ambiguous:
            ambiguous_candidates[field.ordinal] = ambiguous

    _resolve_parameter_order(
        documented=documented,
        decisions=decisions,
        ambiguous_candidates=ambiguous_candidates,
        runtime_parameters=runtime_parameters,
    )

    doc_rows: list[NodeParameterDoc] = []
    link_rows: list[NodeParameterLink] = []
    unresolved: list[dict[str, object]] = []
    counts = _parameter_resolution_counts(len(documented))
    for field in documented:
        _append_parameter_resolution(
            node_type_id=node_type_id,
            relative_path=relative_path,
            canonical_name=canonical_name,
            field=field,
            decision=decisions[field.ordinal],
            parameter_for_id=parameter_for_id,
            doc_rows=doc_rows,
            link_rows=link_rows,
            unresolved=unresolved,
            counts=counts,
        )

    parameters.sort(key=lambda item: (item.ordinal, item.parm_id))
    return parameters, doc_rows, link_rows, counts, unresolved


@dataclass
class _ParameterDecision:
    resolved_ids: list[str]
    source: str | None = None
    reason: str | None = None
    missing_ids: list[str] = field(default_factory=list)


def _index_runtime_parameters(
    parameters: list[RuntimeParameter],
) -> tuple[
    dict[str, RuntimeParameter],
    dict[str, list[RuntimeParameter]],
    dict[str, list[RuntimeParameter]],
]:
    by_id = {parameter.parm_id: parameter for parameter in parameters}
    by_id_without_hash: dict[str, list[RuntimeParameter]] = {}
    by_label: dict[str, list[RuntimeParameter]] = {}
    for parameter in parameters:
        by_id_without_hash.setdefault(parameter.parm_id.replace("#", ""), []).append(
            parameter
        )
        by_label.setdefault(_label_key(parameter.label), []).append(parameter)
    return by_id, by_id_without_hash, by_label


def _resolve_parameter(
    *,
    field: DocumentedField,
    relative_path: str,
    runtime: RuntimeNodeType | None,
    overrides: list[dict[str, object]],
    by_id: dict[str, RuntimeParameter],
    by_id_without_hash: dict[str, list[RuntimeParameter]],
    by_label: dict[str, list[RuntimeParameter]],
) -> tuple[_ParameterDecision, list[RuntimeParameter]]:
    manual_ids = _parameter_override(overrides, relative_path, field)
    desired_ids = manual_ids or field.explicit_ids
    if not desired_ids:
        if runtime is None:
            return _ParameterDecision(
                [], reason="houdini_introspection_unavailable"
            ), []
        return _resolve_parameter_by_label(
            field,
            by_label,
            no_match_reason="no_houdini_match",
        )

    source = "manual" if manual_ids else "bookish-id"
    if runtime is None:
        return _ParameterDecision(list(desired_ids), source=source), []

    resolved_ids: list[str] = []
    missing_ids: list[str] = []
    for desired_id in desired_ids:
        resolved = _runtime_parm_id(desired_id, by_id, by_id_without_hash)
        if resolved is None:
            missing_ids.append(desired_id)
        elif resolved not in resolved_ids:
            resolved_ids.append(resolved)

    if missing_ids and not manual_ids and not resolved_ids:
        return _resolve_parameter_by_label(
            field,
            by_label,
            no_match_reason="bookish_id_not_in_houdini",
            missing_ids=missing_ids,
        )
    if not missing_ids:
        return _ParameterDecision(resolved_ids, source=source), []

    reason = (
        "manual_id_not_in_houdini"
        if manual_ids
        else "bookish_ids_partially_missing"
        if resolved_ids
        else "bookish_id_not_in_houdini"
    )
    return _ParameterDecision(resolved_ids, source, reason, missing_ids), []


def _resolve_parameter_by_label(
    field: DocumentedField,
    by_label: dict[str, list[RuntimeParameter]],
    *,
    no_match_reason: str,
    missing_ids: list[str] | None = None,
) -> tuple[_ParameterDecision, list[RuntimeParameter]]:
    candidates = by_label.get(_label_key(field.label), [])
    if len(candidates) == 1:
        return _ParameterDecision([candidates[0].parm_id], source="houdini-label"), []
    if len(candidates) > 1:
        grouped = [
            candidate
            for candidate in candidates
            if _group_matches_folder(field.group_path, candidate.folder_path)
        ]
        if len(grouped) == 1:
            return _ParameterDecision(
                [grouped[0].parm_id], source="houdini-folder-label"
            ), []
        ambiguous = grouped or candidates
        return _ParameterDecision(
            [], reason="ambiguous_label", missing_ids=missing_ids or []
        ), ambiguous
    return _ParameterDecision(
        [], reason=no_match_reason, missing_ids=missing_ids or []
    ), []


def _resolve_parameter_order(
    *,
    documented: tuple[DocumentedField, ...],
    decisions: dict[int, _ParameterDecision],
    ambiguous_candidates: dict[int, list[RuntimeParameter]],
    runtime_parameters: list[RuntimeParameter],
) -> None:
    # Resolve duplicate-label cases only when surrounding resolved fields make one
    # runtime candidate possible. This deliberately preserves the previous conservative rule.
    for field in documented:
        candidates = ambiguous_candidates.get(field.ordinal)
        if not candidates:
            continue
        lower = _nearest_runtime_ordinal(
            documented, decisions, runtime_parameters, field.ordinal, -1
        )
        upper = _nearest_runtime_ordinal(
            documented, decisions, runtime_parameters, field.ordinal, 1
        )
        ordered = [
            candidate
            for candidate in candidates
            if (lower is None or candidate.ordinal > lower)
            and (upper is None or candidate.ordinal < upper)
        ]
        if len(ordered) == 1:
            decisions[field.ordinal] = _ParameterDecision(
                [ordered[0].parm_id],
                source="houdini-order",
            )


def _parameter_resolution_counts(total: int) -> dict[str, int]:
    return {
        "parameter_total": total,
        "parameter_resolved": 0,
        "parameter_unresolved": 0,
        "parameter_resolved_by_doc_id": 0,
        "parameter_resolved_by_houdini": 0,
        "parameter_resolved_by_manual": 0,
    }


def _append_parameter_resolution(
    *,
    node_type_id: str,
    relative_path: str,
    canonical_name: str | None,
    field: DocumentedField,
    decision: _ParameterDecision,
    parameter_for_id: Callable[[str, DocumentedField], NodeParameter],
    doc_rows: list[NodeParameterDoc],
    link_rows: list[NodeParameterLink],
    unresolved: list[dict[str, object]],
    counts: dict[str, int],
) -> None:
    missing_ids = decision.missing_ids
    doc_parameter_id = _parameter_id(node_type_id, f"doc:{field.ordinal}:{field.label}")
    fully_resolved = bool(decision.resolved_ids) and decision.reason is None
    if fully_resolved:
        counts["parameter_resolved"] += 1
        if decision.source == "manual":
            counts["parameter_resolved_by_manual"] += 1
        elif decision.source == "bookish-id":
            counts["parameter_resolved_by_doc_id"] += 1
        else:
            counts["parameter_resolved_by_houdini"] += 1
    else:
        counts["parameter_unresolved"] += 1
        unresolved.append(
            {
                "document": relative_path,
                "node": canonical_name,
                "label": field.label,
                "group_path": list(field.group_path),
                "doc_ordinal": field.ordinal,
                "explicit_id": field.explicit_id,
                "explicit_ids": list(field.explicit_ids),
                "resolved_ids": list(decision.resolved_ids),
                "missing_ids": list(missing_ids),
                "reason": decision.reason or "no_houdini_match",
            }
        )

    doc_rows.append(
        NodeParameterDoc(
            doc_parameter_id=doc_parameter_id,
            node_type_id=node_type_id,
            ordinal=field.ordinal,
            label=field.label,
            group_path=field.group_path,
            description=field.description,
            explicit_ids=field.explicit_ids,
            unresolved_reason=None
            if fully_resolved
            else (decision.reason or "no_houdini_match"),
        )
    )
    for link_ordinal, parm_id in enumerate(decision.resolved_ids):
        parameter = parameter_for_id(parm_id, field)
        link_rows.append(
            NodeParameterLink(
                doc_parameter_id=doc_parameter_id,
                parameter_id=parameter.parameter_id,
                ordinal=link_ordinal,
                resolution_source=decision.source or "unknown",
            )
        )


def _nearest_runtime_ordinal(
    documented: tuple[DocumentedField, ...],
    decisions: dict[int, _ParameterDecision],
    runtime_parameters: list[RuntimeParameter],
    ordinal: int,
    direction: int,
) -> int | None:
    runtime_ordinals = {
        parameter.parm_id: parameter.ordinal for parameter in runtime_parameters
    }
    index = ordinal + direction
    while 0 <= index < len(documented):
        decision = decisions.get(index)
        resolved_ids = decision.resolved_ids if decision is not None else []
        ordinals = [
            runtime_ordinals[parm_id]
            for parm_id in resolved_ids
            if parm_id in runtime_ordinals
        ]
        if ordinals:
            return max(ordinals) if direction < 0 else min(ordinals)
        index += direction
    return None


def _group_matches_folder(
    group_path: tuple[str, ...], folder_path: tuple[str, ...]
) -> bool:
    if not group_path or not folder_path:
        return False
    group_keys = tuple(_label_key(value) for value in group_path if _label_key(value))
    folder_keys = tuple(_label_key(value) for value in folder_path if _label_key(value))
    if not group_keys or not folder_keys:
        return False
    if (
        len(group_keys) <= len(folder_keys)
        and folder_keys[-len(group_keys) :] == group_keys
    ):
        return True
    return False


def _parameter_override(
    overrides: list[dict[str, object]],
    relative_path: str,
    field: DocumentedField,
) -> tuple[str, ...]:
    for item in overrides:
        if str(item.get("document") or "") != relative_path:
            continue
        if _safe_int(item.get("doc_ordinal"), -1) != field.ordinal:
            continue
        parm_ids = item.get("parm_ids")
        if isinstance(parm_ids, list):
            values = tuple(
                str(value).strip()
                for value in parm_ids
                if isinstance(value, str) and value.strip()
            )
            if values:
                return values
        parm_id = item.get("parm_id")
        if isinstance(parm_id, str) and parm_id.strip():
            return (parm_id.strip(),)
    return ()


def _runtime_parm_id(
    value: str,
    by_id: dict[str, RuntimeParameter],
    by_id_without_hash: dict[str, list[RuntimeParameter]],
) -> str | None:
    if value in by_id:
        return value
    candidates = by_id_without_hash.get(value.replace("#", ""), [])
    return candidates[0].parm_id if len(candidates) == 1 else None


def _parameter_id(node_type_id: str, value: str) -> str:
    return hashlib.sha256(f"{node_type_id}|{value}".encode("utf-8")).hexdigest()[:32]


def _label_key(value: str) -> str:
    value = clean_label(value).casefold()
    return "".join(character for character in value if character.isalnum())


def _safe_int(value: object, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
