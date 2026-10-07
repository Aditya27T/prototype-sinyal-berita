"""Pipeline end-to-end — milik Person 3.

Flow (PLAN §Person 3.2): collect → clean → dedup → insert → analyze → simpan analysis.
Idempotent: posting yang sudah ada (UNIQUE platform, platform_post_id) tidak diproses ulang.
Hanya memanggil 4 signature kontrak — isi modul P1/P2 bebas diganti.
"""
from __future__ import annotations

import argparse
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml
from dotenv import load_dotenv
from sqlalchemy import select
from sqlalchemy.orm import Session

load_dotenv()

from ai.relevance import analyze, llm_unavailable, model_version, provider
from collectors.source_one import collect, fetch_top_comments
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


def resolve_parent_id(session: Session, post: Post) -> str | None:
    """ID baris `posts` untuk induk posting reply (dari raw_data.parent_post_id)."""
    parent_platform_id = post.raw_data.get("parent_post_id")
    if not parent_platform_id:
        return None
    row = session.execute(
        select(PostRow.id).where(
            PostRow.platform == post.platform,
            PostRow.platform_post_id == str(parent_platform_id),
        )
    ).scalar_one_or_none()
    return row


def link_replies(session: Session) -> int:
    """Isi parent_post_id untuk reply yang induknya baru masuk di run yang sama."""
    orphans = session.execute(select(PostRow).where(PostRow.parent_post_id.is_(None))).scalars().all()
    linked = 0
    for row in orphans:
        if (row.raw_data or {}).get("kind") != "reply":
            continue
        parent_platform_id = (row.raw_data or {}).get("parent_post_id")
        if not parent_platform_id:
            continue
        pid = session.execute(
            select(PostRow.id).where(
                PostRow.platform == row.platform,
                PostRow.platform_post_id == str(parent_platform_id),
            )
        ).scalar_one_or_none()
        if pid:
            row.parent_post_id = pid
            linked += 1
    if linked:
        session.commit()
        print(f"[pipeline] {linked} balasan dihubungkan ke induknya")
    return linked


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


def _model_version_for(result) -> str:
    """Label jujur: jangan tulis nama model LLM bila analyze() jatuh ke heuristic."""
    if "llm-fallback" in (result.reason or ""):
        return "heuristic-fallback"
    return model_version()


def _pace() -> None:
    """Jeda antar panggilan LLM free-tier; tidak perlu saat heuristic/kuota habis."""
    pace = float(os.getenv("AI_PACE_SECONDS", "5"))
    if pace > 0 and provider() != "heuristic" and not llm_unavailable():
        time.sleep(pace)


def _save_analysis(session: Session, row: PostRow, post: Post) -> bool:
    """analyze() + simpan post_analysis untuk satu baris; False bila gagal."""
    try:
        result = analyze(post)
    except Exception as e:
        print(f"[pipeline] analyze gagal post={post.id}: {e}")
        return False
    _pace()
    session.add(
        PostAnalysis(
            post_id=row.id,
            is_relevant=result.is_relevant,
            relevance_score=result.relevance_score,
            location=result.location,
            location_confidence=result.location_confidence,
            issue_hint=result.issue_hint,
            reason=result.reason,
            model_version=_model_version_for(result),
        )
    )
    try:
        session.commit()
        return True
    except Exception:
        session.rollback()
        return False


# posting IG relevan yang komentarnya diambil per run (5 credit per posting)
IG_COMMENTS_MAX_POSTS = int(os.getenv("IG_COMMENTS_MAX_POSTS", "3"))


def _row_to_post(row: PostRow) -> Post:
    return Post(
        id=row.id,
        platform=row.platform,
        platform_post_id=row.platform_post_id,
        url=row.url,
        text=row.text,
        author=row.author,
        published_at=row.published_at,
        collected_at=row.collected_at,
        source_query=(row.raw_data or {}).get("source_query") or row.author,
        raw_data=row.raw_data or {},
    )


def enrich_ig_comments(session: Session, post_ids: list[str]) -> dict:
    """Komentar teratas untuk posting IG relevan dari run ini → baris reply + analysis.

    Prioritas: posting dengan `engagement.comments` terbanyak. Induk ditandai
    `raw_data.comments_fetched_at` agar run berikutnya tidak membayar ulang.
    """
    stats = {"ig_comment_posts": 0, "ig_comments": 0}
    if not post_ids or IG_COMMENTS_MAX_POSTS <= 0:
        return stats
    rows = session.execute(
        select(PostRow)
        .join(PostAnalysis, PostAnalysis.post_id == PostRow.id)
        .where(
            PostRow.id.in_(post_ids),
            PostRow.platform == "instagram",
            PostAnalysis.is_relevant.is_(True),
        )
    ).scalars().all()
    candidates = [
        r for r in rows
        if (r.raw_data or {}).get("kind", "root") == "root"
        and not (r.raw_data or {}).get("comments_fetched_at")
    ]

    def _n_comments(r: PostRow) -> int:
        eng = ((r.raw_data or {}).get("post") or {}).get("engagement") or {}
        return int(eng.get("comments") or 0)

    candidates.sort(key=_n_comments, reverse=True)
    for parent_row in candidates[:IG_COMMENTS_MAX_POSTS]:
        if _n_comments(parent_row) == 0:
            continue  # tidak ada komentar: jangan bayar 5 credit untuk halaman kosong
        parent = _row_to_post(parent_row)
        comments = fetch_top_comments(parent)
        parent_row.raw_data = {**(parent_row.raw_data or {}), "comments_fetched_at": datetime.now(timezone.utc).isoformat()}
        session.commit()
        stats["ig_comment_posts"] += 1
        for c in comments:
            if post_exists(session, c):
                continue
            row = PostRow(
                id=str(c.id),
                source_id=parent_row.source_id,
                platform=c.platform,
                platform_post_id=c.platform_post_id,
                url=c.url,
                text=c.text,
                author=c.author,
                published_at=c.published_at,
                collected_at=c.collected_at,
                raw_data=c.raw_data,
                parent_post_id=parent_row.id,
            )
            session.add(row)
            try:
                session.commit()
            except Exception:
                session.rollback()
                continue
            session.refresh(row)
            stats["ig_comments"] += 1
            _save_analysis(session, row, c)
    if stats["ig_comment_posts"]:
        print(f"[pipeline] komentar IG: {stats}")
    return stats


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
        analyzed_ids: list[str] = []  # kandidat enrich komentar IG (hanya yang dinilai run ini)
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
                        parent_post_id=resolve_parent_id(session, cleaned),
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

                if _save_analysis(session, row, cleaned):
                    stats["analyzed"] += 1
                    analyzed_ids.append(row.id)
        stats.update(enrich_ig_comments(session, analyzed_ids))
        print(f"[pipeline] selesai: {stats} (replies_terhubung={link_replies(session)})")
        return stats


def main() -> None:
    ap = argparse.ArgumentParser(description="Telinga Digital pipeline")
    ap.add_argument("--limit", type=int, default=20, help="limit per query")
    args = ap.parse_args()
    run(limit_per_query=args.limit)


if __name__ == "__main__":
    main()
