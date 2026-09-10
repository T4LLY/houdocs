from __future__ import annotations

from houdocs.node.models import NodeTypeLookup, RuntimeNodeType
from houdocs.node.parser import category_for_context


class NodeTypeCatalog:
    def __init__(self, nodes: tuple[RuntimeNodeType, ...] = ()) -> None:
        self._nodes = {
            (
                _normalize_key(node.context),
                _normalize_key(node.requested_internal_name),
            ): node
            for node in nodes
        }

    def resolve(self, lookup: NodeTypeLookup) -> RuntimeNodeType | None:
        return self._nodes.get(
            (_normalize_key(lookup.context), _normalize_key(lookup.internal_name))
        )

    def canonical_for(self, lookup: NodeTypeLookup) -> str | None:
        runtime = self.resolve(lookup)
        if runtime is not None:
            return runtime.canonical_name
        category = category_for_context(lookup.context)
        if category is None or not lookup.internal_name:
            return None
        return f"{category}/{lookup.internal_name}"


def _normalize_key(value: str) -> str:
    return value.casefold().strip()
