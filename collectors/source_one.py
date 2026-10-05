"""Source pertama — milik Person 1: Instagram via SocialCrawl API.

Kontrak: collect(query: str, limit: int) -> list[Post] (PLAN §3.3).

- query = handle akun di config/sources.yaml → posting hari ini dari akun itu.
- query lain (mis. lokasi dari pipeline) → posting hari ini dari SEMUA akun aktif
  (tidak disaring lokasi; relevansi urusan Person 2). Fetch di-cache per proses,
  jadi credit SocialCrawl terpakai sekali per run.

Urutan sumber per akun: SocialCrawl (bila SOCIALCRAWL_API_KEY ada) → snapshot
fixtures/instagram_<tanggal>.json → kosong. Bila semua kosong: fallback
fixtures/sample_posts.json agar demo offline & test tetap jalan.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import yaml
from dotenv import load_dotenv

from collectors.base import BaseCollector
from core.schemas import Post

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = ROOT / "fixtures"
FIXTURE_FILE = FIXTURE_DIR / "sample_posts.json"
CONFIG_SOURCES = ROOT / "config" / "sources.yaml"

WIB = ZoneInfo("Asia/Jakarta")
MAX_PAGES = 3  # batas credit per akun per run

_cache: dict[str, list[Post]] = {}


def _today_wib() -> str:
    return datetime.now(WIB).date().isoformat()


def _snapshot_file() -> Path:
    return FIXTURE_DIR / f"instagram_{_today_wib()}.json"


def _load_accounts() -> list[str]:
    try:
        cfg = yaml.safe_load(CONFIG_SOURCES.read_text()) or {}
    except Exception:
        return []
    return [
        str(s["source_value"]).lstrip("@")
        for s in cfg.get("sources", [])
        if s.get("active") and s.get("platform") == "instagram" and s.get("source_value")
    ]


def _parse_dt(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    try:
        if isinstance(value, (int, float)):
            ts = value / 1000 if value > 1e12 else value
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _is_today_wib(dt: datetime | None) -> bool:
    return dt is not None and dt.astimezone(WIB).date().isoformat() == _today_wib()


def _unwrap(item: dict) -> dict:
    """SocialCrawl membungkus tiap item: {"post": {...}, "computed": {...}}."""
    return item.get("post", item) if isinstance(item, dict) else {}


def _caption(item: dict) -> str:
    content = item.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        for k in ("text", "caption", "description", "title"):
            if content.get(k):
                return str(content[k])
    for k in ("caption", "text", "description"):
        if item.get(k):
            return str(item[k])
    return ""


def _items_and_cursor(body: dict) -> tuple[list[dict], str | None]:
    data = body.get("data", body)
    if isinstance(data, list):
        return data, None
    items: list[dict] = []
    for k in ("items", "posts", "results", "data"):
        if isinstance(data.get(k), list):
            items = data[k]
            break
    return items, data.get("next_cursor")


def _fetch_socialcrawl(handle: str) -> list[dict] | None:
    """Item mentah posting dari SocialCrawl; None bila tanpa key / gagal."""
    api_key = os.getenv("SOCIALCRAWL_API_KEY", "").strip()
    if not api_key:
        return None
    base = os.getenv("SOCIALCRAWL_BASE_URL", "https://www.socialcrawl.dev/v1").rstrip("/")
    items: list[dict] = []
    cursor: str | None = None
    try:
        with httpx.Client(timeout=30, headers={"x-api-key": api_key}) as client:
            for _ in range(MAX_PAGES):
                params = {"handle": handle}
                if cursor:
                    params["cursor"] = cursor
                resp = client.get(f"{base}/instagram/profile/posts", params=params)
                resp.raise_for_status()
                page, cursor = _items_and_cursor(resp.json())
                items.extend(page)
                # berhenti bila satu halaman tak berisi posting hari ini (pinned post bisa lama,
                # jadi jangan berhenti di posting lama pertama)
                if not cursor or not any(
                    _is_today_wib(_parse_dt(_unwrap(i).get("published_at"))) for i in page
                ):
                    break
    except Exception as e:
        print(f"[collector] SocialCrawl gagal handle={handle}: {e}")
        return items or None
    return items


def _load_snapshot() -> dict[str, list[dict]]:
    f = _snapshot_file()
    if not f.exists():
        return {}
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_snapshot(handle: str, items: list[dict]) -> None:
    snap = _load_snapshot()
    snap[handle] = items
    try:
        _snapshot_file().write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"[collector] gagal simpan snapshot: {e}")


def _to_post(raw: dict, handle: str) -> Post | None:
    item = _unwrap(raw)
    text = _caption(item)
    if not text.strip():
        return None
    author = item.get("author") or {}
    url = item.get("url")
    post_id = item.get("id") or item.get("shortcode")
    if not post_id and url:
        post_id = url.rstrip("/").rsplit("/", 1)[-1]
    try:
        return Post(
            platform="instagram",
            platform_post_id=str(post_id) if post_id else None,
            url=url,
            text=text,
            author=(author.get("username") if isinstance(author, dict) else None) or handle,
            published_at=_parse_dt(item.get("published_at")),
            source_query=handle,
            raw_data=raw,
        )
    except Exception:
        return None


def _account_posts(handle: str) -> list[Post]:
    """Posting hari ini dari satu akun (cache per proses)."""
    if handle in _cache:
        return _cache[handle]
    items = _fetch_socialcrawl(handle)
    if items:
        _save_snapshot(handle, items)
        print(f"[collector] {handle}: {len(items)} item dari SocialCrawl")
    else:
        items = _load_snapshot().get(handle, [])
        if items:
            print(f"[collector] {handle}: {len(items)} item dari snapshot {_snapshot_file().name}")
    posts = [p for p in (_to_post(i, handle) for i in items) if p and _is_today_wib(p.published_at)]
    posts.sort(key=lambda p: p.published_at, reverse=True)
    _cache[handle] = posts
    return posts


def _sample_fallback(query: str, limit: int) -> list[Post]:
    """Fallback lama: fixtures/sample_posts.json (demo offline & test)."""
    if not FIXTURE_FILE.exists():
        return []
    raw = json.loads(FIXTURE_FILE.read_text(encoding="utf-8"))
    q = query.lower()
    posts: list[Post] = []
    for item in raw:
        if q and q not in item.get("text", "").lower() and q not in str(item.get("source_query", "")).lower():
            continue
        try:
            posts.append(Post(**item))
        except Exception:
            continue
        if len(posts) >= limit:
            break
    if not posts:
        for item in raw[:limit]:
            try:
                posts.append(Post(**item))
            except Exception:
                continue
    return posts


class SourceOneCollector(BaseCollector):
    platform: str = "instagram"

    def collect(self, query: str, limit: int = 20) -> list[Post]:
        accounts = _load_accounts()
        handle = query.strip().lstrip("@").lower()
        targets = [a for a in accounts if a.lower() == handle] or accounts
        posts = [p for a in targets for p in _account_posts(a)]
        live = os.getenv("SOCIALCRAWL_API_KEY", "").strip() or _snapshot_file().exists()
        if not posts and not live:
            # tanpa key & tanpa snapshot → data contoh (jangan campur ke mode live)
            return _sample_fallback(query, limit)
        posts.sort(key=lambda p: p.published_at, reverse=True)
        return posts[:limit]


def collect(query: str, limit: int = 20) -> list[Post]:
    """Signature yang dipanggil pipeline Person 3."""
    return SourceOneCollector().collect(query, limit)
