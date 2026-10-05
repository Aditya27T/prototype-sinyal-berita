"""Source pertama — milik Person 1.

Kontrak: collect(query: str, limit: int) -> list[Post] (PLAN §3.3).
Person 1 bebas ganti isi: API resmi / HTTP publik + BeautifulSoup.
Untuk sekarang: fallback baca fixtures agar pipeline Person 3 bisa demo.
"""
from __future__ import annotations

import json
from pathlib import Path

from collectors.base import BaseCollector
from core.schemas import Post

FIXTURE_FILE = Path(__file__).resolve().parent.parent / "fixtures" / "sample_posts.json"


class SourceOneCollector(BaseCollector):
    platform: str = "threads"

    def collect(self, query: str, limit: int = 20) -> list[Post]:
        # TODO(Person 1): ganti dengan httpx/BeautifulSoup ke source publik pilihan.
        # Sementara: filter fixtures berdasarkan query agar end-to-end jalan.
        if not FIXTURE_FILE.exists():
            return []
        raw = json.loads(FIXTURE_FILE.read_text())
        posts: list[Post] = []
        q = query.lower()
        for item in raw:
            text = item.get("text", "")
            sq = str(item.get("source_query", "")).lower()
            if q and q not in text.lower() and q not in sq:
                # tetap sertakan bila query kosong; bila query ada tapi tak cocok, skip
                continue
            try:
                posts.append(Post(**item))
            except Exception:
                continue
            if len(posts) >= limit:
                break
        # fallback: bila filter terlalu ketat, kembalikan N pertama
        if not posts:
            for item in raw[:limit]:
                try:
                    posts.append(Post(**item))
                except Exception:
                    continue
        return posts


def collect(query: str, limit: int = 20) -> list[Post]:
    """Signature yang dipanggil pipeline Person 3."""
    return SourceOneCollector().collect(query, limit)
