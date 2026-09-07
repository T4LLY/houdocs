from __future__ import annotations

from functools import lru_cache

OPENAI_TOKEN_ENCODING = "o200k_base"


@lru_cache(maxsize=1)
def _encoding():
    import tiktoken

    return tiktoken.get_encoding(OPENAI_TOKEN_ENCODING)


def count_openai_tokens(text: str) -> int:
    if not text:
        return 0
    return len(_encoding().encode_ordinary(text))
