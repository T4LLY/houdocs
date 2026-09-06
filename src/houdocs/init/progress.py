from __future__ import annotations

import sys
import time
from collections import deque
from collections.abc import Callable
from typing import TextIO


class InitProgress:
    _RECENT_DOCUMENTS = 30

    def __init__(
        self,
        enabled: bool,
        *,
        stream: TextIO | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._stream = stream or sys.stderr
        self._clock = clock or time.monotonic
        self.enabled = enabled and self._stream.isatty()
        self._width = 0
        self._open = False
        self._document_current = 0
        self._document_total = 0
        self._document_last_at: float | None = None
        self._document_durations: deque[float] = deque(maxlen=self._RECENT_DOCUMENTS)

    def show(self, message: str) -> None:
        if not self.enabled:
            return
        padding = " " * max(0, self._width - len(message))
        self._stream.write(f"\r{message}{padding}")
        self._stream.flush()
        self._width = len(message)
        self._open = True

    def indexing(self, current: int, total: int) -> None:
        now = self._clock()
        if current == 0:
            self._document_current = 0
            self._document_total = total
            self._document_last_at = now
            self._document_durations.clear()
            self._render_indexing()
            return

        previous = self._document_current
        if self._document_last_at is not None and current > previous:
            elapsed = max(0.0, now - self._document_last_at)
            per_document = elapsed / (current - previous)
            for _ in range(current - previous):
                self._document_durations.append(per_document)
        self._document_current = current
        self._document_total = total
        self._document_last_at = now
        self._render_indexing()

    def embedding(
        self,
        current: int,
        total: int,
        batch_count: int,
        batch_seconds: float,
    ) -> None:
        del batch_count, batch_seconds
        if total == 0:
            self.show("Embedding search sections: cached")
            return
        self.show(f"Embedding search sections: {current}/{total} uncached")

    def _render_indexing(self) -> None:
        percent = (
            100
            if self._document_total == 0
            else int(self._document_current * 100 / self._document_total)
        )
        message = (
            f"Parsing Houdini help documents: {self._document_current}/{self._document_total} "
            f"({percent}%)"
        )
        eta = self._document_eta_seconds()
        if eta is not None:
            message += f" | ETA {_format_eta(eta)}"
        elif self._document_total > self._document_current:
            message += " | ETA --"
        self.show(message)

    def _document_eta_seconds(self) -> float | None:
        if self._document_current >= self._document_total:
            return 0.0 if self._document_total else None
        if not self._document_durations:
            return None
        average = sum(self._document_durations) / len(self._document_durations)
        remaining = self._document_total - self._document_current
        return average * remaining

    def finish(self) -> None:
        if not self.enabled or not self._open:
            return
        self._stream.write("\n")
        self._stream.flush()
        self._open = False


def _format_eta(seconds: float) -> str:
    rounded = max(0, int(round(seconds)))
    if rounded < 60:
        return f"{rounded}s"
    minutes, secs = divmod(rounded, 60)
    if minutes < 60:
        return f"{minutes}m {secs:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m"
