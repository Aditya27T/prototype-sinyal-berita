"""FastAPI — milik Person 3 (PLAN: endpoint baca relevant posts)."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import desc, select

load_dotenv()

from database.connection import get_session_factory, init_db  # noqa: E402
from database.models import PostAnalysis, PostRow  # noqa: E402

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
                }
            )
        return out
