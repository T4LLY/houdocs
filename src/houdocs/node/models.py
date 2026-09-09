from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NodeTypeLookup:
    context: str
    internal_name: str
    title: str | None = None


@dataclass(frozen=True)
class DocumentedField:
    ordinal: int
    label: str
    description: str
    group_path: tuple[str, ...] = ()
    explicit_ids: tuple[str, ...] = ()

    @property
    def explicit_id(self) -> str | None:
        return ", ".join(self.explicit_ids) if self.explicit_ids else None


@dataclass(frozen=True)
class RelatedLink:
    ordinal: int
    kind: str
    target: str
    label: str | None
    node_lookup: NodeTypeLookup | None = None


@dataclass(frozen=True)
class NodeDocSource:
    page_type: str | None
    context: str | None
    namespace: str | None
    internal_name: str | None
    version: str | None
    version_source: str | None
    title: str
    inputs: tuple[DocumentedField, ...]
    outputs: tuple[DocumentedField, ...]
    parameters: tuple[DocumentedField, ...]
    related: tuple[RelatedLink, ...]


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
class RuntimeParameter:
    ordinal: int
    parm_id: str
    label: str
    folder_path: tuple[str, ...]
    parm_type: str
    multiparm: bool


@dataclass(frozen=True)
class RuntimeNodeType:
    context: str
    requested_internal_name: str
    category: str
    internal_name: str
    canonical_name: str
    min_inputs: int | None
    max_inputs: int | None
    max_outputs: int | None
    parameters: tuple[RuntimeParameter, ...]


@dataclass(frozen=True)
class NodeTypeDocument:
    node_type_id: str
    document_id: str
    context: str
    namespace: str | None
    internal_name: str
    version: str | None
    category: str | None
    canonical_name: str | None
    priority: int
    resolution_source: str | None
    unresolved_reason: str | None


@dataclass(frozen=True)
class NodeParameter:
    parameter_id: str
    node_type_id: str
    ordinal: int
    parm_id: str
    label: str
    folder_path: tuple[str, ...]
    parm_type: str | None
    multiparm: bool
    runtime_present: bool


@dataclass(frozen=True)
class NodeParameterDoc:
    doc_parameter_id: str
    node_type_id: str
    ordinal: int
    label: str
    group_path: tuple[str, ...]
    description: str
    explicit_ids: tuple[str, ...]
    unresolved_reason: str | None


@dataclass(frozen=True)
class NodeParameterLink:
    doc_parameter_id: str
    parameter_id: str
    ordinal: int
    resolution_source: str


@dataclass(frozen=True)
class NodePort:
    node_type_id: str
    direction: str
    ordinal: int
    label: str
    description: str


@dataclass(frozen=True)
class NodeRelated:
    node_type_id: str
    ordinal: int
    kind: str
    target: str
    label: str | None
    canonical_target: str | None
    resolved: bool
    unresolved_reason: str | None
