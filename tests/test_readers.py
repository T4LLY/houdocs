from __future__ import annotations

from pathlib import Path

import pytest

from houdocs.docs.bookish import BookishDocumentParser
from houdocs.docs.index import DocumentIndexer
from houdocs.docs.models import Document
from houdocs.docs.read import DocumentReader
from houdocs.docs.repository import DocumentRepository
from houdocs.errors import HouDocsError
from houdocs.node.index import NodeIndexer
from houdocs.node.models import (
    NodeParameter,
    NodeParameterDoc,
    NodeParameterLink,
    NodePort,
    NodeRelated,
    NodeTypeDocument,
)
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

    assert set(page) == {"text"}
    assert "Intro." in page["text"] and "More." in page["text"]
    assert set(section) == {"text"}
    assert "More." in section["text"]


def test_read_ambiguous_title_lists_numbered_choices_and_pick_selects_one(
    tmp_path: Path,
) -> None:
    source = tmp_path / "help"
    (source / "nodes" / "lop").mkdir(parents=True)
    (source / "nodes" / "sop").mkdir(parents=True)
    (source / "nodes" / "lop" / "copytopoints.txt").write_text(
        "= Copy to Points =\n\nLOP article.\n", encoding="utf-8"
    )
    (source / "nodes" / "sop" / "copytopoints.txt").write_text(
        "= Copy to Points =\n\nSOP article.\n", encoding="utf-8"
    )
    reader = DocumentReader(_base(source, tmp_path / "state"))

    with pytest.raises(HouDocsError) as caught:
        reader.read("Copy to Points")
    assert caught.value.error.code == "document_ambiguous"
    assert caught.value.error.detail is None
    assert caught.value.error.choices == (
        "LOP / Copy to Points",
        "SOP / Copy to Points",
    )

    assert reader.read("Copy to Points", pick=1) == {
        "text": "Copy to Points\nLOP article."
    }
    assert reader.read("Copy to Points", pick=2) == {
        "text": "Copy to Points\nSOP article."
    }


def test_read_section_ambiguity_uses_native_human_readable_choices(
    tmp_path: Path,
) -> None:
    source = tmp_path / "help"
    source.mkdir()
    (source / "page.txt").write_text(
        "= Page =\n\n== First ==\n\n=== Details ===\n\nOne.\n\n"
        "== Second ==\n\n=== Details ===\n\nTwo.\n",
        encoding="utf-8",
    )
    reader = DocumentReader(_base(source, tmp_path / "state"))

    with pytest.raises(HouDocsError) as caught:
        reader.read("Page", "Details")

    assert caught.value.error.code == "document_section_ambiguous"
    assert caught.value.error.detail is None
    assert caught.value.error.choices == ("First/Details", "Second/Details")


def test_read_pick_rejects_candidate_number_outside_available_range(
    tmp_path: Path,
) -> None:
    source = tmp_path / "help"
    source.mkdir()
    (source / "page.txt").write_text("= Page =\n\nBody.\n", encoding="utf-8")
    reader = DocumentReader(_base(source, tmp_path / "state"))

    with pytest.raises(HouDocsError) as caught:
        reader.read("Page", pick=2)
    assert caught.value.error.code == "document_pick_out_of_range"


def test_specialized_readers_resolve_direct_indexes_and_reuse_sections(
    tmp_path: Path,
) -> None:
    source = tmp_path / "help"
    (source / "hom" / "hou").mkdir(parents=True)
    (source / "vex" / "functions").mkdir(parents=True)
    (source / "nodes" / "sop").mkdir(parents=True)
    (source / "hom" / "hou" / "Node.txt").write_text(
        "= hou.Node =\n#type: homclass\n\n::`setInput(self, input_index, node)`:\n    Connect input.\n",
        encoding="utf-8",
    )
    (source / "vex" / "functions" / "xyzdist.txt").write_text(
        "= xyzdist =\n\n#type: vex\n#context: sop\n#group: geometry\n\nfloat xyzdist(int geo, vector p):\n    Distance.\n",
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
    assert py["signatures"] == ["setInput(self, input_index, node)"]
    assert "Connect input." in py["text"]
    assert vex["contexts"] == ["sop"]
    assert vex["group"] == "geometry"
    assert "Distance." in vex["text"]
    assert node == {
        "parameters": [
            {
                "id": "strength",
                "label": "Strength",
                "description": "Amount.",
                "type": "Float",
            }
        ]
    }




def test_node_reader_returns_only_compact_operational_metadata(tmp_path: Path) -> None:
    database = tmp_path / "docs.db"
    documents = DocumentRepository(database)
    documents.replace_document(
        Document(
            "node-doc",
            "Example",
            "nodes/sop/example.txt",
            "node-doc",
            "22.0.429",
            "Example body",
        ),
        [],
    )
    repository = NodeRepository(database)
    repository.replace_all(
        [
            (
                NodeTypeDocument(
                    "Sop/example",
                    "node-doc",
                    "sop",
                    None,
                    "example",
                    None,
                    "Sop",
                    "Sop/example",
                    1000,
                    "houdini",
                    None,
                ),
                (
                    NodeParameter(
                        "p0",
                        "Sop/example",
                        0,
                        "group",
                        "Group",
                        ("Code",),
                        "parmTemplateType.String",
                        False,
                        True,
                    ),
                    NodeParameter(
                        "p1",
                        "Sop/example",
                        1,
                        "bindings",
                        "Bindings",
                        ("Bindings",),
                        "parmTemplateType.Folder",
                        True,
                        True,
                    ),
                ),
                (
                    NodeParameterDoc(
                        "d0",
                        "Sop/example",
                        0,
                        "Group",
                        ("Code",),
                        "Select geometry.",
                        (),
                        None,
                    ),
                    NodeParameterDoc(
                        "d1",
                        "Sop/example",
                        1,
                        "Group Bindings",
                        ("Bindings",),
                        "Repeated bindings.",
                        (),
                        None,
                    ),
                    NodeParameterDoc(
                        "d2",
                        "Sop/example",
                        2,
                        "Unknown",
                        (),
                        "Unresolved documentation.",
                        (),
                        "no_houdini_match",
                    ),
                ),
                (
                    NodeParameterLink("d0", "p0", 0, "houdini-label"),
                    NodeParameterLink("d1", "p1", 0, "houdini-label"),
                ),
                (
                    NodePort("Sop/example", "input", 1, "Target", "Target geometry."),
                    NodePort("Sop/example", "input", 0, "Source", "Source geometry."),
                    NodePort("Sop/example", "output", 0, "Output", "Result geometry."),
                ),
                (
                    NodeRelated(
                        "Sop/example",
                        0,
                        "node",
                        "Node:sop/copy",
                        None,
                        "Sop/copy",
                        True,
                        None,
                    ),
                    NodeRelated(
                        "Sop/example",
                        1,
                        "concept",
                        "/model/copying",
                        "Copying",
                        "/model/copying",
                        True,
                        None,
                    ),
                    NodeRelated(
                        "Sop/example",
                        2,
                        "node",
                        "Node:sop/missing",
                        None,
                        None,
                        False,
                        "node_target_unresolved",
                    ),
                ),
            )
        ]
    )

    node = NodeReader(documents=documents, repository=repository).read("sop/example")

    assert node == {
        "inputs": [
            {"label": "Source", "description": "Source geometry."},
            {"label": "Target", "description": "Target geometry."},
        ],
        "outputs": [
            {"label": "Output", "description": "Result geometry."},
        ],
        "parameters": [
            {
                "id": "group",
                "label": "Group",
                "description": "Select geometry.",
                "type": "String",
            },
            {
                "id": "bindings",
                "label": "Group Bindings",
                "description": "Repeated bindings.",
                "type": "Folder",
                "multiparm": True,
            },
        ],
        "related": ["sop/copy", "/model/copying"],
    }


def test_node_repository_resolves_duplicate_canonical_names_by_priority(
    tmp_path: Path,
) -> None:
    database = tmp_path / "docs.db"
    documents = DocumentRepository(database)
    documents.replace_document(
        Document("lower", "Lower", "nodes/sop/foo.txt", "node", "22.0.429", "lower"),
        [],
    )
    documents.replace_document(
        Document(
            "higher", "Higher", "nodes/sop/foo-2.txt", "node", "22.0.429", "higher"
        ),
        [],
    )
    repository = NodeRepository(database)
    repository.replace_all(
        [
            (
                NodeTypeDocument(
                    "a",
                    "lower",
                    "sop",
                    None,
                    "foo",
                    None,
                    "Sop",
                    "Sop/foo",
                    1,
                    "houdini",
                    None,
                ),
                (),
                (),
                (),
                (),
                (),
            ),
            (
                NodeTypeDocument(
                    "z",
                    "higher",
                    "sop",
                    None,
                    "foo",
                    None,
                    "Sop",
                    "Sop/foo",
                    1001,
                    "houdini",
                    None,
                ),
                (),
                (),
                (),
                (),
                (),
            ),
        ]
    )

    resolved = repository.resolve("Sop/foo")

    assert resolved is not None
    assert resolved[0] == "higher"

    bare = repository.resolve("foo")

    assert bare is not None
    assert bare[0] == "higher"
