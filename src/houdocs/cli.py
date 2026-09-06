from __future__ import annotations

import json
from typing import Annotated, Any, Callable

import typer

from houdocs.config import load_config, resolve_requested_version
from houdocs.errors import HouDocsError


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


def _not_implemented(command: str, *, detail: str | None = None) -> None:
    raise HouDocsError(
        "feature_not_implemented",
        f"houdocs {command} is not implemented in phase 1.",
        detail=detail,
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
        detail = f"requested_version={version}" if version else "requested_version=auto"
        _not_implemented("init", detail=detail)

    _invoke(action)


@app.command("search")
def search_command(query: str) -> None:
    _invoke(lambda: _not_implemented("search", detail=f"query={query}"))


@app.command("read")
def read_command(page: str, section: str | None = None) -> None:
    detail = f"page={page}" + (f" section={section}" if section else "")
    _invoke(lambda: _not_implemented("read", detail=detail))


@app.command("node")
def node_command(node_type: str) -> None:
    _invoke(lambda: _not_implemented("node", detail=f"node_type={node_type}"))


@app.command("python")
def python_command(symbol: str) -> None:
    _invoke(lambda: _not_implemented("python", detail=f"symbol={symbol}"))


@app.command("vex")
def vex_command(function: str) -> None:
    _invoke(lambda: _not_implemented("vex", detail=f"function={function}"))


def main() -> None:
    app()


if __name__ == "__main__":
    main()
