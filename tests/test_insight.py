"""Test insight: cluster_rule + heuristic analyze_event + draft_report (tanpa LLM)."""
from datetime import datetime, timezone

from ai.insight import draft_report, heuristic_insight
from core.schemas import EventDraft
from graph.insight_graph import cluster_rule


def _p(**kw):
    base = {
        "id": "x",
        "text": "teks",
        "url": "https://threads.com/@a/post/1",
        "author": "a",
        "published_at": datetime(2026, 10, 6, 5, 0, tzinfo=timezone.utc),
        "location": None,
        "issue_hint": None,
        "kind": "root",
        "parent_post_id": None,
    }
    base.update(kw)
    return base


def test_cluster_groups_by_location_hint_day():
    posts = [
        _p(id="a1", location="Suhat", issue_hint="listrik"),
        _p(id="a2", location="Suhat", issue_hint="listrik", author="warga", kind="reply"),
        _p(id="b1", location="Tajinan", issue_hint="kebakaran"),
    ]
    drafts = cluster_rule(posts)
    assert len(drafts) == 2
    suhat = next(d for d in drafts if d.location == "Suhat")
    assert set(suhat.post_ids) == {"a1", "a2"}
    assert suhat.key == "Suhat|listrik|2026-10-06"


def test_cluster_separates_different_day():
    d1 = datetime(2026, 10, 6, 5, 0, tzinfo=timezone.utc)
    d2 = datetime(2026, 10, 5, 5, 0, tzinfo=timezone.utc)
    drafts = cluster_rule(
        [_p(id="a1", location="Suhat", issue_hint="listrik", published_at=d1),
         _p(id="b1", location="Suhat", issue_hint="listrik", published_at=d2)]
    )
    assert len(drafts) == 2


def test_cluster_caps_sample_texts_at_five():
    posts = [_p(id=f"p{i}", location="Suhat", issue_hint="listrik", text=f"teks {i}") for i in range(8)]
    drafts = cluster_rule(posts)
    assert len(drafts[0].post_ids) == 8
    assert len(drafts[0].sample_texts) == 5


def test_heuristic_issue_class_from_hint_and_urgency_from_count():
    ev = EventDraft(key="k", location="Suhat", issue_hint="listrik", post_ids=["a", "b", "c", "d"])
    ins = heuristic_insight(ev)
    assert ins.issue_class == "listrik_dan_air"
    assert ins.urgency == 2  # min(5, 1 + 4//3)

    many = EventDraft(key="k", location="Suhat", issue_hint="banjir", post_ids=list("abcdefghij"))
    assert heuristic_insight(many).urgency == 4


def test_heuristic_class_falls_back_to_text_then_lainnya():
    ev = EventDraft(key="k", issue_hint=None, post_ids=["a"], sample_texts=["Genangan air di gang"])
    assert heuristic_insight(ev).issue_class == "banjir"
    ev2 = EventDraft(key="k", issue_hint=None, post_ids=["a"], sample_texts=["Promo kopi diskon"])
    assert heuristic_insight(ev2).issue_class == "lainnya"


def test_analyze_event_never_touches_llm_when_provider_heuristic(monkeypatch):
    from ai import insight

    monkeypatch.setenv("AI_PROVIDER", "heuristic")
    ev = EventDraft(key="k", location="Suhat", issue_hint="listrik", post_ids=["a"])
    assert insight.analyze_event(ev).issue_class == "listrik_dan_air"
    assert insight.insight_model_version() == insight.HEURISTIC_VERSION


def test_draft_report_contains_event_and_sources():
    events = [
        {
            "key": "Suhat|listrik|2026-10-06",
            "location": "Suhat",
            "issue_class": "listrik_dan_air",
            "urgency": 3,
            "rationale": "listrik mati sejak pagi",
            "post_ids": ["a"],
            "sources": [
                {
                    "url": "https://threads.com/@a/post/1",
                    "text": "listrik mati",
                    "author": "warga",
                    "kind": "reply",
                }
            ],
        }
    ]
    md = draft_report(events, "today")
    assert "# Laporan isu publik Malang Raya" in md
    assert "Suhat" in md
    assert "listrik_dan_air" in md
    assert "[3/5]" in md
    assert "(balasan)" in md
    assert "https://threads.com/@a/post/1" in md