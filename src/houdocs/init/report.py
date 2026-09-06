from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class InitIssue:
    severity: str
    kind: str
    detail: str
    document: str | None = None
    symbol: str | None = None
    line: int | None = None

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "severity": self.severity,
            "kind": self.kind,
            "detail": self.detail,
        }
        if self.document is not None:
            payload["document"] = self.document
        if self.symbol is not None:
            payload["symbol"] = self.symbol
        if self.line is not None:
            payload["line"] = self.line
        return payload


@dataclass
class InitReporter:
    issues: list[InitIssue] = field(default_factory=list)

    def warning(
        self,
        kind: str,
        detail: str,
        *,
        document: str | None = None,
        symbol: str | None = None,
        line: int | None = None,
    ) -> None:
        self.issues.append(
            InitIssue(
                severity="warning",
                kind=kind,
                detail=detail,
                document=document,
                symbol=symbol,
                line=line,
            )
        )

    def error(
        self,
        kind: str,
        detail: str,
        *,
        document: str | None = None,
        symbol: str | None = None,
        line: int | None = None,
    ) -> None:
        self.issues.append(
            InitIssue(
                severity="error",
                kind=kind,
                detail=detail,
                document=document,
                symbol=symbol,
                line=line,
            )
        )

    def counts(self) -> dict[str, int]:
        return {
            "warnings": sum(issue.severity == "warning" for issue in self.issues),
            "errors": sum(issue.severity == "error" for issue in self.issues),
        }

    def build(self, **fields: Any) -> dict[str, object]:
        return {
            "schema_version": 1,
            **fields,
            "issue_counts": self.counts(),
            "issues": [issue.to_dict() for issue in self.issues],
        }


def write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
