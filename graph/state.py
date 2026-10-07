"""State LangGraph untuk insight graph."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Annotated, TypedDict
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from core.schemas import EventDraft

WIB = ZoneInfo("Asia/Jakarta")


def _merge_lists(a: list, b: list) -> list:
    """Reducer: gabung daftar tanpa duplikat (dipakai antar-node)."""
    out = list(a or [])
    for item in b or []:
        if item not in out:
            out.append(item)
    return out


class InsightState(TypedDict, total=False):
    """State yang mengalir antar node insight graph."""

    window_date: str
    min_score: float
    posts: Annotated[list[dict], _merge_lists]
    drafts: list[EventDraft]  # ditimpa tiap node (cluster_rule → merge_llm), bukan digabung
    events: Annotated[list[dict], _merge_lists]
    report_id: str
    report_period: str
    session: Session
    model_version: str


def resolve_date(value: str | None) -> str:
    """"today" / "yesterday" / "YYYY-MM-DD" → tanggal ISO (WIB)."""
    today = datetime.now(WIB).date()
    if not value or value == "today":
        return today.isoformat()
    if value == "yesterday":
        return (today - timedelta(days=1)).isoformat()
    return date.fromisoformat(value).isoformat()