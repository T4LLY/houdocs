from __future__ import annotations

import json
from pathlib import Path

from houdocs.init.runtime import HoudiniInstallation, RuntimeSnapshot
from houdocs.init.service import InitService


class FakeRuntime:
    def __init__(self, installation: HoudiniInstallation, snapshot: RuntimeSnapshot) -> None:
        self.installation = installation
        self.snapshot = snapshot
        self.selected: list[str | None] = []
        self.probed: list[tuple[HoudiniInstallation, str | None]] = []

    def select(self, requested_version: str | None) -> HoudiniInstallation:
        self.selected.append(requested_version)
        return self.installation

    def probe(
        self,
        installation: HoudiniInstallation,
        *,
        requested_version: str | None,
    ) -> RuntimeSnapshot:
        self.probed.append((installation, requested_version))
        return self.snapshot


def test_init_service_persists_report_and_assist_compatible_node_dump(tmp_path: Path) -> None:
    help_root = tmp_path / "help"
    help_root.mkdir()
    install_root = tmp_path / "Houdini22.0.429"
    installation = HoudiniInstallation(
        root=install_root,
        bin_dir=install_root / "bin",
        houdini=install_root / "bin" / "houdini.exe",
        hcommand=install_root / "bin" / "hcommand.exe",
        version=(22, 0, 429),
    )
    payload = {
        "schema_version": 1,
        "houdini_version": "22.0.429",
        "help_directories": [str(help_root)],
        "node_type_count": 2,
        "node_types": [
            {
                "canonical_name": "Sop/good",
                "parameters": [{"id": "strength"}],
                "parameter_error": None,
            },
            {
                "canonical_name": "Sop/bad",
                "parameters": [],
                "parameter_error": "RuntimeError: broken template",
            },
        ],
    }
    snapshot = RuntimeSnapshot(
        houdini_version="22.0.429",
        help_directories=(help_root,),
        node_types=tuple(payload["node_types"]),
        payload=payload,
    )
    runtime = FakeRuntime(installation, snapshot)

    result = InitService(runtime=runtime, data_root=tmp_path / "data").run("22.0.429")

    version_root = tmp_path / "data" / "versions" / "22.0.429"
    report_path = version_root / "reports" / "init-report.json"
    dump_path = version_root / "reports" / "houdini-node-types-22.0.429.json"
    assert report_path.is_file()
    assert dump_path.is_file()
    assert not (version_root / "docs.db").exists()
    assert not (version_root / "search.db").exists()

    persisted_report = json.loads(report_path.read_text(encoding="utf-8"))
    persisted_dump = json.loads(dump_path.read_text(encoding="utf-8"))
    assert result == persisted_report
    assert persisted_dump == payload
    assert result["runtime"] == {
        "node_types": 2,
        "parameters": 1,
        "parameter_errors": 1,
    }
    assert result["issue_counts"] == {"warnings": 1, "errors": 0}
    assert result["issues"][0]["kind"] == "node_parameter_introspection_error"
    assert result["issues"][0]["symbol"] == "Sop/bad"
    assert runtime.selected == ["22.0.429"]
    assert runtime.probed == [(installation, "22.0.429")]
