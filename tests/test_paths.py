from __future__ import annotations

from pathlib import Path

import pytest

from houdocs.errors import HouDocsError
from houdocs.paths import VersionPaths


def test_version_paths_are_fully_isolated_by_version(tmp_path: Path) -> None:
    paths = VersionPaths.for_version("22.0.429", data_root=tmp_path)

    assert paths.root == tmp_path.resolve() / "versions" / "22.0.429"
    assert paths.database == paths.root / "docs.db"
    assert paths.search_database == paths.root / "search.db"
    assert paths.docs == paths.root / "docs"
    assert paths.reports == paths.root / "reports"


def test_version_paths_create_only_the_version_tree(tmp_path: Path) -> None:
    paths = VersionPaths.for_version("22.0.429", data_root=tmp_path)

    paths.ensure()

    assert paths.root.is_dir()
    assert paths.docs.is_dir()
    assert paths.reports.is_dir()
    assert not paths.database.exists()
    assert not paths.search_database.exists()


def test_version_path_rejects_path_like_values(tmp_path: Path) -> None:
    with pytest.raises(HouDocsError) as caught:
        VersionPaths.for_version("../22.0.429", data_root=tmp_path)

    assert caught.value.error.code == "invalid_houdini_version"
