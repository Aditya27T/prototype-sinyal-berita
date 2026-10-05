"""Cleaning — milik Person 1. Kontrak: clean(post) -> Post | None."""
from __future__ import annotations

import re

from core.schemas import Post

_WS = re.compile(r"\s+")


def clean(post: Post) -> Post | None:
    """Rapikan whitespace, buang posting kosong. Return None = dibuang."""
    text = _WS.sub(" ", (post.text or "")).strip()
    if not text:
        return None
    # TODO(Person 1): tambah aturan (buang URL pendek? normalisasi case? dsb.)
    post.text = text
    return post
