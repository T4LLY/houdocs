from __future__ import annotations

import json
from typing import Annotated, Any, Callable

import typer

from houdocs.config import HouDocsConfig, load_config, resolve_requested_version
from houdocs.docs.read import DocumentReader
from houdocs.docs.repository import DocumentRepository
from houdocs.errors import HouDocsError
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
    typer.echo(json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
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
) -> None:
    def action() -> None:
        config = load_config()
        version = resolve_requested_version(houdini_version, config=config)
        _emit(InitService().run(version, config=config))

    _invoke(action)


@app.command("search")
def search_command(query: str) -> None:
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
    page: str,
    section: Annotated[str | None, typer.Argument()] = None,
) -> None:
    def action() -> None:
        config = load_config()
        paths = _offline_paths(config)
        _emit(DocumentReader(DocumentRepository(paths.database)).read(page, section))

    _invoke(action)


@app.command("node")
def node_command(node_type: str) -> None:
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
def python_command(symbol: str) -> None:
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
def vex_command(function: str) -> None:
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
