from __future__ import annotations

import json

from typer.testing import CliRunner

from houdocs.cli import app


runner = CliRunner()


def test_cli_exposes_only_the_planned_top_level_commands() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    for command in ("init", "search", "read", "node", "python", "vex"):
        assert command in result.stdout


def test_init_exposes_version_but_not_connection_target_options() -> None:
    result = runner.invoke(app, ["init", "--help"])

    assert result.exit_code == 0
    assert "--houdini-version" in result.stdout
    assert "--progress" in result.stdout
    assert "--host" not in result.stdout
    assert "--port" not in result.stdout
    assert "--executable" not in result.stdout


def test_offline_command_without_index_fails_with_machine_readable_error() -> None:
    result = runner.invoke(app, ["search", "packed primitive"])

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["error"] is True
    assert payload["code"] == "docs_index_missing"


def test_search_and_reader_commands_do_not_expose_extra_options() -> None:
    search = runner.invoke(app, ["search", "--help"])
    read = runner.invoke(app, ["read", "--help"])
    node = runner.invoke(app, ["node", "--help"])
    python = runner.invoke(app, ["python", "--help"])
    vex = runner.invoke(app, ["vex", "--help"])

    assert search.exit_code == read.exit_code == node.exit_code == python.exit_code == vex.exit_code == 0
    assert "QUERY" in search.stdout
    assert "PAGE" in read.stdout and "[SECTION]" in read.stdout
    for output in (search.stdout, read.stdout, node.stdout, python.stdout, vex.stdout):
        assert "--houdini-version" not in output
        assert "--top-k" not in output
        assert "--rebuild" not in output
