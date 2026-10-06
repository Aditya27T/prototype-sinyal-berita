"""FastAPI — milik Person 3 (PLAN: endpoint baca relevant posts)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import desc, select

load_dotenv()

from database.connection import get_session_factory, init_db  # noqa: E402
from database.models import Event, EventPost, PostAnalysis, PostRow, Report  # noqa: E402

app = FastAPI(title="Telinga Digital — Signyal Prototype", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class RelevantPostOut(BaseModel):
    id: str
    platform: str
    platform_post_id: Optional[str] = None
    url: Optional[str] = None
    text: str
    author: Optional[str] = None
    published_at: Optional[datetime] = None
    relevance_score: float
    location: Optional[str] = None
    location_confidence: float = 0.0
    issue_hint: Optional[str] = None
    reason: Optional[str] = None


@app.on_event("startup")
def _startup() -> None:
    init_db()


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.get("/posts/relevant", response_model=list[RelevantPostOut])
def list_relevant(
    limit: int = Query(50, ge=1, le=200),
    location: Optional[str] = None,
    min_score: float = Query(0.0, ge=0.0, le=1.0),
) -> list[RelevantPostOut]:
    SessionLocal = get_session_factory()
    with SessionLocal() as s:
        stmt = (
            select(PostRow, PostAnalysis)
            .join(PostAnalysis, PostAnalysis.post_id == PostRow.id)
            .where(PostAnalysis.is_relevant.is_(True))
            .where(PostAnalysis.relevance_score >= min_score)
            .order_by(desc(PostAnalysis.relevance_score))
            .limit(limit)
        )
        if location:
            stmt = stmt.where(PostAnalysis.location.ilike(f"%{location}%"))
        rows = s.execute(stmt).all()
        return [
            RelevantPostOut(
                id=r.id,
                platform=r.platform,
                platform_post_id=r.platform_post_id,
                url=r.url,
                text=r.text,
                author=r.author,
                published_at=r.published_at,
                relevance_score=a.relevance_score,
                location=a.location,
                location_confidence=a.location_confidence,
                issue_hint=a.issue_hint,
                reason=a.reason,
            )
            for r, a in rows
        ]


@app.get("/posts/all")
def list_all(limit: int = Query(50, ge=1, le=200)) -> list[dict]:
    """Debug: semua posts + flag relevant (bantu Person 2 spot-check)."""
    SessionLocal = get_session_factory()
    with SessionLocal() as s:
        stmt = (
            select(PostRow, PostAnalysis)
            .outerjoin(PostAnalysis, PostAnalysis.post_id == PostRow.id)
            .order_by(desc(PostRow.collected_at))
            .limit(limit)
        )
        out = []
        for r, a in s.execute(stmt).all():
            out.append(
                {
                    "id": r.id,
                    "platform": r.platform,
                    "url": r.url,
                    "text": r.text,
                    "author": r.author,
                    "published_at": r.published_at,
                    "collected_at": r.collected_at,
                    "is_relevant": a.is_relevant if a else None,
                    "relevance_score": a.relevance_score if a else None,
                    "location": a.location if a else None,
                    "issue_hint": a.issue_hint if a else None,
                    "reason": a.reason if a else None,
                    "kind": (r.raw_data or {}).get("kind", "root"),
                    "topic_tag": (r.raw_data or {}).get("topic_tag"),
                    "parent_post_id": r.parent_post_id,
                    "parent_url": (r.raw_data or {}).get("parent_url"),
                }
            )
        return out


# --- Event & laporan (insight graph) ---------------------------------------


class EventPostOut(BaseModel):
    id: str
    platform: str
    text: str
    url: Optional[str] = None
    author: Optional[str] = None
    published_at: Optional[datetime] = None
    kind: str = "root"
    parent_url: Optional[str] = None
    topic_tag: Optional[str] = None


class EventOut(BaseModel):
    id: str
    key: str
    location: Optional[str] = None
    issue_class: str
    urgency: int
    rationale: Optional[str] = None
    window_date: str
    created_at: Optional[datetime] = None
    post_count: int = 0
    posts: list[EventPostOut] = []


class ReportOut(BaseModel):
    id: str
    period: str
    status: str
    body_md: str
    created_at: Optional[datetime] = None
    approved_at: Optional[datetime] = None
    event_count: Optional[int] = None


def _event_payload(s, event: Event, with_posts: bool) -> dict:
    rows = (
        s.execute(
            select(PostRow)
            .join(EventPost, EventPost.post_id == PostRow.id)
            .where(EventPost.event_id == event.id)
            .order_by(desc(PostRow.published_at))
        )
        .scalars()
        .all()
    )
    posts = []
    for r in rows:
        raw = r.raw_data or {}
        posts.append(
            EventPostOut(
                id=r.id,
                platform=r.platform,
                text=r.text,
                url=r.url,
                author=r.author,
                published_at=r.published_at,
                kind=raw.get("kind", "root"),
                parent_url=raw.get("parent_url"),
                topic_tag=raw.get("topic_tag"),
            )
        )
    return {
        "id": event.id,
        "key": event.key,
        "location": event.location,
        "issue_class": event.issue_class,
        "urgency": event.urgency,
        "rationale": event.rationale,
        "window_date": event.window_date,
        "created_at": event.created_at,
        "post_count": len(posts),
        "posts": posts if with_posts else [],
    }


@app.get("/events", response_model=list[EventOut])
def list_events(
    date_: Optional[str] = Query(None, alias="date"),
    min_urgency: int = Query(1, ge=1, le=5),
    limit: int = Query(50, ge=1, le=200),
) -> list[dict]:
    """Event dari insight graph, urut urgency tertinggi."""
    SessionLocal = get_session_factory()
    with SessionLocal() as s:
        stmt = select(Event).where(Event.urgency >= min_urgency)
        if date_:
            stmt = stmt.where(Event.window_date == date_)
        stmt = stmt.order_by(desc(Event.urgency), desc(Event.created_at)).limit(limit)
        return [_event_payload(s, e, with_posts=True) for e in s.execute(stmt).scalars().all()]


@app.get("/events/{event_id}", response_model=EventOut)
def get_event(event_id: str) -> dict:
    SessionLocal = get_session_factory()
    with SessionLocal() as s:
        event = s.get(Event, event_id)
        if not event:
            raise HTTPException(status_code=404, detail="event tidak ditemukan")
        return _event_payload(s, event, with_posts=True)


def _report_payload(report: Report, event_count: int | None = None) -> dict:
    return {
        "id": report.id,
        "period": report.period,
        "status": report.status,
        "body_md": report.body_md,
        "created_at": report.created_at,
        "approved_at": report.approved_at,
        "event_count": event_count,
    }


@app.get("/reports", response_model=list[ReportOut])
def list_reports(
    status: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
) -> list[dict]:
    SessionLocal = get_session_factory()
    with SessionLocal() as s:
        stmt = select(Report).order_by(desc(Report.period), desc(Report.created_at)).limit(limit)
        if status:
            stmt = stmt.where(Report.status == status)
        out = []
        for r in s.execute(stmt).scalars().all():
            n = s.execute(
                select(Event).where(Event.window_date == r.period)
            ).scalars().all()
            out.append(_report_payload(r, len(n)))
        return out


@app.get("/reports/{report_id}", response_model=ReportOut)
def get_report(report_id: str) -> dict:
    SessionLocal = get_session_factory()
    with SessionLocal() as s:
        report = s.get(Report, report_id)
        if not report:
            raise HTTPException(status_code=404, detail="laporan tidak ditemukan")
        n = s.execute(select(Event).where(Event.window_date == report.period)).scalars().all()
        return _report_payload(report, len(n))


@app.post("/reports/{report_id}/approve", response_model=ReportOut)
def approve_report(report_id: str) -> dict:
    """Operator menyetujui draf → status approved + approved_at."""
    SessionLocal = get_session_factory()
    with SessionLocal() as s:
        report = s.get(Report, report_id)
        if not report:
            raise HTTPException(status_code=404, detail="laporan tidak ditemukan")
        report.status = "approved"
        report.approved_at = datetime.now(timezone.utc)
        s.commit()
        s.refresh(report)
        n = s.execute(select(Event).where(Event.window_date == report.period)).scalars().all()
        return _report_payload(report, len(n))
