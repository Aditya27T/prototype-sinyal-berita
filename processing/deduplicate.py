"""Dedup — milik Person 1. Kontrak: dedup_key(post) -> str (PLAN §3.3)."""
from __future__ import annotations

import hashlib
import re

from core.schemas import Post

_WS = re.compile(r"\s+")


def _norm_text(text: str) -> str:
    return _WS.sub(" ", text.strip().lower())


def dedup_key(post: Post) -> str:
    """platform + platform_post_id; fallback hash URL, lalu hash text."""
    if post.platform_post_id:
        return f"{post.platform}:{post.platform_post_id}"
    if post.url:
        h = hashlib.sha256(post.url.encode()).hexdigest()[:16]
        return f"{post.platform}:url:{h}"
    h = hashlib.sha256(_norm_text(post.text).encode()).hexdigest()[:16]
    return f"{post.platform}:text:{h}"
