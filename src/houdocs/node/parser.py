from __future__ import annotations

import re
from pathlib import Path

from houdocs.node.models import DocumentedField, NodeDocSource, NodeTypeLookup, RelatedLink

_PROPERTY_RE = re.compile(r"^#(?P<name>[A-Za-z0-9_-]+):\s*(?P<value>.*)$")
_HEADING_RE = re.compile(r"^(?P<marks>={1,6})\s*(?P<title>.*?)\s*(?P=marks)(?:\s*\([^)]+\))?\s*$")
_AT_SECTION_RE = re.compile(r"^@(?P<name>[A-Za-z0-9_-]+)(?:\s+.*)?$")
_BOOKISH_LINK_RE = re.compile(r"\[([^\[\]]+)\]")
_WHITESPACE_RE = re.compile(r"\s+")
_FILENAME_VERSION_RE = re.compile(r"-(?P<version>\d+(?:\.\d+)*)$")

_CATEGORY_ALIASES = {
    "apex": "Apex",
    "chop": "Chop",
    "cop": "Cop",
    "cop2": "Cop2",
    "dop": "Dop",
    "lop": "Lop",
    "obj": "Object",
    "out": "Driver",
    "shop": "Shop",
    "sop": "Sop",
    "top": "Top",
    "vex": "Vex",
    "vop": "Vop",
}


def category_for_context(context: str) -> str | None:
    return _CATEGORY_ALIASES.get(context.casefold())


def context_for_category(category: str) -> str | None:
    key = category.casefold()
    for context, mapped in _CATEGORY_ALIASES.items():
        if mapped.casefold() == key:
            return context
    return None


def parse_node_document(source: str, relative_path: str | None = None) -> NodeDocSource:
    lines = source.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    properties: dict[str, str] = {}
    title = ""
    for raw in lines:
        stripped = raw.strip()
        match = _PROPERTY_RE.match(stripped)
        if match:
            properties[match.group("name").casefold()] = match.group("value").strip()
        heading = _HEADING_RE.match(raw.rstrip())
        if heading and len(heading.group("marks")) == 1 and not title:
            title = heading.group("title").strip()

    explicit_version = properties.get("version") or None
    inferred_version = _filename_version(relative_path) if explicit_version is None else None
    return NodeDocSource(
        page_type=properties.get("type") or None,
        context=properties.get("context") or None,
        namespace=properties.get("namespace") or None,
        internal_name=properties.get("internal") or None,
        version=explicit_version or inferred_version,
        version_source="explicit" if explicit_version else "filename" if inferred_version else None,
        title=title,
        inputs=tuple(_parse_fields(_section_lines(lines, "inputs"), allow_id=False)),
        outputs=tuple(_parse_fields(_section_lines(lines, "outputs"), allow_id=False)),
        parameters=tuple(_parse_fields(_section_lines(lines, "parameters"), allow_id=True)),
        related=tuple(_parse_related(_section_lines(lines, "related"))),
    )


def node_type_lookup(node_doc: NodeDocSource) -> NodeTypeLookup:
    context = node_doc.context or ""
    internal_name = node_doc.internal_name or ""
    if node_doc.namespace and not internal_name.casefold().startswith(
        f"{node_doc.namespace}::".casefold()
    ):
        internal_name = f"{node_doc.namespace}::{internal_name}"
    if node_doc.version and not internal_name.casefold().endswith(
        f"::{node_doc.version}".casefold()
    ):
        internal_name = f"{internal_name}::{node_doc.version}"
    return NodeTypeLookup(context, internal_name, node_doc.title or None)


def strict_node_lookup(relative_path: str, node_doc: NodeDocSource) -> NodeTypeLookup | None:
    if node_doc.page_type and node_doc.page_type.casefold() == "include":
        return None
    path = Path(relative_path)
    if path.stem.casefold() == "index":
        return None
    parts = path.parts
    if len(parts) < 3 or parts[0].casefold() != "nodes":
        return None
    context = parts[1]
    if category_for_context(context) is None:
        return None
    if node_doc.context and node_doc.internal_name:
        return node_type_lookup(node_doc)
    internal_name = path.stem
    if not internal_name:
        return None
    return NodeTypeLookup(context, internal_name, node_doc.title or None)


def should_index_node_document(relative_path: str, node_doc: NodeDocSource) -> bool:
    if node_doc.page_type and node_doc.page_type.casefold() == "include":
        return False
    if Path(relative_path).stem.casefold() == "index":
        return False
    if node_doc.page_type and node_doc.page_type.casefold() == "node":
        return True
    return strict_node_lookup(relative_path, node_doc) is not None


def _filename_version(relative_path: str | None) -> str | None:
    if not relative_path:
        return None
    match = _FILENAME_VERSION_RE.search(Path(relative_path).stem)
    return match.group("version") if match else None


def _section_lines(lines: list[str], name: str) -> list[str]:
    output: list[str] = []
    active = False
    for raw in lines:
        match = _AT_SECTION_RE.match(raw.strip())
        if match:
            section_name = match.group("name").casefold()
            if active and section_name != name:
                break
            active = section_name == name
            continue
        if active:
            output.append(raw)
    return output


def _parse_fields(lines: list[str], *, allow_id: bool) -> list[DocumentedField]:
    fields: list[DocumentedField] = []
    current_label: str | None = None
    current_lines: list[str] = []
    current_ids: tuple[str, ...] = ()
    current_group_path: tuple[str, ...] = ()
    group_levels: dict[int, str] = {}

    def active_group_path() -> tuple[str, ...]:
        return tuple(group_levels[level] for level in sorted(group_levels))

    def finish() -> None:
        nonlocal current_label, current_lines, current_ids, current_group_path
        if current_label is None:
            return
        fields.append(
            DocumentedField(
                ordinal=len(fields),
                label=current_label,
                description=_normalize_description(current_lines),
                group_path=current_group_path,
                explicit_ids=current_ids,
            )
        )
        current_label = None
        current_lines = []
        current_ids = ()
        current_group_path = ()

    for raw in lines:
        stripped = raw.strip()
        heading = _HEADING_RE.match(raw.rstrip())
        if heading:
            finish()
            level = len(heading.group("marks"))
            if level >= 2:
                for existing_level in [key for key in group_levels if key >= level]:
                    del group_levels[existing_level]
                title = _clean_label(heading.group("title"))
                if title:
                    group_levels[level] = title
            continue
        if not stripped or stripped.startswith(":include"):
            if current_label is not None:
                current_lines.append(raw)
            continue
        if _is_field_label(raw):
            finish()
            current_label = _clean_label(stripped[:-1])
            current_group_path = active_group_path()
            continue
        if current_label is None:
            continue
        if allow_id:
            match = _PROPERTY_RE.match(stripped)
            if match and match.group("name").casefold() == "id":
                current_ids = tuple(
                    item.strip() for item in match.group("value").split(",") if item.strip()
                )
                continue
        current_lines.append(raw)
    finish()
    return fields


def _is_field_label(raw: str) -> bool:
    stripped = raw.strip()
    if not stripped.endswith(":") or stripped.startswith((":include", "#", "==")):
        return False
    if raw[:1].isspace() and not stripped.startswith("::"):
        return False
    label = _clean_label(stripped[:-1])
    return bool(label) and not label.casefold().startswith("task")


def _clean_label(value: str) -> str:
    value = value.strip().lstrip(":").strip()
    value = value.replace('"""', "").replace("__", "").replace("`", "")
    return _WHITESPACE_RE.sub(" ", value).strip()


def _normalize_description(lines: list[str]) -> str:
    output: list[str] = []
    for raw in lines:
        stripped = raw.strip()
        if not stripped or stripped.startswith(("#id:", ":include")):
            continue
        output.append(stripped.replace('"""', "").replace("__", ""))
    return _WHITESPACE_RE.sub(" ", " ".join(output)).strip()


def _parse_related(lines: list[str]) -> list[RelatedLink]:
    output: list[RelatedLink] = []
    for raw in lines:
        for match in _BOOKISH_LINK_RE.finditer(raw):
            body = match.group(1).strip()
            if "|" in body:
                label, target = body.split("|", 1)
                label = _clean_label(label) or None
                target = target.strip()
            else:
                label = None
                target = body
            kind, lookup = _related_target(target)
            output.append(RelatedLink(len(output), kind, target, label, lookup))
    return output


def _related_target(target: str) -> tuple[str, NodeTypeLookup | None]:
    value = target.strip()
    prefix, separator, rest = value.partition(":")
    if separator and prefix.casefold() == "node":
        context, slash, internal = rest.partition("/")
        if slash and context and internal:
            return "node", NodeTypeLookup(context, internal)
        return "node", None
    if value.startswith(("http://", "https://")):
        return "url", None
    if value.startswith("/"):
        return "document", None
    if separator:
        return prefix.casefold(), None
    return "unknown", None
