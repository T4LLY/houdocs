from __future__ import annotations

from pathlib import Path

import pytest

from houdocs.config import (
    ensure_config_file,
    load_config,
    local_config_path,
    resolve_requested_version,
)
from houdocs.errors import HouDocsError


def test_default_config_is_created_without_selecting_a_version(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"

    ensure_config_file(config_path)
    config = load_config(config_path, cwd=tmp_path)

    assert config.houdini.version is None
    assert config_path.read_text(encoding="utf-8") == '[houdini]\nversion = ""\n'


def test_current_directory_version_overrides_global_version(tmp_path: Path) -> None:
    config_path = tmp_path / "global.toml"
    config_path.write_text('[houdini]\nversion = "21.0.547"\n', encoding="utf-8")
    cwd = tmp_path / "project"
    cwd.mkdir()
    (cwd / ".houdocs.toml").write_text(
        '[houdini]\nversion = "22.0.429"\n',
        encoding="utf-8",
    )

    config = load_config(config_path, cwd=cwd)

    assert config.houdini.version == "22.0.429"


def test_cli_version_overrides_effective_config(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text('[houdini]\nversion = "21.0.547"\n', encoding="utf-8")
    config = load_config(config_path, cwd=tmp_path)

    assert resolve_requested_version("22.0.429", config=config) == "22.0.429"


def test_local_config_is_not_created_implicitly(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"

    load_config(config_path, cwd=tmp_path)

    assert not local_config_path(tmp_path).exists()


def test_invalid_version_in_config_is_invalid_config(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text('[houdini]\nversion = "../22.0.429"\n', encoding="utf-8")

    with pytest.raises(HouDocsError) as caught:
        load_config(config_path, cwd=tmp_path)

    assert caught.value.error.code == "invalid_config"
