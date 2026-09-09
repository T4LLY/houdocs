from __future__ import annotations

import re

_WHITESPACE_RE = re.compile(r"\s+")


def clean_label(value: str) -> str:
    value = value.strip().lstrip(":").strip()
    value = value.replace('"""', "").replace("__", "").replace("`", "")
    return _WHITESPACE_RE.sub(" ", value).strip()
