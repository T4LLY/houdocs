from __future__ import annotations

from collections.abc import Callable
from pathlib import Path, PurePosixPath

from houdocs.docs.models import Document
from houdocs.errors import HouDocsError
from houdocs.docs.repository import DocumentRepository
from houdocs.node.models import RuntimeNodeType, RuntimeParameter
from houdocs.node.parser import context_for_category, parse_node_document, should_index_node_document
from houdocs.node.repository import NodeRecord, NodeRepository
from houdocs.node.resolver import NodeTypeCatalog, build_node_metadata
from houdocs.node.unresolved import load_overrides, unresolved_path, write_unresolved

IssueCallback = Callable[[str, str, str | None, str | None], None]


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
        runtime_rows: tuple[dict[str, object], ...],
        *,
        houdini_version: str,
        on_warning: IssueCallback | None = None,
        on_error: IssueCallback | None = None,
        overrides: dict[str, list[dict[str, object]]] | None = None,
        write_report: bool = True,
        fail_on_error: bool = False,
    ) -> dict[str, int | str]:
        catalog = NodeTypeCatalog(_runtime_node_types(runtime_rows))
        unresolved_file = unresolved_path(self.report_directory, houdini_version)
        active_overrides = overrides if overrides is not None else load_overrides(unresolved_file)
        records: list[NodeRecord] = []
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
                _issue(
                    on_error,
                    "node_document_parse_error",
                    f"{type(exc).__name__}: {exc}",
                    document.relative_path,
                    None,
                )
                continue

            node_type, parameters, parameter_docs, parameter_links, ports, related, row_counts, missing = result
            records.append((node_type, parameters, parameter_docs, parameter_links, ports, related))
            counts["documents"] += 1
            for key, value in row_counts.items():
                counts[key] += value
            for key in unresolved:
                unresolved[key].extend(missing[key])

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
        on_error: IssueCallback | None,
    ) -> str | None:
        path = self.docs_directory / PurePosixPath(document.relative_path)
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            _issue(
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
        callback: IssueCallback | None,
    ) -> None:
        if callback is None:
            return
        for item in unresolved["node_types"]:
            _issue(
                callback,
                "node_type_unresolved",
                str(item.get("reason") or "unresolved"),
                _string(item.get("document")),
                _string(item.get("internal_name")),
            )
        for item in unresolved["parameters"]:
            _issue(
                callback,
                "node_parameter_unresolved",
                str(item.get("reason") or "unresolved"),
                _string(item.get("document")),
                _string(item.get("node")),
            )
        for item in unresolved["related"]:
            _issue(
                callback,
                "node_related_unresolved",
                str(item.get("reason") or "unresolved"),
                _string(item.get("document")),
                _string(item.get("node")),
            )


def _runtime_node_types(rows: tuple[dict[str, object], ...]) -> tuple[RuntimeNodeType, ...]:
    nodes: list[RuntimeNodeType] = []
    for row in rows:
        category = _string(row.get("category"))
        name = _string(row.get("name"))
        canonical = _string(row.get("canonical_name"))
        if not category or not name or not canonical:
            continue
        context = context_for_category(category)
        if context is None:
            continue
        parameters: list[RuntimeParameter] = []
        raw_parameters = row.get("parameters")
        if isinstance(raw_parameters, list):
            for raw in raw_parameters:
                if not isinstance(raw, dict):
                    continue
                parm_id = _string(raw.get("id"))
                ordinal = raw.get("parameter_ordinal")
                if not parm_id or not isinstance(ordinal, int):
                    continue
                folder_path = raw.get("folder_path")
                parameters.append(
                    RuntimeParameter(
                        ordinal=ordinal,
                        parm_id=parm_id,
                        label=_string(raw.get("label")) or "",
                        folder_path=tuple(
                            str(value) for value in folder_path if isinstance(value, str)
                        ) if isinstance(folder_path, list) else (),
                        parm_type=_string(raw.get("type")) or "",
                        multiparm=bool(raw.get("is_multiparm")),
                    )
                )
        nodes.append(
            RuntimeNodeType(
                context=context,
                requested_internal_name=name,
                category=category,
                internal_name=name,
                canonical_name=canonical,
                min_inputs=_integer(row.get("min_inputs")),
                max_inputs=_integer(row.get("max_inputs")),
                max_outputs=_integer(row.get("max_outputs")),
                parameters=tuple(parameters),
            )
        )
    return tuple(nodes)


def _issue(
    callback: IssueCallback | None,
    kind: str,
    detail: str,
    document: str | None,
    symbol: str | None,
) -> None:
    if callback is not None:
        callback(kind, detail, document, symbol)


def _string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _integer(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None
