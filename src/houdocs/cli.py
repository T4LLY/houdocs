from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Annotated, Any, Callable

import typer

from houdocs.config import HouDocsConfig, load_config, resolve_requested_version
from houdocs.docs.read import DocumentReader
from houdocs.docs.repository import DocumentRepository
from houdocs.errors import HouDocsError
from houdocs.hip.dump import HIP_DUMP_TIMEOUT_SECONDS, HipDumpService
from houdocs.hip.search import HipSearchService
from houdocs.init.progress import InitProgress
from houdocs.init.service import InitService
from houdocs.node.read import NodeReader
from houdocs.node.repository import NodeRepository
from houdocs.paths import VersionPaths, resolve_initialized_version
from houdocs.python_docs.read import PythonDocumentReader
from houdocs.python_docs.repository import PythonRepository
from houdocs.search.domain import SearchDomain
from houdocs.search.embedding import Model2VecEmbeddingProvider
from houdocs.search.hybrid import HybridSearchBackend
from houdocs.search.service import DocumentSearchService
from houdocs.search.tokens import count_openai_tokens
from houdocs.vex_docs.read import VexDocumentReader
from houdocs.vex_docs.repository import VexRepository


app = typer.Typer(
    no_args_is_help=True,
    rich_markup_mode=None,
    pretty_exceptions_enable=False,
    context_settings={"color": False},
    help="Indexed Houdini documentation CLI.",
)


hip_app = typer.Typer(
    no_args_is_help=True,
    rich_markup_mode=None,
    pretty_exceptions_enable=False,
    context_settings={"color": False},
    help="Dump and search Houdini HIP files.",
)
app.add_typer(hip_app, name="hip")


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
    if error.error.choices:
        payload["choices"] = list(error.error.choices)
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


@app.command("init", help="Initialize Houdini documentation data.")
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
    import_assist: Annotated[
        bool,
        typer.Option(
            "--import-assist",
            help="Apply saved node assist overrides to the existing documentation database.",
        ),
    ] = False,
) -> None:
    progress_view = InitProgress(progress)

    def action() -> None:
        config = load_config()
        requested_version = resolve_requested_version(houdini_version, config=config)
        service = InitService()

        if import_assist:
            version = resolve_initialized_version(requested_version)
            imported = service.import_assist(version)
            typer.echo(f"Imported {imported} assist overrides.")
            return

        installation = service.runtime.select(requested_version)
        paths = VersionPaths.for_version(
            installation.version_string, data_root=service.data_root
        )
        if paths.database.is_file() or paths.search_database.is_file():
            progress_view.finish()
            if not typer.confirm(
                f"Existing HouDocs database for Houdini {paths.version} will be rebuilt. Continue?",
                default=False,
                err=True,
            ):
                raise typer.Exit()

        try:
            result = service.run(
                requested_version,
                config=config,
                progress=progress_view,
            )
        finally:
            progress_view.finish()
        _emit(_init_summary(result))

    _invoke(action)


@app.command("search", help="Search Houdini documentation.")
def search_command(
    query: Annotated[str, typer.Argument(metavar="QUERY")],
    domain: Annotated[
        SearchDomain | None,
        typer.Option("--domain", help="Restrict search to one documentation domain."),
    ] = None,
) -> None:
    def action() -> None:
        config = load_config()
        paths = _offline_paths(config)
        repository = DocumentRepository(paths.database)
        service = DocumentSearchService(
            repository=repository,
            python_repository=PythonRepository(paths.database),
            vex_repository=VexRepository(paths.database),
            backend=_search_backend(paths, config),
        )
        _emit(service.search(query, domain=domain))

    _invoke(action)


@app.command("read", help="Read a documentation page.")
def read_command(
    page: Annotated[str, typer.Argument(metavar="PAGE")],
    section: Annotated[str | None, typer.Argument(metavar="SECTION")] = None,
    pick: Annotated[
        int | None,
        typer.Option(
            "--pick",
            min=1,
            help="Select a numbered candidate for an ambiguous page title.",
        ),
    ] = None,
) -> None:
    def action() -> None:
        config = load_config()
        paths = _offline_paths(config)
        _emit(
            DocumentReader(DocumentRepository(paths.database)).read(
                page, section, pick=pick
            )
        )

    _invoke(action)


@app.command("sections", help="List page sections.")
def sections_command(
    page: Annotated[str, typer.Argument(metavar="PAGE")],
    pick: Annotated[
        int | None,
        typer.Option(
            "--pick",
            min=1,
            help="Select a numbered candidate for an ambiguous page title.",
        ),
    ] = None,
) -> None:
    def action() -> None:
        config = load_config()
        paths = _offline_paths(config)
        _emit(
            DocumentReader(DocumentRepository(paths.database)).sections(
                page, pick=pick
            )
        )

    _invoke(action)


@app.command("node", help="Read node documentation.")
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
                token_counter=count_openai_tokens,
            ).read(node_type)
        )

    _invoke(action)


@app.command("hom", help="Read HOM documentation.")
def hom_command(
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


@app.command("vex", help="Read VEX documentation.")
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


@hip_app.command("dump")
def hip_dump_command(
    hip_file: Annotated[
        Path,
        typer.Option("--file", help="HIP file to dump."),
    ],
    output: Annotated[
        Path | None,
        typer.Option("--output", help="Output directory. Defaults to an OS temp directory."),
    ] = None,
    houdini_version: Annotated[
        str | None,
        typer.Option("--houdini-version", help="Houdini version to use for the dump."),
    ] = None,
    timeout: Annotated[
        float,
        typer.Option("--timeout", help="Headless HIP dump timeout in seconds."),
    ] = HIP_DUMP_TIMEOUT_SECONDS,
) -> None:
    def action() -> None:
        config = load_config()
        requested_version = resolve_requested_version(houdini_version, config=config)
        result = HipDumpService().dump(
            hip_file,
            requested_version=requested_version,
            output=output,
            timeout_seconds=timeout,
        )
        _emit({"output": str(result.output), "errors": result.errors})

    _invoke(action)


@hip_app.command("search")
def hip_search_command(
    query: Annotated[str, typer.Argument(metavar="QUERY")],
    root: Annotated[
        Path,
        typer.Option("--root", help="Root directory containing searchable HIP JSON shards."),
    ],
    output: Annotated[
        Path,
        typer.Option("--output", help="JSON file to write search hits to."),
    ],
) -> None:
    def action() -> None:
        _emit(HipSearchService().search(query, root=root, output=output))

    _invoke(action)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
