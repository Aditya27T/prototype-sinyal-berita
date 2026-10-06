"""SQLAlchemy models — milik Person 3 (PLAN §Person 3.1)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
import uuid


class Base(DeclarativeBase):
    pass


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    platform: Mapped[str] = mapped_column(String(50), nullable=False)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    source_value: Mapped[str] = mapped_column(String(500), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    posts: Mapped[list["PostRow"]] = relationship(back_populates="source")


class PostRow(Base):
    __tablename__ = "posts"
    __table_args__ = (UniqueConstraint("platform", "platform_post_id", name="uq_posts_platform_postid"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    source_id: Mapped[str | None] = mapped_column(ForeignKey("sources.id"), nullable=True)
    platform: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    platform_post_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    author: Mapped[str | None] = mapped_column(String(200), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    raw_data: Mapped[dict] = mapped_column(JSON, default=dict)
    parent_post_id: Mapped[str | None] = mapped_column(ForeignKey("posts.id"), nullable=True, index=True)

    source: Mapped[Source | None] = relationship(back_populates="posts")
    analysis: Mapped["PostAnalysis | None"] = relationship(back_populates="post", uselist=False, cascade="all, delete-orphan")


class PostAnalysis(Base):
    __tablename__ = "post_analysis"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    post_id: Mapped[str] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"), unique=True, nullable=False)
    is_relevant: Mapped[bool] = mapped_column(Boolean, nullable=False, index=True)
    relevance_score: Mapped[float] = mapped_column(Float, nullable=False)
    location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    location_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    issue_hint: Mapped[str | None] = mapped_column(String(200), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_version: Mapped[str] = mapped_column(String(100), default="heuristic-0.1")
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    post: Mapped[PostRow] = relationship(back_populates="analysis")


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (UniqueConstraint("key", "window_date", name="uq_events_key_window"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    key: Mapped[str] = mapped_column(String(500), nullable=False)
    location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    issue_class: Mapped[str] = mapped_column(String(100), nullable=False, default="lainnya")
    urgency: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    window_date: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    event_posts: Mapped[list["EventPost"]] = relationship(
        back_populates="event", cascade="all, delete-orphan"
    )


class EventPost(Base):
    __tablename__ = "event_posts"
    __table_args__ = (UniqueConstraint("event_id", "post_id", name="uq_event_posts_event_post"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), nullable=False)
    post_id: Mapped[str] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"), nullable=False)

    event: Mapped[Event] = relationship(back_populates="event_posts")
    post: Mapped[PostRow] = relationship()


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    period: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    body_md: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
