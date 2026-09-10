from __future__ import annotations

from houdocs.node.models import DocumentedField, NodePort, RuntimeNodeType


def resolve_ports(
    *,
    node_type_id: str,
    runtime: RuntimeNodeType | None,
    inputs: tuple[DocumentedField, ...],
    outputs: tuple[DocumentedField, ...],
) -> list[NodePort]:
    return _ports_for_direction(
        node_type_id=node_type_id,
        direction="input",
        documented=inputs,
        minimum=runtime.min_inputs if runtime is not None else None,
        maximum=runtime.max_inputs if runtime is not None else None,
    ) + _ports_for_direction(
        node_type_id=node_type_id,
        direction="output",
        documented=outputs,
        minimum=None,
        maximum=runtime.max_outputs if runtime is not None else None,
    )


def _ports_for_direction(
    *,
    node_type_id: str,
    direction: str,
    documented: tuple[DocumentedField, ...],
    minimum: int | None,
    maximum: int | None,
) -> list[NodePort]:
    count = _runtime_port_count(
        documented_count=len(documented),
        minimum=minimum,
        maximum=maximum,
    )
    title = "Input" if direction == "input" else "Output"
    result: list[NodePort] = []
    for index in range(count):
        field = documented[index] if index < len(documented) else None
        label = (
            field.label if field is not None and field.label else f"{title} {index + 1}"
        )
        result.append(
            NodePort(
                node_type_id=node_type_id,
                direction=direction,
                ordinal=index,
                label=label,
                description=field.description if field is not None else "",
            )
        )
    return result


def _runtime_port_count(
    *,
    documented_count: int,
    minimum: int | None,
    maximum: int | None,
) -> int:
    if maximum is None:
        return documented_count
    maximum = max(0, maximum)
    if maximum >= 9999:
        minimum_count = max(0, minimum or 0)
        return max(documented_count, minimum_count, 1 if maximum else 0)
    return max(documented_count, maximum)
