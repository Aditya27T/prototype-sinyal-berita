"""Pipeline end-to-end — milik Person 3.

Flow (PLAN §Person 3.2): collect → clean → dedup → insert → analyze → simpan analysis.
Idempotent: posting yang sudah ada (UNIQUE platform, platform_post_id) tidak diproses ulang.
Hanya memanggil 4 signature kontrak — isi modul P1/P2 bebas diganti.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import yaml
from dotenv import load_dotenv
from sqlalchemy import select
from sqlalchemy.orm import Session

load_dotenv()

from ai.relevance import analyze, model_version
from collectors.source_one import collect
from core.schemas import Post
from database.connection import get_session_factory, init_db
from database.models import PostAnalysis, PostRow, Source
from processing.deduplicate import dedup_key
from processing.normalize import clean

ROOT = Path(__file__).resolve().parent.parent
CONFIG_SOURCES = ROOT / "config" / "sources.yaml"
CONFIG_LOCATIONS = ROOT / "config" / "locations.yaml"


def load_queries() -> list[str]:
    """Ambil seed lokasi dari config (jangan hardcode di logic)."""
    try:
        data = yaml.safe_load(CONFIG_LOCATIONS.read_text()) or {}
        locs = [str(x) for x in data.get("locations", [])]
        return locs or ["Sawojajar"]
    except Exception:
        return ["Sawojajar"]


def load_sources() -> list[dict]:
    """Semua source aktif dari config."""
    try:
        cfg = yaml.safe_load(CONFIG_SOURCES.read_text()) or {}
        sources = [s for s in cfg.get("sources", []) if s.get("active") and s.get("source_value")]
        if sources:
            return sources
    except Exception:
        pass
    return [{"platform": "threads", "source_type": "fixture", "source_value": "fixtures/sample_posts.json"}]


def match_source(post: Post, sources: dict[str, Source]) -> Source:
    """Petakan post ke source config via (platform, source_query). Fallback: source pertama."""
    sq = (post.source_query or "").strip().lstrip("#@").lower()
    cands = [(key.partition(":")[0], key.partition(":")[2], src) for key, src in sources.items()]
    for platform, value, src in cands:
        if platform == post.platform and value == sq:
            return src
    for platform, value, src in cands:
        if platform == post.platform and (value in sq or sq in value):
            return src
    return next(iter(sources.values()))


def ensure_source(session: Session, platform: str, source_type: str, source_value: str) -> Source:
    src = session.execute(
        select(Source).where(
            Source.platform == platform,
            Source.source_type == source_type,
            Source.source_value == source_value,
        )
    ).scalar_one_or_none()
    if src:
        return src
    src = Source(platform=platform, source_type=source_type, source_value=source_value, active=True)
    session.add(src)
    session.commit()
    session.refresh(src)
    return src


def post_exists(session: Session, post: Post) -> PostRow | None:
    if post.platform_post_id:
        return session.execute(
            select(PostRow).where(
                PostRow.platform == post.platform,
                PostRow.platform_post_id == post.platform_post_id,
            )
        ).scalar_one_or_none()
    # fallback tanpa ID: cocokkan url / text persis
    if post.url:
        row = session.execute(
            select(PostRow).where(PostRow.platform == post.platform, PostRow.url == post.url)
        ).scalar_one_or_none()
        if row:
            return row
    return session.execute(
        select(PostRow).where(PostRow.platform == post.platform, PostRow.text == post.text)
    ).scalar_one_or_none()


def run(limit_per_query: int = 20, only_relevant: bool = False) -> dict:
    init_db()
    SessionLocal = get_session_factory()
    stats = {"collected": 0, "clean_kept": 0, "inserted": 0, "skipped_dup": 0, "analyzed": 0}

    # daftarkan SEMUA source aktif; tiap post dipetakan ke source-nya via match_source
    active_sources = load_sources()

    with SessionLocal() as session:
        src_map: dict[tuple[str, str], Source] = {}
        for s in active_sources:
            src = ensure_source(session, s["platform"], s["source_type"], s["source_value"])
            src_map[(s["platform"], str(s["source_value"]).strip().lstrip("#@").lower())] = src
        match_map: dict[str, Source] = {f"{plat}:{val}": src for (plat, val), src in src_map.items()}
        seen_keys: set[str] = set()
        for query in load_queries():
            try:
                posts = collect(query, limit_per_query)
            except Exception as e:
                print(f"[pipeline] collect gagal query={query}: {e}")
                continue
            stats["collected"] += len(posts)
            for post in posts:
                cleaned = clean(post)
                if cleaned is None:
                    continue
                stats["clean_kept"] += 1
                key = dedup_key(cleaned)
                if key in seen_keys:
                    stats["skipped_dup"] += 1
                    continue
                seen_keys.add(key)

                existing = post_exists(session, cleaned)
                if existing:
                    # idempotent: sudah ada → pastikan analysis ada, lalu skip insert
                    has_analysis = session.execute(
                        select(PostAnalysis).where(PostAnalysis.post_id == existing.id)
                    ).scalar_one_or_none()
                    if has_analysis:
                        stats["skipped_dup"] += 1
                        continue
                    row = existing
                else:
                    row_source = match_source(cleaned, match_map)
                    row = PostRow(
                        id=str(cleaned.id),
                        source_id=row_source.id,
                        platform=cleaned.platform,
                        platform_post_id=cleaned.platform_post_id,
                        url=cleaned.url,
                        text=cleaned.text,
                        author=cleaned.author,
                        published_at=cleaned.published_at,
                        collected_at=cleaned.collected_at,
                        raw_data=cleaned.raw_data,
                    )
                    session.add(row)
                    try:
                        session.commit()
                    except Exception:
                        session.rollback()
                        stats["skipped_dup"] += 1
                        continue
                    session.refresh(row)
                    stats["inserted"] += 1

                try:
                    result = analyze(cleaned)
                except Exception as e:
                    print(f"[pipeline] analyze gagal post={cleaned.id}: {e}")
                    continue
                session.add(
                    PostAnalysis(
                        post_id=row.id,
                        is_relevant=result.is_relevant,
                        relevance_score=result.relevance_score,
                        location=result.location,
                        location_confidence=result.location_confidence,
                        issue_hint=result.issue_hint,
                        reason=result.reason,
                        model_version=model_version(),
                    )
                )
                try:
                    session.commit()
                    stats["analyzed"] += 1
                except Exception:
                    session.rollback()
        print(f"[pipeline] selesai: {stats}")
        return stats


def main() -> None:
    ap = argparse.ArgumentParser(description="Telinga Digital pipeline")
    ap.add_argument("--limit", type=int, default=20, help="limit per query")
    args = ap.parse_args()
    run(limit_per_query=args.limit)


if __name__ == "__main__":
    main()
