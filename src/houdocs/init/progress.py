from __future__ import annotations

import sys
import time
from collections import deque
from collections.abc import Callable, Iterator
from contextlib import contextmanager
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
        self._phase_name: str | None = None
        self._phase_started_at: float | None = None
        self._document_current = 0
        self._document_total = 0
        self._document_last_at: float | None = None
        self._document_durations: deque[float] = deque(maxlen=self._RECENT_DOCUMENTS)
        self._embedding_batches: deque[tuple[int, float]] = deque(
            maxlen=self._RECENT_DOCUMENTS
        )

    @contextmanager
    def phase(self, name: str) -> Iterator[None]:
        self.start_phase(name)
        try:
            yield
        except BaseException:
            self.finish()
            self._phase_name = None
            self._phase_started_at = None
            raise
        else:
            self.complete_phase()

    def start_phase(self, name: str) -> None:
        if not self.enabled:
            return
        if self._phase_started_at is not None:
            raise RuntimeError("Initialization progress phase already active.")
        self._phase_name = name
        self._phase_started_at = self._clock()
        self.show(f"          RUN   {name}")

    def complete_phase(self) -> None:
        if not self.enabled or self._phase_started_at is None or self._phase_name is None:
            return
        elapsed = max(0.0, self._clock() - self._phase_started_at)
        name = self._phase_name
        self._clear_line()
        self._stream.write(f"[{elapsed / 60.0:5.1f}m] DONE  {name}\n")
        self._stream.flush()
        self._phase_name = None
        self._phase_started_at = None

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
        if current == 0:
            self._embedding_batches.clear()
        if total == 0:
            self.show("Embedding search sections: cached")
            return
        if batch_count > 0:
            self._embedding_batches.append((batch_count, max(0.0, batch_seconds)))

        percent = int(current * 100 / total)
        message = f"Embedding search sections: {current}/{total} ({percent}%) uncached"
        eta = self._embedding_eta_seconds(current, total)
        if eta is not None:
            message += f" | ETA {_format_eta(eta)}"
        elif current < total:
            message += " | ETA --"
        self.show(message)

    def _embedding_eta_seconds(self, current: int, total: int) -> float | None:
        if current >= total:
            return 0.0
        sections = sum(count for count, _seconds in self._embedding_batches)
        if sections <= 0:
            return None
        seconds = sum(seconds for _count, seconds in self._embedding_batches)
        return (seconds / sections) * (total - current)

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

    def _clear_line(self) -> None:
        if not self._open:
            return
        self._stream.write(f"\r{' ' * self._width}\r")
        self._width = 0
        self._open = False

    def finish(self) -> None:
        if not self.enabled or not self._open:
            return
        self._stream.write("\n")
        self._stream.flush()
        self._width = 0
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
