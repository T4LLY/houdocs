from __future__ import annotations

import json
from pathlib import Path

from houdocs.config import HouDocsConfig
from houdocs.docs.bookish import BookishDocumentParser
from houdocs.docs.index import DocumentIndexer
from houdocs.docs.repository import DocumentRepository
from houdocs.errors import HouDocsError
from houdocs.init.progress import InitProgress
from houdocs.init.report import InitReporter, write_json_atomic
from houdocs.init.runtime import HoudiniRuntime, RuntimeSnapshot
from houdocs.node.index import NodeIndexer
from houdocs.node.repository import NodeRepository
from houdocs.node.unresolved import load_overrides, unresolved_path
from houdocs.paths import VersionPaths
from houdocs.python_docs.index import PythonIndexer
from houdocs.python_docs.repository import PythonRepository
from houdocs.search.embedding import Model2VecEmbeddingProvider
from houdocs.search.hybrid import HybridSearchBackend
from houdocs.search.index import SearchIndexer
from houdocs.search.store import SearchStore
from houdocs.search.tokens import count_openai_tokens
from houdocs.vex_docs.index import VexIndexer
from houdocs.vex_docs.repository import VexRepository


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

        unresolved_file = unresolved_path(paths.reports, snapshot.houdini_version)
        # Validate and retain manual work before touching either database. Existing
        # assist data is user-authored state and must never be silently discarded.
        try:
            unresolved_before = (
                unresolved_file.read_bytes() if unresolved_file.is_file() else None
            )
        except OSError as exc:
            raise HouDocsError(
                "node_assist_invalid",
                f"Unable to read node assist report: {unresolved_file}",
                detail=str(exc),
            ) from exc
        overrides = load_overrides(unresolved_file)
        report_path = paths.reports / "init-report.json"

        try:
            # init is a full rebuild. There are intentionally no schema migrations,
            # so both SQLite databases must start from the current schema.
            _reset_sqlite_database(paths.database)
            _reset_sqlite_database(paths.search_database)
            report_path.unlink(missing_ok=True)

            reporter = InitReporter()
            self._collect_runtime_issues(snapshot, reporter)

            node_dump_path = (
                paths.reports
                / f"houdini-node-types-{snapshot.houdini_version}.json"
            )
            write_json_atomic(node_dump_path, snapshot.payload)

            repository = DocumentRepository(paths.database)
            indexer = DocumentIndexer(
                repository=repository,
                parser=BookishDocumentParser(),
                cache_directory=paths.docs,
                token_counter=count_openai_tokens,
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
                    overrides=overrides,
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
                    "node_unresolved": str(unresolved_file),
                    "report": str(report_path),
                },
            )
            write_json_atomic(report_path, report)
            return report
        except BaseException:
            _reset_sqlite_database(paths.database)
            _reset_sqlite_database(paths.search_database)
            report_path.unlink(missing_ok=True)
            _restore_file(unresolved_file, unresolved_before)
            raise

    def import_assist(self, houdini_version: str) -> int:
        paths = VersionPaths.for_version(houdini_version, data_root=self.data_root)
        if not paths.database.is_file():
            raise HouDocsError("docs_index_missing", "Run houdocs init first.")
        if not paths.docs.is_dir():
            raise HouDocsError(
                "docs_cache_missing",
                f"Documentation cache is missing for Houdini {houdini_version}.",
            )

        unresolved_file = unresolved_path(paths.reports, houdini_version)
        if not unresolved_file.is_file():
            raise HouDocsError(
                "node_assist_missing",
                f"Node assist report is missing for Houdini {houdini_version}.",
            )
        overrides = load_overrides(unresolved_file)

        node_dump_path = paths.reports / f"houdini-node-types-{houdini_version}.json"
        try:
            payload = json.loads(node_dump_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise HouDocsError(
                "node_runtime_dump_missing",
                f"Unable to read saved Houdini node metadata for {houdini_version}.",
                detail=str(exc),
            ) from exc

        rows = payload.get("node_types") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise HouDocsError(
                "node_runtime_dump_invalid",
                f"Saved Houdini node metadata is invalid for {houdini_version}.",
            )

        # Import only affects node metadata. The assist report is the source of
        # truth for manual work and is deliberately read-only in this mode.
        result = NodeIndexer(
            documents=DocumentRepository(paths.database),
            repository=NodeRepository(paths.database),
            docs_directory=paths.docs,
            report_directory=paths.reports,
        ).index_all(
            tuple(item for item in rows if isinstance(item, dict)),
            houdini_version=houdini_version,
            overrides=overrides,
            write_report=False,
            fail_on_error=True,
        )
        return int(result.get("parameter_resolved_by_manual", 0))

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


def _reset_sqlite_database(path: Path) -> None:
    for candidate in (
        path,
        Path(str(path) + "-wal"),
        Path(str(path) + "-shm"),
        Path(str(path) + "-journal"),
    ):
        candidate.unlink(missing_ok=True)


def _restore_file(path: Path, content: bytes | None) -> None:
    if content is None:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".restore.tmp")
    temporary.write_bytes(content)
    temporary.replace(path)
