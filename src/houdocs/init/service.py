from __future__ import annotations

from pathlib import Path

from houdocs.docs.bookish import BookishDocumentParser
from houdocs.docs.index import DocumentIndexer
from houdocs.docs.repository import DocumentRepository
from houdocs.init.report import InitReporter, write_json_atomic
from houdocs.init.runtime import HoudiniRuntime, RuntimeSnapshot
from houdocs.paths import VersionPaths


class InitService:
    def __init__(
        self,
        *,
        runtime: HoudiniRuntime | None = None,
        data_root: Path | None = None,
    ) -> None:
        self.runtime = runtime or HoudiniRuntime()
        self.data_root = data_root

    def run(self, requested_version: str | None) -> dict[str, object]:
        installation = self.runtime.select(requested_version)
        snapshot = self.runtime.probe(
            installation,
            requested_version=requested_version,
        )
        paths = VersionPaths.for_version(snapshot.houdini_version, data_root=self.data_root)
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
        documents = indexer.index_all(
            snapshot.help_directories,
            houdini_version=snapshot.houdini_version,
            on_error=lambda kind, detail, document: reporter.error(
                kind, detail, document=document
            ),
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
            artifacts={
                "docs_database": str(paths.database),
                "docs_cache": str(paths.docs),
                "node_types": str(node_dump_path),
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
