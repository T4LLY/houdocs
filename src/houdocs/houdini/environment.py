from __future__ import annotations

import ntpath
import os
import posixpath
import sys
from typing import TYPE_CHECKING, Mapping

if TYPE_CHECKING:
    from houdocs.houdini.runtime import HoudiniInstallation


def subprocess_environment_for(
    installation: HoudiniInstallation,
    *,
    environ: Mapping[str, str] | None = None,
    platform: str | None = None,
) -> dict[str, str]:
    env = dict(os.environ if environ is None else environ)
    platform_name = sys.platform if platform is None else platform
    env["HFS"] = str(installation.root)

    selected = str(installation.bin_dir)
    path_separator = ";" if platform_name.startswith("win") else ":"
    current_path = env.get("PATH", "")
    parts = [part for part in current_path.split(path_separator) if part]
    selected_key = _path_key(selected, platform_name)
    remainder = [
        part for part in parts if _path_key(part, platform_name) != selected_key
    ]
    env["PATH"] = path_separator.join([selected, *remainder])
    return env


def _path_key(value: str, platform_name: str) -> str:
    if platform_name.startswith("win"):
        return ntpath.normpath(value).casefold()
    return posixpath.normpath(value)
