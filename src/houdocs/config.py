from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_config_path, user_data_path

from houdocs.errors import HouDocsError


_VERSION_RE = re.compile(r"^\d+\.\d+(?:\.\d+)?$")

_DEFAULT_CONFIG = """[houdini]
version = ""

[search.embedding]
docs_profile = "minishlab/potion-retrieval-32M"

[search.hybrid]
rrf_k = 60
candidate_multiplier = 8
candidate_min = 32
"""


@dataclass(frozen=True)
class HoudiniConfig:
    version: str | None


@dataclass(frozen=True)
class SearchEmbeddingConfig:
    docs_profile: str


@dataclass(frozen=True)
class SearchHybridConfig:
    rrf_k: int
    candidate_multiplier: int
    candidate_min: int


@dataclass(frozen=True)
class HouDocsConfig:
    houdini: HoudiniConfig
    search_embedding: SearchEmbeddingConfig
    search_hybrid: SearchHybridConfig


def default_config_path() -> Path:
    return user_config_path("houdocs", ensure_exists=False) / "config.toml"


def default_data_root() -> Path:
    return user_data_path("houdocs", ensure_exists=False)


def local_config_path(cwd: Path | None = None) -> Path:
    return (cwd or Path.cwd()).resolve() / ".houdocs.toml"


def ensure_config_file(path: Path | None = None) -> Path:
    config_path = path or default_config_path()
    if config_path.exists():
        if not config_path.is_file():
            raise HouDocsError(
                "invalid_config",
                f"Config path is not a file: {config_path}",
            )
        return config_path

    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(_DEFAULT_CONFIG, encoding="utf-8")
    except OSError as exc:
        raise HouDocsError(
            "invalid_config",
            f"Unable to create config.toml: {config_path}",
        ) from exc
    return config_path


def load_config(
    path: Path | None = None,
    *,
    cwd: Path | None = None,
) -> HouDocsConfig:
    config_path = ensure_config_file(path)
    raw = _deep_merge(tomllib.loads(_DEFAULT_CONFIG), _read_toml(config_path))

    local_path = local_config_path(cwd)
    if local_path.exists():
        if not local_path.is_file():
            raise HouDocsError(
                "invalid_config",
                f"Config path is not a file: {local_path}",
            )
        raw = _deep_merge(raw, _read_toml(local_path))

    houdini = _table(raw, "houdini")
    search = _table(raw, "search")
    embedding = _table(search, "embedding")
    hybrid = _table(search, "hybrid")
    return HouDocsConfig(
        houdini=HoudiniConfig(
            version=_optional_version(houdini, "version"),
        ),
        search_embedding=SearchEmbeddingConfig(
            docs_profile=_string(embedding, "docs_profile"),
        ),
        search_hybrid=SearchHybridConfig(
            rrf_k=_positive_int(hybrid, "rrf_k", allow_zero=True),
            candidate_multiplier=_positive_int(hybrid, "candidate_multiplier"),
            candidate_min=_positive_int(hybrid, "candidate_min"),
        ),
    )


def resolve_requested_version(
    explicit: str | None,
    *,
    config: HouDocsConfig,
) -> str | None:
    if explicit is not None and explicit.strip():
        return validate_version(explicit)
    return config.houdini.version


def validate_version(value: str) -> str:
    normalized = value.strip()
    if not _VERSION_RE.fullmatch(normalized):
        raise HouDocsError(
            "invalid_houdini_version",
            f"Invalid Houdini version: {value}",
            detail="Expected <major>.<minor> or <major>.<minor>.<build>.",
        )
    return normalized


def _read_toml(path: Path) -> dict[str, object]:
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise HouDocsError(
            "invalid_config",
            f"Unable to read TOML config: {path}",
        ) from exc


def _deep_merge(
    base: dict[str, object],
    override: dict[str, object],
) -> dict[str, object]:
    merged = dict(base)
    for key, value in override.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged[key] = _deep_merge(current, value)
        else:
            merged[key] = value
    return merged


def _table(mapping: dict[str, object], key: str) -> dict[str, object]:
    value = mapping.get(key)
    if not isinstance(value, dict):
        raise HouDocsError(
            "invalid_config",
            f"config.toml [{key}] must be a table.",
        )
    return value


def _optional_version(mapping: dict[str, object], key: str) -> str | None:
    value = mapping.get(key)
    if not isinstance(value, str):
        raise HouDocsError(
            "invalid_config",
            f"config.toml {key} must be a string.",
        )
    if not value.strip():
        return None
    try:
        return validate_version(value)
    except HouDocsError as exc:
        raise HouDocsError(
            "invalid_config",
            f"config.toml {key} contains an invalid Houdini version: {value}",
            detail=exc.error.detail,
        ) from exc


def _string(mapping: dict[str, object], key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise HouDocsError("invalid_config", f"config.toml {key} must be a non-empty string.")
    return value.strip()


def _positive_int(
    mapping: dict[str, object],
    key: str,
    *,
    allow_zero: bool = False,
) -> int:
    value = mapping.get(key)
    minimum = 0 if allow_zero else 1
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        relation = ">= 0" if allow_zero else "> 0"
        raise HouDocsError("invalid_config", f"config.toml {key} must be an integer {relation}.")
    return value
