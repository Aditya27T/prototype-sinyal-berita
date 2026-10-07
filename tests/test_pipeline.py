"""Test idempotency pipeline (milik Person 3)."""
import importlib
import sys


def test_pipeline_idempotent(tmp_path, monkeypatch):
    db = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
    # pastikan modul baca env baru — reset singleton
    for mod in ["database.connection", "pipeline.run"]:
        sys.modules.pop(mod, None)
    import database.connection as conn

    conn._engine = None
    conn._SessionLocal = None
    conn.DATABASE_URL = f"sqlite:///{db}"
    conn.init_db(f"sqlite:///{db}")

    pr = importlib.import_module("pipeline.run")

    s1 = pr.run(limit_per_query=20)
    # jalankan ulang — inserted harus 0, skipped_dup > 0
    conn._engine = None
    conn._SessionLocal = None
    s2 = pr.run(limit_per_query=20)
    assert s1["inserted"] > 0
    assert s2["inserted"] == 0


def test_enrich_ig_comments_adds_reply_rows(tmp_path, monkeypatch):
    """Komentar teratas IG untuk posting relevan → baris reply ber-parent + analysis."""
    from datetime import datetime, timezone

    import database.connection as conn
    from core.schemas import Post
    from database.models import PostAnalysis, PostRow

    url = f"sqlite:///{tmp_path / 'c.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    conn._engine = None
    conn._SessionLocal = None
    conn.init_db(url)
    from uuid import uuid4

    import pipeline.run as pr

    now = datetime.now(timezone.utc)
    parent_url = "https://www.instagram.com/malangraya_info/p/ABC/"
    fetched: list[str] = []
    ids = {"p-rel": str(uuid4()), "p-noise": str(uuid4()), "p-rel-empty": str(uuid4())}

    def fake_fetch(parent: Post) -> list[Post]:
        fetched.append(parent.platform_post_id)
        return [
            Post(platform="instagram", platform_post_id=f"c{i}", url=parent_url,
                 text=f"Komentar warga nomor {i} tentang banjir", author=f"warga{i}",
                 published_at=now, raw_data={"kind": "reply", "parent_post_id": parent.platform_post_id})
            for i in range(2)
        ]

    monkeypatch.setattr(pr, "fetch_top_comments", fake_fetch)
    monkeypatch.setattr(pr, "IG_COMMENTS_MAX_POSTS", 3)

    with conn.get_session_factory(url)() as s:
        def _root(pid, relevant, n_comments):
            row = PostRow(id=ids[pid], platform="instagram", platform_post_id=pid, url=parent_url,
                          text="Banjir Sawojajar", author="malangraya_info", published_at=now,
                          raw_data={"kind": "root", "post": {"engagement": {"comments": n_comments}}})
            s.add(row)
            s.flush()
            s.add(PostAnalysis(post_id=ids[pid], is_relevant=relevant, relevance_score=0.9 if relevant else 0.1,
                               location="Sawojajar", issue_hint="banjir", model_version="t"))
            return row
        _root("p-rel", True, 5)
        _root("p-noise", False, 9)      # tidak relevan → jangan bayar komentar
        _root("p-rel-empty", True, 0)   # relevan tapi 0 komentar → lewati
        s.commit()

        stats = pr.enrich_ig_comments(s, list(ids.values()))
        assert fetched == ["p-rel"]
        assert stats == {"ig_comment_posts": 1, "ig_comments": 2}
        replies = s.query(PostRow).filter(PostRow.parent_post_id == ids["p-rel"]).all()
        assert len(replies) == 2
        assert all(r.raw_data["kind"] == "reply" for r in replies)
        assert s.query(PostAnalysis).filter(PostAnalysis.post_id.in_([r.id for r in replies])).count() == 2
        assert s.get(PostRow, ids["p-rel"]).raw_data.get("comments_fetched_at")

        # run kedua: induk sudah ditandai → tidak fetch lagi
        stats2 = pr.enrich_ig_comments(s, [ids["p-rel"]])
        assert fetched == ["p-rel"] and stats2["ig_comment_posts"] == 0
