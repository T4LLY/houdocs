from __future__ import annotations

from houdocs.node.catalog import NodeTypeCatalog
from houdocs.node.models import NodeRelated, RelatedLink


def resolve_related(
    *,
    node_type_id: str,
    relative_path: str,
    canonical_name: str | None,
    related: tuple[RelatedLink, ...],
    catalog: NodeTypeCatalog,
    overrides: list[dict[str, object]],
) -> tuple[list[NodeRelated], dict[str, int], list[dict[str, object]]]:
    rows: list[NodeRelated] = []
    unresolved: list[dict[str, object]] = []
    resolved_count = 0
    for link in related:
        canonical_target: str | None = None
        reason: str | None = None
        manual = _related_override(overrides, relative_path, link)
        if manual:
            canonical_target = manual
        elif link.kind == "node":
            if link.node_lookup is not None:
                canonical_target = catalog.canonical_for(link.node_lookup)
            if canonical_target is None:
                reason = "node_target_unresolved"
        elif link.kind != "unknown":
            canonical_target = link.target
        else:
            reason = "unknown_related_target"

        resolved = canonical_target is not None
        if resolved:
            resolved_count += 1
        else:
            unresolved.append(
                {
                    "document": relative_path,
                    "node": canonical_name,
                    "ordinal": link.ordinal,
                    "kind": link.kind,
                    "target": link.target,
                    "label": link.label,
                    "reason": reason,
                }
            )
        rows.append(
            NodeRelated(
                node_type_id=node_type_id,
                ordinal=link.ordinal,
                kind=link.kind,
                target=link.target,
                label=link.label,
                canonical_target=canonical_target,
                resolved=resolved,
                unresolved_reason=reason,
            )
        )
    return (
        rows,
        {
            "related_total": len(related),
            "related_resolved": resolved_count,
            "related_unresolved": len(related) - resolved_count,
        },
        unresolved,
    )


def _related_override(
    overrides: list[dict[str, object]],
    relative_path: str,
    link: RelatedLink,
) -> str | None:
    for item in overrides:
        if str(item.get("document") or "") != relative_path:
            continue
        if _safe_int(item.get("ordinal"), -1) != link.ordinal:
            continue
        target = item.get("canonical_target")
        if isinstance(target, str) and target.strip():
            return target.strip()
    return None


def _safe_int(value: object, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
