"""Insight graph — LangGraph serial: fetch_relevant → cluster_rule →
analyze_events → persist → draft_report.

Clustering awal berbasis aturan: satu event = (location, issue_hint, hari).
Balasan Threads ikut induknya lewat posts.parent_post_id agar satu utas =
satu unit event (Fase 2 roadmap; merge LLM menyusul).
"""
from __future__ import annotations

import os
from datetime import datetime

from langgraph.graph import END, StateGraph
from sqlalchemy import select
from sqlalchemy.orm import Session

from ai.insight import MAX_SAMPLE_TEXTS, analyze_event, draft_report, insight_model_version
from core.schemas import EventDraft
from database.models import Event, EventPost, PostAnalysis, PostRow, Report
from graph.state import WIB, InsightState, resolve_date


def cluster_rule(posts: list[dict]) -> list[EventDraft]:
    """Group posting relevan per (location, issue_hint, hari) → EventDraft.

    `posts` = dict hasil fetch_relevant: id, text, url, author, published_at,
    location, issue_hint, kind, parent_post_id.
    """

    def _day(p: dict) -> str:
        dt = p.get("published_at")
        if isinstance(dt, datetime):
            return dt.astimezone(WIB).date().isoformat()
        if isinstance(dt, str):
            return dt[:10]
        return "unknown"

    groups: dict[str, EventDraft] = {}
    for p in sorted(posts, key=lambda x: str(x.get("published_at") or "")):
        loc = p.get("location") or None
        hint = p.get("issue_hint") or None
        key = f"{loc or 'unknown'}|{hint or 'unknown'}|{_day(p)}"
        draft = groups.get(key)
        if draft is None:
            draft = EventDraft(key=key, location=loc, issue_hint=hint)
            groups[key] = draft
        draft.post_ids.append(p["id"])
        if len(draft.sample_texts) < MAX_SAMPLE_TEXTS:
            draft.sample_texts.append((p.get("text") or "").strip())
    return list(groups.values())


def fetch_relevant(state: InsightState) -> dict:
    """Ambil posting relevan dari DB; balasan ikutppmbawa sebagai terpisah."""
    session: Session = state["session"]
    window = state.get("window_date") or resolve_date("today")
    min_score = float(state.get("min_score", 0.0))
    stmt = (
        select(PostRow, PostAnalysis)
        .join(PostAnalysis, PostAnalysis.post_id == PostRow.id)
        .where(PostAnalysis.is_relevant.is_(True), PostAnalysis.relevance_score >= min_score)
    )
    rows = session.execute(stmt).all()
    posts = []
    for row, an in rows:
        if row.published_at and row.published_at.astimezone(WIB).date().isoformat() != window:
            continue
        posts.append(
            {
                "id": row.id,
                "platform": row.platform,
                "text": row.text,
                "url": row.url,
                "author": row.author,
                "published_at": row.published_at,
                "location": an.location,
                "issue_hint": an.issue_hint,
                "kind": (row.raw_data or {}).get("kind", "root"),
                "parent_post_id": row.parent_post_id,
            }
        )
    # balasan tetap ikut event induknya: samakan location/issue_hint dengan induk
    by_id = {p["id"]: p for p in posts}
    for p in posts:
        if p["kind"] == "reply" and p["parent_post_id"] in by_id:
            parent = by_id[p["parent_post_id"]]
            p["location"] = p["location"] or parent["location"]
            p["issue_hint"] = p["issue_hint"] or parent["issue_hint"]
    posts.sort(key=lambda x: str(x.get("published_at") or ""))
    return {"posts": posts}


def node_cluster_rule(state: InsightState) -> dict:
    window = state.get("window_date") or resolve_date("today")
    drafts = cluster_rule(state.get("posts", []))
    # pastikan key berisi tanggal window yang diminta
    fixed = []
    for d in drafts:
        if not d.key.endswith(window):
            loc, hint, _ = d.key.split("|", 2)
            d = d.model_copy(update={"key": f"{loc}|{hint}|{window}"})
        fixed.append(d)
    return {"drafts": fixed}


def node_analyze_events(state: InsightState) -> dict:
    """Satu panggilan LLM (atau heuristic) per event → issue_class + urgency."""
    version = insight_model_version()
    out = []
    for draft in state.get("drafts", []):
        insight = analyze_event(draft)
        out.append(
            {
                "key": draft.key,
                "location": draft.location,
                "issue_hint": draft.issue_hint,
                "issue_class": insight.issue_class,
                "urgency": insight.urgency,
                "rationale": insight.rationale,
                "post_ids": draft.post_ids,
                "model_version": version,
            }
        )
    return {"events": out, "model_version": version}


def node_persist(state: InsightState) -> dict:
    """Tulis event + event_posts (idempoten per key+window)."""
    session: Session = state["session"]
    window = state.get("window_date") or resolve_date("today")
    for ev in state.get("events", []):
        existing = session.execute(
            select(Event).where(Event.key == ev["key"], Event.window_date == window)
        ).scalar_one_or_none()
        if existing:
            ev["id"] = existing.id
            for pid in ev["post_ids"]:
                ep = session.execute(
                    select(EventPost).where(
                        EventPost.event_id == existing.id, EventPost.post_id == pid
                    )
                ).scalar_one_or_none()
                if not ep:
                    session.add(EventPost(event_id=existing.id, post_id=pid))
            continue
        row = Event(
            key=ev["key"],
            location=ev.get("location"),
            issue_class=ev.get("issue_class") or "lainnya",
            urgency=int(ev.get("urgency") or 1),
            rationale=ev.get("rationale"),
            window_date=window,
        )
        session.add(row)
        session.flush()
        ev["id"] = row.id
        for pid in ev["post_ids"]:
            session.add(EventPost(event_id=row.id, post_id=pid))
    session.commit()
    return {}


def node_draft_report(state: InsightState) -> dict:
    """Buat draf laporan dari event yang ter-persist; simpan status draft."""
    session: Session = state["session"]
    window = state.get("window_date") or resolve_date("today")
    events = state.get("events", [])
    posts_by_id = {p["id"]: p for p in state.get("posts", [])}
    payload = []
    for ev in events:
        sources = []
        for pid in ev.get("post_ids", []):
            p = posts_by_id.get(pid)
            if p:
                sources.append(
                    {
                        "url": p.get("url"),
                        "text": p.get("text"),
                        "author": p.get("author"),
                        "kind": p.get("kind"),
                    }
                )
        payload.append(
            {
                "key": ev["key"],
                "location": ev.get("location"),
                "issue_class": ev.get("issue_class"),
                "urgency": ev.get("urgency"),
                "rationale": ev.get("rationale"),
                "post_ids": ev.get("post_ids", []),
                "sources": sources,
            }
        )
    period = "today" if window == resolve_date("today") else window
    body = draft_report(payload, period)
    report = session.execute(
        select(Report).where(Report.period == window, Report.status == "draft")
    ).scalar_one_or_none()
    if report:
        report.body_md = body
    else:
        report = Report(period=window, body_md=body, status="draft")
        session.add(report)
    session.commit()
    return {"report_id": report.id, "report_period": period}


def build_graph():
    g = StateGraph(InsightState)
    g.add_node("fetch_relevant", fetch_relevant)
    g.add_node("cluster_rule", node_cluster_rule)
    g.add_node("analyze_events", node_analyze_events)
    g.add_node("persist", node_persist)
    g.add_node("draft_report", node_draft_report)
    g.set_entry_point("fetch_relevant")
    g.add_edge("fetch_relevant", "cluster_rule")
    g.add_edge("cluster_rule", "analyze_events")
    g.add_edge("analyze_events", "persist")
    g.add_edge("persist", "draft_report")
    g.add_edge("draft_report", END)
    return g.compile()


def run_insight(session: Session, window: str | None = None, min_score: float = 0.0) -> dict:
    """Jalankan insight graph pada data yang sudah ada di DB."""
    window_date = resolve_date(window or "today")
    state: InsightState = {
        "window_date": window_date,
        "min_score": float(os.getenv("INSIGHT_MIN_SCORE", str(min_score))),
        "session": session,
        "report_period": "today" if window_date == resolve_date("today") else window_date,
    }
    graph = build_graph()
    final = graph.invoke(state)
    events = session.execute(
        select(Event).where(Event.window_date == final.get("window_date", window_date))
    ).scalars().all()
    return {
        "window_date": final.get("window_date"),
        "events": len(events),
        "report_id": final.get("report_id"),
        "report_period": final.get("report_period"),
        "model_version": final.get("model_version"),
    }