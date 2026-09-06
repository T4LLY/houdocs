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
    assert "--host" not in result.stdout
    assert "--port" not in result.stdout
    assert "--executable" not in result.stdout


def test_phase_one_commands_fail_with_machine_readable_error() -> None:
    result = runner.invoke(app, ["search", "packed primitive"])

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["error"] is True
    assert payload["code"] == "feature_not_implemented"
