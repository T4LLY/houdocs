from __future__ import annotations

import json
import sqlite3
from typing import Annotated, Any, Callable

import typer

from houdocs.config import HouDocsConfig, load_config, resolve_requested_version
from houdocs.docs.read import DocumentReader
from houdocs.docs.repository import DocumentRepository
from houdocs.errors import HouDocsError
from houdocs.init.progress import InitProgress
from houdocs.init.service import InitService
from houdocs.node.read import NodeReader
from houdocs.node.repository import NodeRepository
from houdocs.paths import VersionPaths, resolve_initialized_version
from houdocs.python_docs.read import PythonDocumentReader
from houdocs.python_docs.repository import PythonRepository
from houdocs.search.embedding import Model2VecEmbeddingProvider
from houdocs.search.hybrid import HybridSearchBackend
from houdocs.search.service import DocumentSearchService
from houdocs.vex_docs.read import VexDocumentReader
from houdocs.vex_docs.repository import VexRepository


app = typer.Typer(
    no_args_is_help=True,
    rich_markup_mode=None,
    pretty_exceptions_enable=False,
    context_settings={"color": False},
    help="Indexed Houdini documentation CLI.",
)


def _emit(value: Any, *, exit_code: int | None = None) -> None:
    typer.echo(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    )
    if exit_code is not None:
        raise typer.Exit(exit_code)


def _fail(error: HouDocsError) -> None:
    payload: dict[str, object] = {
        "error": True,
        "code": error.error.code,
        "message": error.error.message,
    }
    if error.error.detail:
        payload["detail"] = error.error.detail
    _emit(payload, exit_code=1)


def _invoke(action: Callable[[], None]) -> None:
    try:
        action()
    except HouDocsError as exc:
        _fail(exc)
    except sqlite3.Error as exc:
        _fail(
            HouDocsError(
                "docs_database_error",
                "Unable to access documentation database.",
                str(exc),
            )
        )


def _init_summary(report: dict[str, object]) -> dict[str, object]:
    documents = report.get("documents")
    node = report.get("node")
    python = report.get("python")
    vex = report.get("vex")
    search = report.get("search")
    issue_counts = report.get("issue_counts")
    artifacts = report.get("artifacts")

    documents = documents if isinstance(documents, dict) else {}
    node = node if isinstance(node, dict) else {}
    python = python if isinstance(python, dict) else {}
    vex = vex if isinstance(vex, dict) else {}
    search = search if isinstance(search, dict) else {}
    issue_counts = issue_counts if isinstance(issue_counts, dict) else {}
    artifacts = artifacts if isinstance(artifacts, dict) else {}

    return {
        "houdini_version": report.get("houdini_version"),
        "documents": documents.get("total", 0),
        "sections": search.get("entries", 0),
        "node_documents": node.get("documents", 0),
        "python_symbols": python.get("symbols", 0),
        "vex_functions": vex.get("functions", 0),
        "search_entries": search.get("entries", 0),
        "warnings": issue_counts.get("warnings", 0),
        "errors": issue_counts.get("errors", 0),
        "report": artifacts.get("report"),
    }


def _offline_paths(config: HouDocsConfig) -> VersionPaths:
    version = resolve_initialized_version(config.houdini.version)
    paths = VersionPaths.for_version(version)
    if not paths.database.is_file():
        raise HouDocsError("docs_index_missing", "Run houdocs init first.")
    return paths


def _search_backend(paths: VersionPaths, config: HouDocsConfig) -> HybridSearchBackend:
    if not paths.search_database.is_file():
        raise HouDocsError("docs_index_missing", "Run houdocs init first.")
    return HybridSearchBackend(
        database=paths.search_database,
        embeddings=Model2VecEmbeddingProvider(),
        rrf_k=config.search_hybrid.rrf_k,
        candidate_multiplier=config.search_hybrid.candidate_multiplier,
        candidate_min=config.search_hybrid.candidate_min,
    )


@app.command("init")
def init_command(
    houdini_version: Annotated[
        str | None,
        typer.Option("--houdini-version", help="Houdini version to initialize."),
    ] = None,
    progress: Annotated[
        bool,
        typer.Option(
            "--progress", help="Show interactive initialization progress on a TTY."
        ),
    ] = False,
) -> None:
    progress_view = InitProgress(progress)

    def action() -> None:
        try:
            config = load_config()
            version = resolve_requested_version(houdini_version, config=config)
            result = InitService().run(version, config=config, progress=progress_view)
        finally:
            progress_view.finish()
        _emit(_init_summary(result))

    _invoke(action)


@app.command("search")
def search_command(
    query: Annotated[str, typer.Argument(metavar="QUERY")],
) -> None:
    def action() -> None:
        config = load_config()
        paths = _offline_paths(config)
        repository = DocumentRepository(paths.database)
        service = DocumentSearchService(
            repository=repository,
            backend=_search_backend(paths, config),
        )
        _emit(service.search(query))

    _invoke(action)


@app.command("read")
def read_command(
    page: Annotated[str, typer.Argument(metavar="PAGE")],
    section: Annotated[str | None, typer.Argument(metavar="SECTION")] = None,
) -> None:
    def action() -> None:
        config = load_config()
        paths = _offline_paths(config)
        _emit(DocumentReader(DocumentRepository(paths.database)).read(page, section))

    _invoke(action)


@app.command("node")
def node_command(
    node_type: Annotated[str, typer.Argument(metavar="NODE_TYPE")],
) -> None:
    def action() -> None:
        config = load_config()
        paths = _offline_paths(config)
        documents = DocumentRepository(paths.database)
        _emit(
            NodeReader(
                documents=documents,
                repository=NodeRepository(paths.database),
            ).read(node_type)
        )

    _invoke(action)


@app.command("python")
def python_command(
    symbol: Annotated[str, typer.Argument(metavar="SYMBOL")],
) -> None:
    def action() -> None:
        config = load_config()
        paths = _offline_paths(config)
        documents = DocumentRepository(paths.database)
        _emit(
            PythonDocumentReader(
                documents=documents,
                repository=PythonRepository(paths.database),
            ).read(symbol)
        )

    _invoke(action)


@app.command("vex")
def vex_command(
    function: Annotated[str, typer.Argument(metavar="FUNCTION")],
) -> None:
    def action() -> None:
        config = load_config()
        paths = _offline_paths(config)
        documents = DocumentRepository(paths.database)
        _emit(
            VexDocumentReader(
                documents=documents,
                repository=VexRepository(paths.database),
            ).read(function)
        )

    _invoke(action)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
