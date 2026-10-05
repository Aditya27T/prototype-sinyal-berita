"""Cleaning — milik Person 1. Kontrak: clean(post) -> Post | None."""
from __future__ import annotations

import re

from core.schemas import Post

_WS = re.compile(r"\s+")
# baris yang isinya hanya hashtag (blok tag di akhir caption Instagram)
_HASHTAG_LINE = re.compile(r"^\s*(?:[#.][\w.]*\s*)+$")


def _strip_hashtag_block(text: str) -> str:
    lines = text.splitlines()
    while lines and (not lines[-1].strip() or _HASHTAG_LINE.match(lines[-1])):
        lines.pop()
    return "\n".join(lines)


def clean(post: Post) -> Post | None:
    """Buang blok hashtag di akhir, rapikan whitespace, buang posting kosong. None = dibuang.

    Iklan/endorse TIDAK dibuang di sini — itu tugas AI relevance (Person 2).
    """
    text = _WS.sub(" ", _strip_hashtag_block(post.text or "")).strip()
    if not text:
        return None
    post.text = text
    return post
