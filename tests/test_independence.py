from __future__ import annotations

import ast
from pathlib import Path


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_direct_hou_import_is_confined_to_hython_worker() -> None:
    root = Path(__file__).parents[1]
    paths = list((root / "src" / "houdocs").rglob("*.py"))
    paths.append(root / "tools" / "node_document_assist.py")

    violations: list[tuple[str, str]] = []
    allowed_hou = {"src/houdocs/hip/worker.py"}
    for path in paths:
        relative = str(path.relative_to(root)).replace("\\", "/")
        for name in _imports(path):
            if name.startswith("houbridge"):
                violations.append((relative, name))
            elif name == "hou" and relative not in allowed_hou:
                violations.append((relative, name))

    assert violations == []


def test_ai_assist_remains_outside_public_houdocs_cli() -> None:
    root = Path(__file__).parents[1]
    cli = (root / "src" / "houdocs" / "cli.py").read_text(encoding="utf-8")
    assert "node_document_assist" not in cli
    assert (root / "tools" / "node_document_assist.py").is_file()
    assert (root / "tools" / "node-document-assist-ai-prompt.md").is_file()
