"""Self-contained Houdini worker for initialization runtime metadata."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import hou  # type: ignore


def _safe(fn: Callable[[], Any], default: Any = None) -> Any:
    try:
        return fn()
    except Exception:
        return default


def _enum_text(value: object) -> str | None:
    return None if value is None else str(value)


_MULTIPARM_TYPES = {
    hou.folderType.MultiparmBlock,
    hou.folderType.ScrollingMultiparmBlock,
    hou.folderType.TabbedMultiparmBlock,
}


def _collect_parameters(node_type: Any) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    parameter_ordinal = 0
    layout_ordinal = 0

    def walk(
        container: Any,
        folder_path: tuple[str, ...] = (),
        multiparm_path: tuple[str, ...] = (),
    ) -> None:
        nonlocal parameter_ordinal, layout_ordinal
        for parm_template in container.parmTemplates():
            current_layout_ordinal = layout_ordinal
            layout_ordinal += 1
            if isinstance(parm_template, hou.FolderParmTemplate):
                folder_type = _safe(parm_template.folderType)
                is_actual_folder = bool(_safe(parm_template.isActualFolder, False))
                name = _safe(parm_template.name, "")
                label = _safe(parm_template.label, "")
                folder_name = label or name
                if is_actual_folder:
                    walk(parm_template, folder_path + (folder_name,), multiparm_path)
                    continue

                is_multiparm = folder_type in _MULTIPARM_TYPES
                if is_multiparm:
                    result.append(
                        {
                            "parameter_ordinal": parameter_ordinal,
                            "layout_ordinal": current_layout_ordinal,
                            "id": name,
                            "label": label,
                            "type": _enum_text(_safe(parm_template.type)),
                            "num_components": _safe(parm_template.numComponents),
                            "folder_path": list(folder_path),
                            "multiparm_path": list(multiparm_path),
                            "is_multiparm": True,
                            "folder_type": _enum_text(folder_type),
                            "hidden": _safe(parm_template.isHidden),
                            "label_hidden": _safe(parm_template.isLabelHidden),
                        }
                    )
                    parameter_ordinal += 1
                walk(
                    parm_template,
                    folder_path + (folder_name,),
                    multiparm_path + ((name or folder_name),)
                    if is_multiparm
                    else multiparm_path,
                )
                continue

            is_non_value = isinstance(
                parm_template,
                (hou.LabelParmTemplate, hou.SeparatorParmTemplate),
            )
            result.append(
                {
                    "parameter_ordinal": None if is_non_value else parameter_ordinal,
                    "layout_ordinal": current_layout_ordinal,
                    "id": _safe(parm_template.name, ""),
                    "label": _safe(parm_template.label, ""),
                    "type": _enum_text(_safe(parm_template.type)),
                    "num_components": _safe(parm_template.numComponents),
                    "folder_path": list(folder_path),
                    "multiparm_path": list(multiparm_path),
                    "is_multiparm": False,
                    "stores_value": not is_non_value,
                    "hidden": _safe(parm_template.isHidden),
                    "label_hidden": _safe(parm_template.isLabelHidden),
                    "join_with_next": _safe(parm_template.joinWithNext),
                }
            )
            if not is_non_value:
                parameter_ordinal += 1

    walk(node_type.parmTemplateGroup())
    return result


def _collect_node_types() -> list[dict[str, object]]:
    node_types: list[dict[str, object]] = []
    for category_name, category in sorted(hou.nodeTypeCategories().items()):
        for type_name, node_type in sorted(category.nodeTypes().items()):
            components = _safe(node_type.nameComponents, ("", "", type_name, ""))
            while len(components) < 4:
                components = tuple(components) + ("",)
            scope, namespace, core_name, version = components[:4]
            try:
                parameters = _collect_parameters(node_type)
                parameter_error = None
            except Exception as exc:
                parameters = []
                parameter_error = f"{type(exc).__name__}: {exc}"

            node_types.append(
                {
                    "category": category_name,
                    "name": node_type.name(),
                    "canonical_name": _safe(
                        node_type.nameWithCategory,
                        f"{category_name}/{node_type.name()}",
                    ),
                    "description": _safe(node_type.description, ""),
                    "scope": scope,
                    "namespace": namespace,
                    "core_name": core_name,
                    "version": version,
                    "min_inputs": _safe(node_type.minNumInputs),
                    "max_inputs": _safe(node_type.maxNumInputs),
                    "max_outputs": _safe(node_type.maxNumOutputs),
                    "parameters": parameters,
                    "parameter_error": parameter_error,
                }
            )
    return node_types


def _help_directories() -> list[str]:
    try:
        return list(hou.findDirectories("help"))
    except hou.OperationFailed:
        return []


def build_payload() -> dict[str, object]:
    node_types = _collect_node_types()
    return {
        "schema_version": 1,
        "houdini_version": str(hou.applicationVersionString()),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "help_directories": _help_directories(),
        "node_type_count": len(node_types),
        "node_types": node_types,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(build_payload(), ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
