from __future__ import annotations

from pathlib import Path

from houdocs.config import HouDocsConfig
from houdocs.docs.bookish import BookishDocumentParser
from houdocs.docs.index import DocumentIndexer
from houdocs.docs.repository import DocumentRepository
from houdocs.init.progress import InitProgress
from houdocs.init.report import InitReporter, write_json_atomic
from houdocs.init.runtime import HoudiniRuntime, RuntimeSnapshot
from houdocs.node.index import NodeIndexer
from houdocs.node.repository import NodeRepository
from houdocs.node.unresolved import unresolved_path
from houdocs.python_docs.index import PythonIndexer
from houdocs.python_docs.repository import PythonRepository
from houdocs.vex_docs.index import VexIndexer
from houdocs.vex_docs.repository import VexRepository
from houdocs.paths import VersionPaths
from houdocs.search.embedding import Model2VecEmbeddingProvider
from houdocs.search.hybrid import HybridSearchBackend
from houdocs.search.index import SearchIndexer
from houdocs.search.store import SearchStore


class InitService:
    def __init__(
        self,
        *,
        runtime: HoudiniRuntime | None = None,
        data_root: Path | None = None,
    ) -> None:
        self.runtime = runtime or HoudiniRuntime()
        self.data_root = data_root

    def run(
        self,
        requested_version: str | None,
        *,
        config: HouDocsConfig,
        progress: InitProgress | None = None,
    ) -> dict[str, object]:
        progress_view = progress or InitProgress(False)
        with progress_view.phase("inspect Houdini"):
            installation = self.runtime.select(requested_version)
            progress_view.show(
                f"Starting and inspecting Houdini {installation.version_string}"
            )
            snapshot = self.runtime.probe(
                installation,
                requested_version=requested_version,
            )
            paths = VersionPaths.for_version(
                snapshot.houdini_version, data_root=self.data_root
            )
            paths.ensure()

        reporter = InitReporter()
        self._collect_runtime_issues(snapshot, reporter)

        node_dump_path = paths.reports / f"houdini-node-types-{snapshot.houdini_version}.json"
        write_json_atomic(node_dump_path, snapshot.payload)

        repository = DocumentRepository(paths.database)
        indexer = DocumentIndexer(
            repository=repository,
            parser=BookishDocumentParser(),
            cache_directory=paths.docs,
        )
        with progress_view.phase("index documents"):
            documents = indexer.index_all(
                snapshot.help_directories,
                houdini_version=snapshot.houdini_version,
                on_error=lambda kind, detail, document: reporter.error(
                    kind, detail, document=document
                ),
                progress=progress_view.indexing if progress_view.enabled else None,
            )

        warning = lambda kind, detail, document, symbol: reporter.warning(
            kind, detail, document=document, symbol=symbol
        )
        error = lambda kind, detail, document, symbol: reporter.error(
            kind, detail, document=document, symbol=symbol
        )
        with progress_view.phase("index node docs"):
            node = NodeIndexer(
                documents=repository,
                repository=NodeRepository(paths.database),
                docs_directory=paths.docs,
                report_directory=paths.reports,
            ).index_all(
                snapshot.node_types,
                houdini_version=snapshot.houdini_version,
                on_warning=warning,
                on_error=error,
            )
        python_repository = PythonRepository(paths.database)
        with progress_view.phase("index HOM symbols"):
            python = PythonIndexer(
                documents=repository,
                repository=python_repository,
                docs_directory=paths.docs,
            ).index_all(on_warning=warning, on_error=error)
        vex_repository = VexRepository(paths.database)
        with progress_view.phase("index VEX functions"):
            vex = VexIndexer(
                documents=repository,
                repository=vex_repository,
                docs_directory=paths.docs,
            ).index_all(on_warning=warning, on_error=error)

        with progress_view.phase("build search index"):
            search_backend = HybridSearchBackend(
                database=paths.search_database,
                embeddings=Model2VecEmbeddingProvider(),
                rrf_k=config.search_hybrid.rrf_k,
                candidate_multiplier=config.search_hybrid.candidate_multiplier,
                candidate_min=config.search_hybrid.candidate_min,
            )
            search = SearchIndexer(
                documents=repository,
                python_documents=python_repository,
                vex_documents=vex_repository,
                backend=search_backend,
                store=SearchStore(paths.search_database),
                embedding_profile=config.search_embedding.docs_profile,
            ).index_all(
                embedding_progress=(
                    progress_view.embedding if progress_view.enabled else None
                )
            )

        report_path = paths.reports / "init-report.json"
        report = reporter.build(
            houdini_version=snapshot.houdini_version,
            requested_version=requested_version,
            installation_root=str(installation.root),
            help_directories=[str(path) for path in snapshot.help_directories],
            runtime={
                "node_types": len(snapshot.node_types),
                "parameters": snapshot.parameter_count,
                "parameter_errors": snapshot.parameter_error_count,
            },
            documents=documents,
            node=node,
            python=python,
            vex=vex,
            search=search,
            artifacts={
                "docs_database": str(paths.database),
                "docs_cache": str(paths.docs),
                "search_database": str(paths.search_database),
                "node_types": str(node_dump_path),
                "node_unresolved": str(unresolved_path(paths.reports, snapshot.houdini_version)),
                "report": str(report_path),
            },
        )
        write_json_atomic(report_path, report)
        return report

    @staticmethod
    def _collect_runtime_issues(snapshot: RuntimeSnapshot, reporter: InitReporter) -> None:
        for node in snapshot.node_types:
            parameter_error = node.get("parameter_error")
            if not isinstance(parameter_error, str) or not parameter_error:
                continue
            symbol = node.get("canonical_name")
            reporter.warning(
                "node_parameter_introspection_error",
                parameter_error,
                symbol=symbol if isinstance(symbol, str) else None,
            )
