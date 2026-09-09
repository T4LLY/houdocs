from __future__ import annotations

from pathlib import Path, PurePosixPath

from houdocs.docs.models import Document
from houdocs.docs.repository import DocumentRepository
from houdocs.errors import HouDocsError
from houdocs.specialized_indexing import SpecializedIssueCallback, emit_specialized_issue
from houdocs.init.probe import RuntimeNodeSnapshot
from houdocs.node.models import NodeDocumentRecord, RuntimeNodeType, RuntimeParameter
from houdocs.node.parser import context_for_category, parse_node_document, should_index_node_document
from houdocs.node.repository import NodeRepository
from houdocs.node.resolver import NodeTypeCatalog, build_node_metadata
from houdocs.node.unresolved import load_overrides, unresolved_path, write_unresolved


class NodeIndexer:
    def __init__(
        self,
        *,
        documents: DocumentRepository,
        repository: NodeRepository,
        docs_directory: Path,
        report_directory: Path,
    ) -> None:
        self.documents = documents
        self.repository = repository
        self.docs_directory = docs_directory
        self.report_directory = report_directory

    def index_all(
        self,
        runtime_nodes: tuple[RuntimeNodeSnapshot, ...],
        *,
        houdini_version: str,
        on_warning: SpecializedIssueCallback | None = None,
        on_error: SpecializedIssueCallback | None = None,
        overrides: dict[str, list[dict[str, object]]] | None = None,
        write_report: bool = True,
        fail_on_error: bool = False,
    ) -> dict[str, int | str]:
        catalog = NodeTypeCatalog(_runtime_node_types(runtime_nodes))
        unresolved_file = unresolved_path(self.report_directory, houdini_version)
        active_overrides = overrides if overrides is not None else load_overrides(unresolved_file)
        records: list[NodeDocumentRecord] = []
        unresolved: dict[str, list[dict[str, object]]] = {
            "node_types": [],
            "parameters": [],
            "related": [],
        }
        counts = {
            "documents": 0,
            "node_type_total": 0,
            "node_type_resolved": 0,
            "node_type_unresolved": 0,
            "parameter_total": 0,
            "parameter_resolved": 0,
            "parameter_unresolved": 0,
            "parameter_resolved_by_doc_id": 0,
            "parameter_resolved_by_houdini": 0,
            "parameter_resolved_by_manual": 0,
            "related_total": 0,
            "related_resolved": 0,
            "related_unresolved": 0,
            "failed": 0,
        }

        for document in self.documents.all_documents():
            if document.kind != "node-doc":
                continue
            source = self._read_source(document, on_error)
            if source is None:
                counts["failed"] += 1
                if fail_on_error:
                    raise HouDocsError(
                        "node_index_incomplete",
                        f"Unable to read node documentation during assist import: {document.relative_path}",
                    )
                continue
            try:
                node_doc = parse_node_document(source, document.relative_path)
                if not should_index_node_document(document.relative_path, node_doc):
                    continue
                result = build_node_metadata(
                    document_id=document.document_id,
                    relative_path=document.relative_path,
                    node_doc=node_doc,
                    catalog=catalog,
                    overrides=active_overrides,
                )
            except Exception as exc:
                counts["failed"] += 1
                if fail_on_error:
                    raise HouDocsError(
                        "node_index_incomplete",
                        f"Unable to parse node documentation during assist import: {document.relative_path}",
                        detail=f"{type(exc).__name__}: {exc}",
                    ) from exc
                emit_specialized_issue(
                    on_error,
                    "node_document_parse_error",
                    f"{type(exc).__name__}: {exc}",
                    document.relative_path,
                    None,
                )
                continue

            records.append(result.record)
            counts["documents"] += 1
            for key, value in result.counts.items():
                counts[key] += value
            for key in unresolved:
                unresolved[key].extend(result.unresolved[key])

        self.repository.replace_all(records)
        if write_report:
            write_unresolved(
                unresolved_file,
                houdini_version=houdini_version,
                overrides=active_overrides,
                unresolved=unresolved,
            )
        self._report_unresolved(unresolved, on_warning)
        return {**counts, "unresolved_file": str(unresolved_file)}

    def _read_source(
        self,
        document: Document,
        on_error: SpecializedIssueCallback | None,
    ) -> str | None:
        path = self.docs_directory / PurePosixPath(document.relative_path)
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            emit_specialized_issue(
                on_error,
                "specialized_source_read_error",
                str(exc),
                document.relative_path,
                None,
            )
            return None

    @staticmethod
    def _report_unresolved(
        unresolved: dict[str, list[dict[str, object]]],
        callback: SpecializedIssueCallback | None,
    ) -> None:
        if callback is None:
            return
        for item in unresolved["node_types"]:
            emit_specialized_issue(
                callback,
                "node_type_unresolved",
                str(item.get("reason") or "unresolved"),
                _string(item.get("document")),
                _string(item.get("internal_name")),
            )
        for item in unresolved["parameters"]:
            emit_specialized_issue(
                callback,
                "node_parameter_unresolved",
                str(item.get("reason") or "unresolved"),
                _string(item.get("document")),
                _string(item.get("node")),
            )
        for item in unresolved["related"]:
            emit_specialized_issue(
                callback,
                "node_related_unresolved",
                str(item.get("reason") or "unresolved"),
                _string(item.get("document")),
                _string(item.get("node")),
            )


def _runtime_node_types(rows: tuple[RuntimeNodeSnapshot, ...]) -> tuple[RuntimeNodeType, ...]:
    nodes: list[RuntimeNodeType] = []
    for row in rows:
        context = context_for_category(row.category)
        if context is None:
            continue
        parameters = tuple(
            RuntimeParameter(
                ordinal=parameter.ordinal,
                parm_id=parameter.parm_id,
                label=parameter.label,
                folder_path=parameter.folder_path,
                parm_type=parameter.parm_type,
                multiparm=parameter.multiparm,
            )
            for parameter in row.parameters
            if parameter.parm_id and parameter.ordinal is not None
        )
        nodes.append(
            RuntimeNodeType(
                context=context,
                requested_internal_name=row.internal_name,
                category=row.category,
                internal_name=row.internal_name,
                canonical_name=row.canonical_name,
                min_inputs=row.min_inputs,
                max_inputs=row.max_inputs,
                max_outputs=row.max_outputs,
                parameters=parameters,
            )
        )
    return tuple(nodes)


def _string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
