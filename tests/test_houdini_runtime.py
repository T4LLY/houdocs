from __future__ import annotations

from pathlib import Path

import pytest

from houdocs.errors import HouDocsError
from houdocs.houdini.runtime import (
    HoudiniInstallation,
    discover_houdini_installations,
    select_houdini_installation,
)


def _installation(root: Path, version: tuple[int, int, int]) -> HoudiniInstallation:
    bin_dir = root / "bin"
    return HoudiniInstallation(
        root=root,
        bin_dir=bin_dir,
        hython=bin_dir / "hython.exe",
        hcommand=bin_dir / "hcommand.exe",
        houdini=bin_dir / "houdini.exe",
        version=version,
    )


def test_selects_latest_installation_when_version_is_unspecified(tmp_path: Path) -> None:
    installs = (
        _installation(tmp_path / "Houdini22.0.429", (22, 0, 429)),
        _installation(tmp_path / "Houdini21.0.777", (21, 0, 777)),
    )

    assert select_houdini_installation(None, installations=installs).version == (22, 0, 429)


def test_selects_latest_build_for_major_minor_request(tmp_path: Path) -> None:
    installs = (
        _installation(tmp_path / "Houdini22.0.429", (22, 0, 429)),
        _installation(tmp_path / "Houdini22.0.400", (22, 0, 400)),
    )

    selected = select_houdini_installation("22.0", installations=installs)

    assert selected.version == (22, 0, 429)


def test_requires_exact_build_for_three_part_request(tmp_path: Path) -> None:
    installs = (
        _installation(tmp_path / "Houdini22.0.429", (22, 0, 429)),
        _installation(tmp_path / "Houdini22.0.400", (22, 0, 400)),
    )

    selected = select_houdini_installation("22.0.400", installations=installs)

    assert selected.version == (22, 0, 400)


def test_missing_requested_version_reports_available_versions(tmp_path: Path) -> None:
    installs = (_installation(tmp_path / "Houdini22.0.429", (22, 0, 429)),)

    with pytest.raises(HouDocsError) as caught:
        select_houdini_installation("21.0.777", installations=installs)

    assert caught.value.error.code == "houdini_version_not_found"
    assert "22.0.429" in (caught.value.error.detail or "")


def test_discovery_finds_windows_sidefx_installations(tmp_path: Path) -> None:
    sidefx = tmp_path / "Side Effects Software"
    root = sidefx / "Houdini 22.0.429"
    bin_dir = root / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "hython.exe").write_bytes(b"")
    (bin_dir / "hcommand.exe").write_bytes(b"")
    (bin_dir / "houdini.exe").write_bytes(b"")

    installs = discover_houdini_installations(
        environ={"ProgramFiles": str(tmp_path), "PATH": ""},
        platform="win32",
    )

    assert len(installs) == 1
    assert installs[0].version == (22, 0, 429)
    assert installs[0].hython == (bin_dir / "hython.exe").resolve()


def test_discovery_reads_version_header_for_custom_installation_path(tmp_path: Path) -> None:
    root = tmp_path / "houdini-current"
    bin_dir = root / "bin"
    header = root / "toolkit" / "include" / "SYS" / "SYS_Version.h"
    bin_dir.mkdir(parents=True)
    header.parent.mkdir(parents=True)
    (bin_dir / "hython.exe").write_bytes(b"")
    (bin_dir / "hcommand.exe").write_bytes(b"")
    (bin_dir / "houdini.exe").write_bytes(b"")
    header.write_text('#define SYS_VERSION_FULL "22.0.429"\n', encoding="utf-8")

    installs = discover_houdini_installations(
        environ={"HFS": str(root), "PATH": ""},
        platform="win32",
    )

    assert len(installs) == 1
    assert installs[0].root == root.resolve()
    assert installs[0].version == (22, 0, 429)


def test_discovery_ignores_installation_when_version_cannot_be_identified(tmp_path: Path) -> None:
    root = tmp_path / "houdini-current"
    bin_dir = root / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "hython.exe").write_bytes(b"")
    (bin_dir / "hcommand.exe").write_bytes(b"")
    (bin_dir / "houdini.exe").write_bytes(b"")

    installs = discover_houdini_installations(
        environ={"HFS": str(root), "PATH": ""},
        platform="win32",
    )

    assert installs == ()
