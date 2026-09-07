from __future__ import annotations

import sys
from types import SimpleNamespace

from houdocs.search import tokens


def test_openai_token_counter_uses_o200k_base(monkeypatch) -> None:
    requested: list[str] = []

    class FakeEncoding:
        def encode_ordinary(self, text: str) -> list[int]:
            return list(range(len(text)))

    fake_tiktoken = SimpleNamespace(
        get_encoding=lambda name: requested.append(name) or FakeEncoding()
    )
    monkeypatch.setitem(sys.modules, "tiktoken", fake_tiktoken)
    tokens._encoding.cache_clear()
    try:
        assert tokens.count_openai_tokens("abc") == 3
        assert tokens.count_openai_tokens("") == 0
        assert requested == ["o200k_base"]
    finally:
        tokens._encoding.cache_clear()
