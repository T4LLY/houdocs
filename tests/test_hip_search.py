from __future__ import annotations

import json
from pathlib import Path

import pytest

from houdocs.errors import HouDocsError
from houdocs.hip.search import HipSearchService


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


def test_hip_search_mmaps_candidates_and_aggregates_same_field(tmp_path: Path) -> None:
    root = tmp_path / "dump" / "search"
    text = "setpointattrib(0); before setpointattrib(1);"
    _write_json(
        root / "obj" / "geo1.json",
        {
            "network": "/obj/geo1",
            "nodes": {
                "wrangle1": {
                    "path": "/obj/geo1/wrangle1",
                    "type": "attribwrangle",
                    "parms": {"snippet": text},
                }
            },
        },
    )
    # This invalid file must never be parsed because the byte prefilter rejects it.
    (root / "unrelated.json").write_text("not-json", encoding="utf-8")
    output = tmp_path / "hits.json"

    summary = HipSearchService(token_counter=len).search(
        "setpointattrib",
        root=root,
        output=output,
    )

    assert summary == {"hits": 1, "output": str(output.resolve())}
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload == {
        "hits": [
            {
                "node": "/obj/geo1/wrangle1",
                "file": "obj/geo1.json",
                "pointer": "/nodes/wrangle1/parms/snippet",
                "snippet": "setpointattrib",
                "occurrences": 2,
                "tokens": len(text),
            }
        ]
    }


def test_hip_search_uses_json_pointer_escaping(tmp_path: Path) -> None:
    root = tmp_path / "search"
    _write_json(
        root / "obj.json",
        {
            "network": "/obj",
            "nodes": {
                "node": {
                    "path": "/obj/node",
                    "parms": {"a/b~c": "needle"},
                }
            },
        },
    )
    output = tmp_path / "hits.json"

    HipSearchService(token_counter=len).search("needle", root=root, output=output)

    hit = json.loads(output.read_text(encoding="utf-8"))["hits"][0]
    assert hit["pointer"] == "/nodes/node/parms/a~1b~0c"


def test_hip_search_rejects_output_inside_search_root(tmp_path: Path) -> None:
    root = tmp_path / "search"
    root.mkdir()

    with pytest.raises(HouDocsError) as caught:
        HipSearchService(token_counter=len).search(
            "needle",
            root=root,
            output=root / "hits.json",
        )

    assert caught.value.error.code == "hip_search_output_inside_root"
    assert not (root / "hits.json").exists()


def test_hip_search_rejects_empty_query(tmp_path: Path) -> None:
    root = tmp_path / "search"
    root.mkdir()

    with pytest.raises(HouDocsError) as caught:
        HipSearchService(token_counter=len).search("", root=root, output=tmp_path / "hits.json")

    assert caught.value.error.code == "hip_search_query_empty"
