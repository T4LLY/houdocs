from __future__ import annotations

import json
import mmap
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator

from houdocs.errors import HouDocsError
from houdocs.search.tokens import count_openai_tokens


@dataclass(frozen=True)
class HipSearchHit:
    node: str
    file: str
    pointer: str
    snippet: str
    occurrences: int
    tokens: int

    def to_dict(self) -> dict[str, object]:
        return {
            "node": self.node,
            "file": self.file,
            "pointer": self.pointer,
            "snippet": self.snippet,
            "occurrences": self.occurrences,
            "tokens": self.tokens,
        }


class HipSearchService:
    def __init__(
        self,
        *,
        token_counter: Callable[[str], int] = count_openai_tokens,
    ) -> None:
        self.token_counter = token_counter

    def search(
        self,
        query: str,
        *,
        root: Path,
        output: Path,
    ) -> dict[str, object]:
        if not query:
            raise HouDocsError(
                "hip_search_query_empty",
                "HIP search query must not be empty.",
            )

        search_root = root.expanduser().resolve()
        if not search_root.is_dir():
            raise HouDocsError(
                "hip_search_root_missing",
                f"HIP search root does not exist: {root}",
            )

        output_path = output.expanduser().resolve()
        if _is_within(output_path, search_root):
            raise HouDocsError(
                "hip_search_output_inside_root",
                "HIP search output must be outside the search root.",
            )

        query_bytes = query.encode("utf-8")
        hits: list[HipSearchHit] = []
        for path in sorted(search_root.rglob("*.json")):
            if not path.is_file() or not _contains_bytes(path, query_bytes):
                continue
            payload = _read_json(path)
            hits.extend(
                _hits_for_shard(
                    payload,
                    query=query,
                    relative_file=path.relative_to(search_root).as_posix(),
                    token_counter=self.token_counter,
                )
            )

        result = {"hits": [hit.to_dict() for hit in hits]}
        _write_result(output_path, result)
        return {"hits": len(hits), "output": str(output_path)}


def _contains_bytes(path: Path, query: bytes) -> bool:
    try:
        if path.stat().st_size == 0:
            return False
        with path.open("rb") as handle:
            with mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as mapped:
                return mapped.find(query) >= 0
    except OSError as exc:
        raise HouDocsError(
            "hip_search_read_failed",
            f"Unable to read HIP search file: {path}",
            detail=str(exc),
        ) from exc


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise HouDocsError(
            "hip_search_invalid_json",
            f"HIP search file is invalid JSON: {path}",
            detail=str(exc),
        ) from exc
    if not isinstance(value, dict):
        raise HouDocsError(
            "hip_search_invalid_json",
            f"HIP search file root must be an object: {path}",
        )
    return value


def _hits_for_shard(
    payload: dict[str, Any],
    *,
    query: str,
    relative_file: str,
    token_counter: Callable[[str], int],
) -> list[HipSearchHit]:
    nodes = payload.get("nodes")
    if not isinstance(nodes, dict):
        raise HouDocsError(
            "hip_search_invalid_shard",
            f"HIP search JSON is missing a nodes object: {relative_file}",
        )

    hits: list[HipSearchHit] = []
    for node_name, raw_node in nodes.items():
        if not isinstance(node_name, str) or not isinstance(raw_node, dict):
            continue
        node_path = raw_node.get("path")
        if not isinstance(node_path, str) or not node_path:
            continue
        base_pointer = "/nodes/" + _pointer_token(node_name)
        for pointer, text in _scalar_fields(raw_node, base_pointer):
            occurrences = text.count(query)
            if occurrences == 0:
                continue
            hits.append(
                HipSearchHit(
                    node=node_path,
                    file=relative_file,
                    pointer=pointer,
                    snippet=query,
                    occurrences=occurrences,
                    tokens=token_counter(text),
                )
            )
    return hits


def _scalar_fields(value: Any, pointer: str) -> Iterator[tuple[str, str]]:
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _scalar_fields(
                item,
                pointer + "/" + _pointer_token(str(key)),
            )
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            yield from _scalar_fields(item, pointer + f"/{index}")
        return
    if isinstance(value, str):
        yield pointer, value
        return
    if value is None:
        yield pointer, "null"
        return
    if isinstance(value, bool):
        yield pointer, "true" if value else "false"
        return
    if isinstance(value, (int, float)):
        yield pointer, json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _pointer_token(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _write_result(path: Path, result: dict[str, object]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(result, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
    except OSError as exc:
        raise HouDocsError(
            "hip_search_output_failed",
            f"Unable to write HIP search output: {path}",
            detail=str(exc),
        ) from exc
