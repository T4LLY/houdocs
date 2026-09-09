from __future__ import annotations

from collections.abc import Callable

SpecializedIssueCallback = Callable[[str, str, str | None, str | None], None]


def emit_specialized_issue(
    callback: SpecializedIssueCallback | None,
    kind: str,
    detail: str,
    document: str | None,
    symbol: str | None,
) -> None:
    if callback is not None:
        callback(kind, detail, document, symbol)
