"""Kontrak data bersama — disepakati bertiga (PLAN §3).
Perubahan di file ini harus disepakati Person 1/2/3.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Post(BaseModel):
    """Keluaran Person 1, masukan Person 2 (PLAN §3.1)."""

    id: UUID = Field(default_factory=uuid4)
    platform: str = Field(..., min_length=1, description="wajib, mis. 'threads'")
    platform_post_id: Optional[str] = None
    url: Optional[str] = None
    text: str = Field(..., min_length=1, description="wajib")
    author: Optional[str] = None
    published_at: Optional[datetime] = None
    collected_at: datetime = Field(default_factory=utcnow)
    source_query: Optional[str] = None
    raw_data: dict[str, Any] = Field(default_factory=dict)

    @field_validator("text")
    @classmethod
    def text_must_not_be_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("text wajib diisi")
        return v


class AnalysisResult(BaseModel):
    """Keluaran Person 2 (PLAN §3.2)."""

    is_relevant: bool
    relevance_score: float = Field(..., ge=0.0, le=1.0)
    location: Optional[str] = None
    location_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    issue_hint: Optional[str] = None
    reason: Optional[str] = None


class EventDraft(BaseModel):
    """Hasil clustering — satu unit event dari kumpulan posting relevan."""

    key: str = Field(..., min_length=1, description='f"{location}|{issue_hint}|{date}"')
    location: Optional[str] = None
    issue_hint: Optional[str] = None
    post_ids: list[str] = Field(default_factory=list)
    sample_texts: list[str] = Field(default_factory=list, description="maks 5 teks untuk LLM")
    # {author, platform, url, published_at (ISO), kind} — bahan "Eksposur Media Sosial"
    sources: list[dict[str, Any]] = Field(default_factory=list)


class EventInsight(BaseModel):
    """Isu + urgency + narasi laporan satu event — satu panggilan LLM mengisi semuanya.

    Field narasi mengikuti format docs/contohlaporan.md; None bila LLM tidak
    mengisi (heuristic akan melengkapi dengan template).
    """

    issue_class: str = Field(..., min_length=1, description="dari daftar 12 kelas di prompt")
    urgency: int = Field(..., ge=1, le=5)
    rationale: str = Field(..., min_length=1)
    title: Optional[str] = None  # judul singkat, mis. "Kecelakaan Lalu Lintas di Jalan Veteran"
    occurred_at: Optional[str] = None  # waktu kejadian dalam teks, hanya bila ada di posting
    summary: Optional[str] = None  # Ringkasan Isu (2–4 kalimat)
    exposure: Optional[str] = None  # Eksposur Media Sosial (dihitung dari sources)
    sentiment: Optional[str] = None  # negatif | netral | positif
    attention_level: Optional[str] = None  # rendah | sedang | tinggi
    issue_character: Optional[str] = None  # mis. "Insidental / kejadian lokal"
    potential: Optional[str] = None  # Potensi Isu
    recommendation: Optional[str] = None  # Rekomendasi (tidak ikut ke PDF)
    status: Optional[str] = None  # monitor | prioritas | selesai
