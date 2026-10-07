"""Ambil komentar teratas untuk posting relevan yang belum diambil komentarnya.

Tidak perlu run pipeline penuh: pipeline hanya menganalisis posting baru, jadi
posting lama yang relevan tidak pernah jadi kandidat komentar lagi. Modul ini
memilih langsung dari DB.

Biaya: 5 credit SocialCrawl per posting (hanya yang punya komentar). Saldo saat
itu dicek lebih dulu bila `--max-cost` diberikan.

Jalankan:
    uv run python -m pipeline.comments --max-posts 5
    uv run python -m pipeline.comments --max-posts 5 --all   # termasuk yang suduah diambil
"""
from __future__ import annotations

import argparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.connection import get_session_factory, init_db
from database.models import PostAnalysis, PostRow


def candidates(session: Session, include_fetched: bool = False) -> list[PostRow]:
    """Posting IG relevan, belum punya marker komentar, diurutkan komentar terbanyak."""
    rows = session.execute(
        select(PostRow)
        .join(PostAnalysis, PostAnalysis.post_id == PostRow.id)
        .where(
            PostRow.platform == "instagram",
            PostAnalysis.is_relevant.is_(True),
        )
    ).scalars().all()

    def _is_root(r: PostRow) -> bool:
        return (r.raw_data or {}).get("kind", "root") == "root"

    def _n_comments(r: PostRow) -> int:
        eng = ((r.raw_data or {}).get("post") or {}).get("engagement") or {}
        return int(eng.get("comments") or 0)

    out = [r for r in rows if _is_root(r) and _n_comments(r) > 0]
    if not include_fetched:
        out = [r for r in out if not (r.raw_data or {}).get("comments_fetched_at")]
    return sorted(out, key=_n_comments, reverse=True)


def main() -> None:
    ap = argparse.ArgumentParser(description="Ambil komentar teratas posting relevan")
    ap.add_argument("--max-posts", type=int, default=3, help="maks posting yang dibayar komentarnya")
    ap.add_argument(
        "--all", action="store_true", help="ambil juga posting yang komentarnya sudah pernah diambil"
    )
    ap.add_argument("--dry-run", action="store_true", help="tampilkan kandidat tanpa memanggil API")
    args = ap.parse_args()

    import pipeline.run as pr

    init_db()
    limit = args.max_posts
    if not args.all:
        pr.IG_COMMENTS_MAX_POSTS = limit

    with get_session_factory()() as session:
        rows = candidates(session, include_fetched=args.all)
        print(f"[comments] {len(rows)} posting relevan qualifies, took {limit} with most comments")
        for r in rows[:limit]:
            eng = ((r.raw_data or {}).get("post") or {}).get("engagement") or {}
            print(f"  - @{r.author} ({eng.get('comments')} komentar): {r.text[:60]}")
        if args.dry_run:
            print("[comments] dry-run: tidak memanggil API")
            return
        stats = pr.enrich_ig_comments(session, [r.id for r in rows])
        print(f"[comments] selesai: {stats}")


if __name__ == "__main__":
    main()