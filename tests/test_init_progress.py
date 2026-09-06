from __future__ import annotations

import io

from houdocs.init.progress import InitProgress


class _TtyBuffer(io.StringIO):
    def isatty(self) -> bool:
        return True


def test_init_progress_updates_one_tty_line_without_ansi() -> None:
    stream = _TtyBuffer()
    progress = InitProgress(True, stream=stream)

    progress.show("Reading Houdini help archives")
    progress.indexing(25, 100)
    progress.finish()

    output = stream.getvalue()
    assert output.startswith("\rReading Houdini help archives")
    assert "\rParsing Houdini help documents: 25/100 (25%)" in output
    assert output.endswith("\n")
    assert "\x1b" not in output


def test_init_progress_eta_uses_only_most_recent_30_documents() -> None:
    stream = _TtyBuffer()
    now = [0.0]
    progress = InitProgress(True, stream=stream, clock=lambda: now[0])

    progress.indexing(0, 100)
    for current in range(1, 31):
        now[0] += 1.0
        progress.indexing(current, 100)

    # The 31st completion takes 31 seconds. A full-history average would use
    # all 31 samples; the required ETA window drops the oldest 1-second sample.
    now[0] += 31.0
    progress.indexing(31, 100)
    progress.finish()

    # Recent-30 average = (29 * 1 + 31) / 30 = 2 sec/doc.
    # 69 documents remain, so ETA is 138 seconds = 2m 18s.
    assert "ETA 2m 18s" in stream.getvalue()


def test_init_progress_uses_available_samples_before_30_documents() -> None:
    stream = _TtyBuffer()
    now = [0.0]
    progress = InitProgress(True, stream=stream, clock=lambda: now[0])

    progress.indexing(0, 10)
    now[0] = 2.0
    progress.indexing(1, 10)
    now[0] = 6.0
    progress.indexing(2, 10)
    progress.finish()

    # Mean of 2s and 4s = 3s/document, with 8 documents remaining.
    assert "ETA 24s" in stream.getvalue()


def test_init_progress_reports_embedding_state_separately() -> None:
    stream = _TtyBuffer()
    progress = InitProgress(True, stream=stream)

    progress.embedding(0, 12, 0, 0.0)
    progress.embedding(12, 12, 12, 1.0)
    progress.finish()

    output = stream.getvalue()
    assert "Embedding search sections: 0/12 uncached" in output
    assert "Embedding search sections: 12/12 uncached" in output


def test_init_progress_reports_fully_cached_embeddings() -> None:
    stream = _TtyBuffer()
    progress = InitProgress(True, stream=stream)

    progress.embedding(0, 0, 0, 0.0)
    progress.finish()

    assert "Embedding search sections: cached" in stream.getvalue()


def test_init_progress_is_silent_for_non_tty_streams() -> None:
    stream = io.StringIO()
    progress = InitProgress(True, stream=stream)

    progress.show("Starting Houdini")
    progress.indexing(1, 2)
    progress.finish()

    assert stream.getvalue() == ""
