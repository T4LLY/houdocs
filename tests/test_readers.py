from __future__ import annotations

from pathlib import Path

from houdocs.docs.bookish import BookishDocumentParser
from houdocs.docs.index import DocumentIndexer
from houdocs.docs.read import DocumentReader
from houdocs.docs.repository import DocumentRepository
from houdocs.node.index import NodeIndexer
from houdocs.node.read import NodeReader
from houdocs.node.repository import NodeRepository
from houdocs.python_docs.index import PythonIndexer
from houdocs.python_docs.read import PythonDocumentReader
from houdocs.python_docs.repository import PythonRepository
from houdocs.vex_docs.index import VexIndexer
from houdocs.vex_docs.read import VexDocumentReader
from houdocs.vex_docs.repository import VexRepository


def _base(source: Path, state: Path) -> DocumentRepository:
    repository = DocumentRepository(state / "docs.db")
    DocumentIndexer(
        repository=repository,
        parser=BookishDocumentParser(),
        cache_directory=state / "docs",
    ).index_all(source, houdini_version="22.0.429")
    return repository


def test_read_returns_page_or_named_section_only(tmp_path: Path) -> None:
    source = tmp_path / "help"
    source.mkdir()
    (source / "page.txt").write_text(
        "= Page =\n\nIntro.\n\n== Details == (details)\n\nMore.\n",
        encoding="utf-8",
    )
    docs = _base(source, tmp_path / "state")
    reader = DocumentReader(docs)

    page = reader.read("Page")
    section = reader.read("Page", "details")

    assert page["section"] is None
    assert "Intro." in page["text"] and "More." in page["text"]
    assert section["section"]["anchor"] == "details"
    assert "More." in section["text"]


def test_specialized_readers_resolve_direct_indexes_and_reuse_sections(tmp_path: Path) -> None:
    source = tmp_path / "help"
    (source / "hom" / "hou").mkdir(parents=True)
    (source / "vex" / "functions").mkdir(parents=True)
    (source / "nodes" / "sop").mkdir(parents=True)
    (source / "hom" / "hou" / "Node.txt").write_text(
        "#type: homclass\n= hou.Node =\n\nsetInput(input_index, node):\n    Connect input.\n",
        encoding="utf-8",
    )
    (source / "vex" / "functions" / "xyzdist.txt").write_text(
        "#type: vex\n#context: sop\n#group: geometry\n= xyzdist =\n\nfloat xyzdist(int geo, vector p):\n    Distance.\n",
        encoding="utf-8",
    )
    (source / "nodes" / "sop" / "example.txt").write_text(
        "#type: node\n#context: sop\n#internal: example\n= Example =\n\n@parameters\nStrength:\n    #id: strength\n    Amount.\n",
        encoding="utf-8",
    )
    state = tmp_path / "state"
    docs = _base(source, state)
    PythonIndexer(
        documents=docs,
        repository=PythonRepository(state / "docs.db"),
        docs_directory=state / "docs",
    ).index_all()
    VexIndexer(
        documents=docs,
        repository=VexRepository(state / "docs.db"),
        docs_directory=state / "docs",
    ).index_all()
    NodeIndexer(
        documents=docs,
        repository=NodeRepository(state / "docs.db"),
        docs_directory=state / "docs",
        report_directory=state / "reports",
    ).index_all(
        (
            {
                "category": "Sop",
                "name": "example",
                "canonical_name": "Sop/example",
                "parameters": [
                    {
                        "parameter_ordinal": 0,
                        "id": "strength",
                        "label": "Strength",
                        "folder_path": [],
                        "type": "Float",
                        "is_multiparm": False,
                    }
                ],
            },
        ),
        houdini_version="22.0.429",
    )

    py = PythonDocumentReader(
        documents=docs, repository=PythonRepository(state / "docs.db")
    ).read("hou.Node.setInput")
    vex = VexDocumentReader(
        documents=docs, repository=VexRepository(state / "docs.db")
    ).read("xyzdist")
    node = NodeReader(
        documents=docs, repository=NodeRepository(state / "docs.db")
    ).read("Sop/example")

    assert py["kind"] == "method"
    assert py["signatures"] == ["setInput(input_index, node)"]
    assert "Connect input." in py["text"]
    assert vex["contexts"] == ["sop"]
    assert vex["group"] == "geometry"
    assert "Distance." in vex["text"]
    assert node["parameters"][0]["ids"] == ["strength"]
    assert node["parameters"][0]["runtime_parameters"][0]["resolution_source"] == "bookish-id"
