from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

from houdocs.config import HouDocsConfig
from houdocs.db.schema import initialize_docs_database
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
from houdocs.search.store import initialize_search_database
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
        # Validate manual work before creating any staged output. Existing assist
        # data is user-authored state and must never be silently discarded.
        overrides = load_overrides(unresolved_file)

        staged_database = _staging_database(paths.database)
        staged_search_database = _staging_database(paths.search_database)
        staged_docs = paths.root / ".init-staging-docs"
        staged_reports = paths.root / ".init-staging-reports"
        _prepare_staging(
            staged_database, staged_search_database, staged_docs, staged_reports
        )

        staged_unresolved = unresolved_path(staged_reports, snapshot.houdini_version)
        staged_node_dump = (
            staged_reports / f"houdini-node-types-{snapshot.houdini_version}.json"
        )
        staged_report = staged_reports / "init-report.json"
        final_node_dump = (
            paths.reports / f"houdini-node-types-{snapshot.houdini_version}.json"
        )
        final_report = paths.reports / "init-report.json"

        try:
            reporter = InitReporter()
            self._collect_runtime_issues(snapshot, reporter)

            initialize_docs_database(staged_database)
            repository = DocumentRepository(staged_database)
            indexer = DocumentIndexer(
                repository=repository,
                parser=BookishDocumentParser(),
                cache_directory=staged_docs,
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
                    repository=NodeRepository(staged_database),
                    docs_directory=staged_docs,
                    report_directory=staged_reports,
                ).index_all(
                    snapshot.node_types,
                    houdini_version=snapshot.houdini_version,
                    on_warning=warning,
                    on_error=error,
                    overrides=overrides,
                )
            python_repository = PythonRepository(staged_database)
            with progress_view.phase("index HOM symbols"):
                python = PythonIndexer(
                    documents=repository,
                    repository=python_repository,
                    docs_directory=staged_docs,
                ).index_all(on_warning=warning, on_error=error)
            vex_repository = VexRepository(staged_database)
            with progress_view.phase("index VEX functions"):
                vex = VexIndexer(
                    documents=repository,
                    repository=vex_repository,
                    docs_directory=staged_docs,
                ).index_all(on_warning=warning, on_error=error)

            with progress_view.phase("build search index"):
                initialize_search_database(staged_search_database)
                search_backend = HybridSearchBackend(
                    database=staged_search_database,
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
                node={**node, "unresolved_file": str(unresolved_file)},
                python=python,
                vex=vex,
                search=search,
                artifacts={
                    "docs_database": str(paths.database),
                    "docs_cache": str(paths.docs),
                    "search_database": str(paths.search_database),
                    "node_types": str(final_node_dump),
                    "node_unresolved": str(unresolved_file),
                    "report": str(final_report),
                },
            )
            write_json_atomic(staged_node_dump, snapshot.payload)
            write_json_atomic(staged_report, report)

            _promote_init_artifacts(
                database=(staged_database, paths.database),
                search_database=(staged_search_database, paths.search_database),
                artifacts=(
                    (staged_docs, paths.docs),
                    (staged_unresolved, unresolved_file),
                    (staged_node_dump, final_node_dump),
                    (staged_report, final_report),
                ),
            )
            return report
        finally:
            _discard_staging(
                staged_database, staged_search_database, staged_docs, staged_reports
            )

    def import_assist(self, houdini_version: str) -> int:
        paths = VersionPaths.for_version(houdini_version, data_root=self.data_root)
        if not paths.database.is_file():
            raise HouDocsError("docs_index_missing", "Run houdocs init first.")

        unresolved_file = unresolved_path(paths.reports, houdini_version)
        if not unresolved_file.is_file():
            raise HouDocsError(
                "node_assist_missing",
                f"Node assist report is missing for Houdini {houdini_version}.",
            )
        overrides = load_overrides(unresolved_file)
        return NodeRepository(paths.database).apply_parameter_overrides(
            overrides["parameters"]
        )

    @staticmethod
    def _collect_runtime_issues(
        snapshot: RuntimeSnapshot, reporter: InitReporter
    ) -> None:
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


def _staging_database(path: Path) -> Path:
    return Path(str(path) + ".init-new")


def _sqlite_family(path: Path) -> tuple[Path, ...]:
    return (
        path,
        Path(str(path) + "-wal"),
        Path(str(path) + "-shm"),
        Path(str(path) + "-journal"),
    )


def _remove_path(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


def _prepare_staging(
    database: Path,
    search_database: Path,
    docs: Path,
    reports: Path,
) -> None:
    for path in (*_sqlite_family(database), *_sqlite_family(search_database)):
        _remove_path(path)
    _remove_path(docs)
    _remove_path(reports)
    docs.mkdir(parents=True, exist_ok=True)
    reports.mkdir(parents=True, exist_ok=True)


def _discard_staging(
    database: Path,
    search_database: Path,
    docs: Path,
    reports: Path,
) -> None:
    for path in (*_sqlite_family(database), *_sqlite_family(search_database)):
        try:
            _remove_path(path)
        except OSError:
            pass
    for path in (docs, reports):
        try:
            _remove_path(path)
        except OSError:
            pass


def _checkpoint_sqlite_database(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        connection.close()
    for sidecar in _sqlite_family(path)[1:]:
        sidecar.unlink(missing_ok=True)


def _backup_path(path: Path) -> Path:
    return Path(str(path) + ".init-backup")


def _promote_init_artifacts(
    *,
    database: tuple[Path, Path],
    search_database: tuple[Path, Path],
    artifacts: tuple[tuple[Path, Path], ...],
) -> None:
    staged_database, final_database = database
    staged_search, final_search = search_database
    _checkpoint_sqlite_database(staged_database)
    _checkpoint_sqlite_database(staged_search)

    staged_pairs = (
        (staged_database, final_database),
        (staged_search, final_search),
        *artifacts,
    )
    for staged, _final in staged_pairs:
        if not staged.exists():
            raise HouDocsError(
                "init_staging_incomplete",
                f"Initialization staging artifact is missing: {staged}",
            )

    final_paths: list[Path] = []
    for final in (final_database, final_search):
        final_paths.extend(_sqlite_family(final))
    final_paths.extend(final for _staged, final in artifacts)

    backup_pairs: list[tuple[Path, Path]] = []
    for final in final_paths:
        backup = _backup_path(final)
        if backup.exists():
            raise HouDocsError(
                "init_recovery_required",
                f"Previous init backup still exists: {backup}",
            )
        if final.exists():
            backup_pairs.append((backup, final))

    promoted: list[Path] = []
    try:
        for backup, final in backup_pairs:
            final.replace(backup)
        for staged, final in staged_pairs:
            staged.replace(final)
            promoted.append(final)
    except BaseException:
        for final in reversed(promoted):
            try:
                _remove_path(final)
            except OSError:
                pass
        for backup, final in reversed(backup_pairs):
            if backup.exists():
                backup.replace(final)
        raise
    else:
        for backup, _final in backup_pairs:
            try:
                _remove_path(backup)
            except OSError:
                # The new initialized state is already committed. A leftover
                # backup is safer than turning cleanup failure into a false init
                # failure; the next init will report init_recovery_required.
                pass
