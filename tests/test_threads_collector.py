"""Test offline collector Threads: mapper balasan, saringan tag, dispatch per source.

Tanpa API key dan tanpa snapshot — semua fetcher dimonkeypatch, jadi tidak
menyentuh credit SocialCrawl.
"""
from datetime import datetime, timezone

import collectors.source_one as so

# tanggal dinamis: _fresh_enough membuang posting yang bukan "hari ini"
TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _root_item(pid="111", url="https://www.threads.com/@infomalangan/post/AAA", text="Banjir Sawojajar parah"):
    return {
        "post": {
            "id": pid,
            "url": url,
            "content": {"text": text},
            "author": {"username": "infomalangan"},
            "published_at": TODAY,
            "ext": {"topic_tag": "Malang"},
        }
    }


def _reply_item(pid="222", text="Disini genangan air tidaksted flows", author="warga1"):
    return {
        "post": {
            "id": pid,
            "url": "https://www.threads.com/@warga1/post/BBB",
            "content": {"text": text},
            "author": {"username": author},
            "published_at": TODAY,
        }
    }


def _reset(monkeypatch):
    so._cache.clear()
    monkeypatch.delenv("SNAPSHOT_DATE", raising=False)
    monkeypatch.setattr(so, "_today_wib", lambda: datetime.now(so.WIB).date().isoformat())
    monkeypatch.setattr(so, "_snapshot_file", lambda: so.FIXTURE_DIR / "tidak-ada.json")
    monkeypatch.setattr(so, "_save_snapshot", lambda key, items: None)  # test tidak menulis fixtures/
    monkeypatch.setattr(so, "_since_date", lambda: so._today_wib())


def test_reply_maps_parent_metadata(monkeypatch):
    _reset(monkeypatch)
    parent = so._to_post(_root_item(), "infomalangan", "threads")
    reply = so._reply_to_post(_reply_item(), parent, "infomalangan")
    assert reply is not None
    assert reply.raw_data["kind"] == "reply"
    assert reply.raw_data["parent_post_id"] == "111"
    assert reply.raw_data["parent_url"] == "https://www.threads.com/@infomalangan/post/AAA"
    assert reply.platform_post_id == "222"


def test_reply_drops_short_and_deleted(monkeypatch):
    _reset(monkeypatch)
    parent = so._to_post(_root_item(), "infomalangan", "threads")
    assert so._reply_to_post(_reply_item(text="👍"), parent, "x") is None
    assert so._reply_to_post(_reply_item(text="@user"), parent, "x") is None
    deleted = _reply_item()
    deleted["post"]["flags"] = {"deleted": True}
    assert so._reply_to_post(deleted, parent, "x") is None


def test_tag_filter_keeps_only_matching_topic_tag(monkeypatch):
    _reset(monkeypatch)
    items = [
        _root_item(pid="1"),
        _root_item(pid="2", url="https://www.threads.com/@a/post/CCC", text="Cuma menyebut kata malang"),
        _root_item(pid="3", url="https://www.threads.com/@a/post/DDD", text="Tag malangraya bukan malang"),
    ]
    items[1]["post"]["ext"] = {"topic_tag": None}
    items[2]["post"]["ext"] = {"topic_tag": "MalangRaya"}

    monkeypatch.setattr(so, "_api", lambda: ("https://x/v1", "k"))

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": {"items": items}}

    class _Client:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, params=None):
            assert url.endswith("/threads/search")
            assert params["query"] == "malang"
            return _Resp()

    monkeypatch.setattr(so.httpx, "Client", _Client)
    got = so._fetch_threads_tag("#Malang")
    assert [so._unwrap(i)["id"] for i in got] == ["1"]


def test_source_posts_account_returns_root_and_replies(monkeypatch):
    _reset(monkeypatch)
    monkeypatch.setattr(so, "_fetch_threads_user_posts", lambda handle: [_root_item()])
    monkeypatch.setattr(so, "_fetch_threads_replies", lambda url: [_reply_item()])
    source = {"platform": "threads", "source_type": "account", "source_value": "infomalangan", "replies": True}
    posts = so._source_posts(source)
    kinds = [p.raw_data["kind"] for p in posts]
    assert kinds.count("root") == 1
    assert kinds.count("reply") == 1
    reply = next(p for p in posts if p.raw_data["kind"] == "reply")
    assert reply.raw_data["parent_post_id"] == "111"


def test_account_without_replies_flag(monkeypatch):
    _reset(monkeypatch)
    monkeypatch.setattr(so, "_fetch_threads_user_posts", lambda handle: [_root_item()])

    def _boom(url):
        raise AssertionError("balasan tidak boleh diambil bila replies=false")

    monkeypatch.setattr(so, "_fetch_threads_replies", _boom)
    posts = so._source_posts(
        {"platform": "threads", "source_type": "account", "source_value": "infomalangan", "replies": False}
    )
    assert [p.raw_data["kind"] for p in posts] == ["root"]


def test_skips_roots_without_replies_until_limit(monkeypatch):
    _reset(monkeypatch)
    monkeypatch.setattr(so, "THREADS_REPLIES_MAX_POSTS", 3)
    items = [
        _root_item(pid="1", url="https://www.threads.com/@a/post/P1", text="Posting tanpa balasan"),
        _root_item(pid="2", url="https://www.threads.com/@a/post/P2", text="Posting tanpa balasan 2"),
        _root_item(pid="3", url="https://www.threads.com/@a/post/P3", text="Posting ada balasan"),
    ]
    monkeypatch.setattr(so, "_fetch_threads_user_posts", lambda handle: items)
    monkeypatch.setattr(so, "_fetch_threads_replies", lambda url: [_reply_item()] if url.endswith("P3") else [])
    posts = so._source_posts(
        {"platform": "threads", "source_type": "account", "source_value": "a", "replies": True}
    )
    replies = [p for p in posts if p.raw_data["kind"] == "reply"]
    assert len(replies) == 1
    assert replies[0].raw_data["parent_post_id"] == "3"


def test_search_source_type_removed(monkeypatch):
    _reset(monkeypatch)
    monkeypatch.setattr(so, "_fetch_threads_user_posts", lambda handle: [_root_item()])
    posts = so._source_posts(
        {"platform": "threads", "source_type": "search", "source_value": "malang", "replies": False}
    )
    assert posts == []


def test_config_sources_have_no_threads_search():
    sources = so._load_sources()
    assert not any(s["platform"] == "threads" and s["source_type"] == "search" for s in sources)
    accounts = [s for s in sources if s["platform"] == "threads" and s["source_type"] == "account"]
    tags = [s for s in sources if s["platform"] == "threads" and s["source_type"] == "tag"]
    assert len(accounts) == 5 and all(s["replies"] for s in accounts)
    assert {s["source_value"] for s in tags} == {"malang", "karangploso malang"}


def test_config_has_no_instagram_hashtag():
    """Feed hashtag IG dihapus 6 Okt 2026: 5 credit/halaman, isinya bukan isu publik."""
    sources = so._load_sources()
    assert not any(s["platform"] == "instagram" and s["source_type"] == "hashtag" for s in sources)
    assert len([s for s in sources if s["platform"] == "instagram"]) == 3

def test_all_replies_emitted_when_limit_reached(monkeypatch):
    """Regresi: dulu loop output berhenti begitu jumlah induk ber-balasan mencapai batas → 0 balasan."""
    _reset(monkeypatch)
    monkeypatch.setattr(so, "THREADS_REPLIES_PER_ACCOUNT", 2)
    monkeypatch.setattr(so, "THREADS_REPLIES_MAX_POSTS", 4)
    items = [_root_item(pid=str(i), url=f"https://www.threads.com/@a/post/P{i}") for i in range(3)]
    monkeypatch.setattr(so, "_fetch_threads_user_posts", lambda handle: items)
    monkeypatch.setattr(so, "_fetch_threads_replies", lambda url: [_reply_item(pid="r" + url[-1])])
    posts = so._source_posts(
        {"platform": "threads", "source_type": "account", "source_value": "a", "replies": True}
    )
    replies = [p for p in posts if p.raw_data["kind"] == "reply"]
    assert len(replies) == 2  # tepat sebanyak batas per akun, bukan 0
    assert {r.raw_data["parent_post_id"] for r in replies} == {"0", "1"}


def _ig_root(pid="900", n_comments=7):
    return {
        "post": {
            "id": pid,
            "url": "https://www.instagram.com/malangraya_info/p/ABC/",
            "content": {"text": "Banjir di Sawojajar pagi ini"},
            "author": {"username": "malangraya_info"},
            "published_at": TODAY,
            "engagement": {"comments": n_comments},
        }
    }


def _ig_comment(cid, text="Iya di gang saya juga sudah selutut airnya"):
    return {"comment": {"id": cid, "text": text, "author": {"username": "warga"}, "published_at": TODAY}}


def test_fetch_top_comments_maps_to_reply_posts(monkeypatch):
    _reset(monkeypatch)
    monkeypatch.setattr(so, "IG_COMMENTS_TOP_N", 2)
    monkeypatch.setattr(
        so, "_fetch_ig_comments", lambda url: [_ig_comment("c1"), _ig_comment("c2", "👍"), _ig_comment("c3")]
    )
    parent = so._to_post(_ig_root(), "malangraya_info", "instagram")
    out = so.fetch_top_comments(parent)
    assert [p.platform_post_id for p in out] == ["c1", "c3"]  # emoji dibuang, maks TOP_N
    assert all(p.platform == "instagram" and p.raw_data["kind"] == "reply" for p in out)
    assert out[0].raw_data["parent_post_id"] == "900"
    assert out[0].url == parent.url  # komentar tanpa permalink → tautan ke induk


def test_fetch_top_comments_only_for_instagram(monkeypatch):
    _reset(monkeypatch)
    monkeypatch.setattr(so, "_fetch_ig_comments", lambda url: (_ for _ in ()).throw(AssertionError("tidak boleh dipanggil")))
    threads_parent = so._to_post(_root_item(), "infomalangan", "threads")
    assert so.fetch_top_comments(threads_parent) == []
