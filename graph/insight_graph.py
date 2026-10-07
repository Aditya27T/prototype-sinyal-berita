"""Insight graph — LangGraph serial: fetch_relevant → cluster_rule → merge_llm →
analyze_events → persist → draft_report.

Clustering awal berbasis aturan: satu event = (location, issue_hint, hari).
Balasan Threads ikut induknya lewat posts.parent_post_id agar satu utas =
satu unit event (Fase 2 roadmap; merge LLM menyusul).
"""
from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime
from pathlib import Path

import yaml
from langgraph.graph import END, StateGraph
from sqlalchemy import select
from sqlalchemy.orm import Session

from ai.insight import (
    MAX_SAMPLE_TEXTS,
    _class_from_texts,
    analyze_event,
    draft_report,
    insight_model_version,
    llm_merge_active,
    merge_events_llm,
)
from core.schemas import EventDraft
from database.models import Event, EventPost, PostAnalysis, PostRow, Report
from graph.state import WIB, InsightState, resolve_date

_STOPWORDS = {
    "yang", "dengan", "untuk", "dalam", "pada", "karena", "sudah", "masih", "akibat", "terjadi",
    "tersebut", "warga", "malang", "kota", "kabupaten", "jalan", "hingga", "setelah", "sebelum",
    "adalah", "menjadi", "saat", "sekitar", "pihak", "kepada", "dari", "atau", "juga", "tidak",
    "orang", "seorang", "salah", "sebuah", "melalui", "terlihat", "kondisi", "berita", "singkat",
    "senin", "selasa", "rabu", "kamis", "jumat", "sabtu", "minggu", "januari", "februari", "maret",
    "april", "juni", "juli", "agustus", "september", "oktober", "november", "desember",
    "kecamatan", "daerah", "kawasan", "wilayah",
}
# lokasi "payung" yang tidak menandai kejadian yang sama
_BROAD_LOCATIONS = {"malang", "kota malang", "malang kota", "malang raya", "kabupaten malang", "kab malang", "batu", "kota batu"}
_LOCATIONS_FILE = Path(__file__).resolve().parent.parent / "config" / "locations.yaml"
MIN_SHARED_TOKENS = 3  # token langka yang sama (mis. "veteran", "konvoi", "kemenangan")


def _seed_locations() -> set[str]:
    try:
        data = yaml.safe_load(_LOCATIONS_FILE.read_text()) or {}
        return {str(x).lower() for x in data.get("locations", [])}
    except Exception:  # noqa: BLE001 — tanpa config, semua lokasi dianggap tidak spesifik
        return set()


def _tokens(texts: list[str]) -> set[str]:
    """Kata ≥ 5 huruf, lowercase, tanpa stopword — penanda event (nama jalan, objek, kejadian)."""
    out: set[str] = set()
    for t in texts:
        for w in re.findall(r"[a-zA-Z]{5,}", t.lower()):
            if w not in _STOPWORDS:
                out.add(w)
    return out


def _norm_location(loc: str | None) -> str:
    return re.sub(r"[^a-z0-9 ]", "", (loc or "").lower()).strip()


def _is_specific(loc: str | None, seeds: set[str]) -> bool:
    """Lokasi spesifik = ada di seed (kecamatan/kawasan) dan bukan lokasi payung."""
    n = _norm_location(loc)
    return bool(n) and n not in _BROAD_LOCATIONS and n in seeds


def merge_similar(
    drafts: list[EventDraft], threshold: float = 0.25, text_rules: bool = True
) -> list[EventDraft]:
    """Gabungkan draft yang satu kelas isu + satu hari bila:
    - lokasinya sama dan spesifik (kecamatan/kawasan dari seed), kelas bukan "lainnya"; atau
    - teksnya mirip: Jaccard token ≥ threshold, atau ≥ MIN_SHARED_TOKENS token *langka*
      yang sama (langka = muncul di ≤ 20 % draft hari itu, jadi footer akun berita dan
      kata kelas seperti "kebakaran" tidak dihitung).
    Dua lokasi spesifik yang berbeda (Tajinan vs Pagelaran) tidak pernah digabung lewat teks.
    Merge berbasis LLM menyusul (roadmap Fase 2).
    """
    seeds = _seed_locations()
    tok = {id(d): _tokens(d.sample_texts) for d in drafts}
    df: dict[str, int] = {}
    for ts in tok.values():
        for t in ts:
            df[t] = df.get(t, 0) + 1
    rare_cap = 2  # token "langka" = muncul di ≤ 2 draft; kosakata umum berita pemkot tidak dihitung
    merged: list[EventDraft] = []
    merged_tok: dict[int, set[str]] = {}
    merged_class: dict[int, str] = {}  # kelas dibekukan saat grup dibuat (tidak ikut bergeser)
    for d in drafts:
        d_class = _class_from_texts(d)
        d_day = d.key.rsplit("|", 1)[-1]
        d_tok = tok[id(d)]
        d_specific = _is_specific(d.location, seeds)
        target = None
        for m in merged:
            if merged_class[id(m)] != d_class or m.key.rsplit("|", 1)[-1] != d_day:
                continue
            m_specific = _is_specific(m.location, seeds)
            same_loc = _norm_location(m.location) == _norm_location(d.location)
            if same_loc and d_specific and d_class != "lainnya":
                target = m
                break
            if d_specific and m_specific and not same_loc:
                continue  # dua kecamatan berbeda → kejadian berbeda, apa pun teksnya
            m_tok = merged_tok[id(m)]
            shared = d_tok & m_tok
            overlap = len(shared) / len(d_tok | m_tok) if (d_tok | m_tok) else 0.0
            rare_shared = {t for t in shared if df.get(t, 0) <= rare_cap}
            # "lainnya" = kelas tampung; hanya teks yang benar-benar mirip yang digabung
            token_match = len(rare_shared) >= MIN_SHARED_TOKENS and d_class != "lainnya"
            # lokasi yang disebut satu draft ("Jalan Veteran, Malang") muncul di teks draft lain
            d_loc_tok, m_loc_tok = _tokens([d.location or ""]), _tokens([m.location or ""])
            loc_mention = bool(d_loc_tok and d_loc_tok <= m_tok) or bool(m_loc_tok and m_loc_tok <= d_tok)
            # text_rules=False (LLM merge aktif): hanya duplikat nyata (Jaccard) yang digabung
            # di sini; penilaian konteks berita diserahkan ke merge_events_llm.
            if overlap >= threshold or (text_rules and (token_match or (loc_mention and d_class != "lainnya"))):
                target = m
                break
        if target is None:
            merged.append(d)
            merged_tok[id(d)] = set(d_tok)
            merged_class[id(d)] = d_class
            continue
        merged_tok[id(target)] |= d_tok
        target.post_ids.extend(pid for pid in d.post_ids if pid not in target.post_ids)
        for t in d.sample_texts:
            if len(target.sample_texts) < MAX_SAMPLE_TEXTS and t not in target.sample_texts:
                target.sample_texts.append(t)
        target.sources.extend(d.sources)
        # lokasi: utamakan yang spesifik (nama kecamatan/kawasan dari seed)
        if d.location and (not target.location or (d_specific and not _is_specific(target.location, seeds))):
            target.location = d.location
        if not target.issue_hint:
            target.issue_hint = d.issue_hint
    return merged


def _event_key(location: str | None, hint: str | None, day: str, post_ids: list[str]) -> str:
    """Key event: lokasi|hint|hari|hash posting — unik walau lokasi+hint sama (dua berita
    kebijakan Pemkot di hari yang sama adalah dua event)."""
    digest = hashlib.sha1(",".join(sorted(post_ids)).encode()).hexdigest()[:6]
    return f"{location or 'unknown'}|{hint or 'unknown'}|{day}|{digest}"


def cluster_rule(posts: list[dict]) -> list[EventDraft]:
    """Clustering berbasis aturan: satu utas (induk + balasan) = satu draft awal, lalu
    draft yang satu kejadian digabung oleh merge_similar (lokasi spesifik sama + kelas
    sama, teks mirip, atau lokasi yang disebut muncul di teks lain).

    Dulu pengelompokan awal memakai (location, issue_hint, hari); itu melebur berita yang
    berbeda bila LLM memberi hint generik yang sama ("kebijakan pemerintah daerah").

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

    by_id = {p["id"]: p for p in posts}
    groups: dict[str, EventDraft] = {}
    ordered = sorted(posts, key=lambda x: (x.get("kind") == "reply", str(x.get("published_at") or "")))
    for p in ordered:  # induk dulu, balasan menyusul ke grup induknya
        parent = by_id.get(p.get("parent_post_id") or "")
        root = parent if (p.get("kind") == "reply" and parent) else p
        day = _day(root)
        gkey = root["id"]
        draft = groups.get(gkey)
        if draft is None:
            draft = EventDraft(
                key=f"{root.get('location') or 'unknown'}|{root.get('issue_hint') or 'unknown'}|{day}",
                location=root.get("location") or None,
                issue_hint=root.get("issue_hint") or None,
            )
            groups[gkey] = draft
        draft.post_ids.append(p["id"])
        if len(draft.sample_texts) < MAX_SAMPLE_TEXTS:
            draft.sample_texts.append((p.get("text") or "").strip())
        if len(draft.sources) < 30:
            pub = p.get("published_at")
            draft.sources.append(
                {
                    "author": p.get("author"),
                    "platform": p.get("platform"),
                    "url": p.get("url"),
                    "text": (p.get("text") or "").strip()[:200],
                    "published_at": pub.isoformat() if isinstance(pub, datetime) else pub,
                    "kind": p.get("kind") or "root",
                }
            )
    merged = merge_similar(list(groups.values()), text_rules=not llm_merge_active())
    for d in merged:
        d.key = _event_key(d.location, d.issue_hint, d.key.rsplit("|", 1)[-1], d.post_ids)
    return merged


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

    def _as_dict(row: PostRow, an: PostAnalysis | None) -> dict:
        return {
            "id": row.id,
            "platform": row.platform,
            "text": row.text,
            "url": row.url,
            "author": row.author,
            "published_at": row.published_at,
            "location": an.location if an else None,
            "issue_hint": an.issue_hint if an else None,
            "kind": (row.raw_data or {}).get("kind", "root"),
            "parent_post_id": row.parent_post_id,
        }

    posts = []
    for row, an in rows:
        if row.published_at and row.published_at.astimezone(WIB).date().isoformat() != window:
            continue
        posts.append(_as_dict(row, an))
    by_id = {p["id"]: p for p in posts}

    # Balasan/komentar ikut event induknya walau tidak relevan sendiri (komentar
    # "iya di gang saya juga" tidak menyebut lokasi, tapi bagian dari utas yang relevan).
    root_ids = [p["id"] for p in posts if p["kind"] != "reply"]
    if root_ids:
        reply_rows = session.execute(
            select(PostRow, PostAnalysis)
            .outerjoin(PostAnalysis, PostAnalysis.post_id == PostRow.id)
            .where(PostRow.parent_post_id.in_(root_ids))
        ).all()
        for row, an in reply_rows:
            if row.id not in by_id:
                d = _as_dict(row, an)
                d["kind"] = "reply"
                posts.append(d)
                by_id[row.id] = d

    # balasan memakai location/issue_hint induk agar masuk cluster yang sama
    for p in posts:
        if p["kind"] == "reply" and p["parent_post_id"] in by_id:
            parent = by_id[p["parent_post_id"]]
            p["location"] = parent["location"] or p["location"]
            p["issue_hint"] = parent["issue_hint"] or p["issue_hint"]
    posts.sort(key=lambda x: str(x.get("published_at") or ""))
    return {"posts": posts}


def node_cluster_rule(state: InsightState) -> dict:
    window = state.get("window_date") or resolve_date("today")
    drafts = cluster_rule(state.get("posts", []))
    # pastikan key berisi tanggal window yang diminta
    fixed = [
        d.model_copy(update={"key": _event_key(d.location, d.issue_hint, window, d.post_ids)})
        for d in drafts
    ]
    return {"drafts": fixed}


def node_merge_llm(state: InsightState) -> dict:
    """LLM menyatukan kandidat yang satu konteks berita (lintas akun/platform, termasuk
    balasan yang sudah menempel di induknya). Key dibentuk ulang setelah merge."""
    window = state.get("window_date") or resolve_date("today")
    before = state.get("drafts", [])
    drafts = merge_events_llm(before)
    if len(drafts) != len(before):
        print(f"[graph] LLM merge: {len(before)} → {len(drafts)} event")
    return {
        "drafts": [
            d.model_copy(update={"key": _event_key(d.location, d.issue_hint, window, d.post_ids)})
            for d in drafts
        ]
    }


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
                "narrative": insight.model_dump(exclude={"issue_class", "urgency", "rationale"}),
                "post_ids": draft.post_ids,
                "sources": draft.sources,
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
            # run ulang (mis. heuristic → LLM) memperbarui isi event, bukan melewatinya
            existing.issue_class = ev.get("issue_class") or existing.issue_class
            existing.urgency = int(ev.get("urgency") or existing.urgency)
            existing.rationale = ev.get("rationale") or existing.rationale
            existing.narrative = ev.get("narrative") or existing.narrative
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
            narrative=ev.get("narrative"),
            window_date=window,
        )
        session.add(row)
        session.flush()
        ev["id"] = row.id
        for pid in ev["post_ids"]:
            session.add(EventPost(event_id=row.id, post_id=pid))
    # event lama di window ini yang tidak lagi dihasilkan (mis. tergabung oleh merge_similar)
    # dihapus, supaya daftar event = hasil clustering terbaru, bukan tumpukan run-run lama
    produced = {ev["key"] for ev in state.get("events", [])}
    stale = session.execute(
        select(Event).where(Event.window_date == window, Event.key.not_in(produced))
    ).scalars().all()
    for row in stale:
        session.delete(row)  # cascade ke event_posts
    if stale:
        print(f"[graph] {len(stale)} event lama di {window} dihapus (tergabung/berubah)")
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
                pub = p.get("published_at")
                sources.append(
                    {
                        "url": p.get("url"),
                        "text": p.get("text"),
                        "author": p.get("author"),
                        "platform": p.get("platform"),
                        "published_at": pub.isoformat() if isinstance(pub, datetime) else pub,
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
                "narrative": ev.get("narrative"),
                "post_ids": ev.get("post_ids", []),
                "sources": sources,
            }
        )
    period = "today" if window == resolve_date("today") else window
    body = draft_report(payload, period, window_date=window)
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
    g.add_node("merge_llm", node_merge_llm)
    g.add_node("analyze_events", node_analyze_events)
    g.add_node("persist", node_persist)
    g.add_node("draft_report", node_draft_report)
    g.set_entry_point("fetch_relevant")
    g.add_edge("fetch_relevant", "cluster_rule")
    g.add_edge("cluster_rule", "merge_llm")
    g.add_edge("merge_llm", "analyze_events")
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