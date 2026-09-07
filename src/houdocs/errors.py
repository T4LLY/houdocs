from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class ErrorDetail:
    code: str
    message: str
    detail: str | None = None
    choices: tuple[str, ...] = ()


class HouDocsError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        detail: str | None = None,
        *,
        choices: Sequence[str] = (),
    ) -> None:
        super().__init__(message)
        self.error = ErrorDetail(
            code=code,
            message=message,
            detail=detail,
            choices=tuple(choices),
        )
