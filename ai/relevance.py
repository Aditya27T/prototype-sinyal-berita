"""Relevance filter — milik Person 2. Kontrak: analyze(post) -> AnalysisResult."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import yaml

from core.schemas import AnalysisResult, Post

PROMPT_FILE = Path(__file__).resolve().parent / "prompts" / "relevance.txt"
LOCATIONS_FILE = (
    Path(__file__).resolve().parent.parent / "config" / "locations.yaml"
)

COMMERCIAL_RE = re.compile(
    r"\b(kos|kontrakan|dijual|disewakan|promo|diskon|hubungi|wa\b|whatsapp|murah|order|jualan|jual|beli|harga|dp|cicilan)\b",
    re.IGNORECASE,
)
MODEL_VERSION = os.getenv("AI_MODEL_VERSION", "heuristic-0.1")


def _locations() -> list[str]:
    try:
        data = yaml.safe_load(LOCATIONS_FILE.read_text()) or {}
        locs = data.get("locations", [])
        return [str(x) for x in locs]
    except Exception:
        return ["Sawojajar", "Dinoyo", "Suhat", "Batu", "Kepanjen"]


def _heuristic(post: Post) -> AnalysisResult:
    """Fallback tanpa LLM agar pipeline Person 3 tetap demo. Person 2 ganti dengan LLM."""
    text = post.text or ""
    low = text.lower()
    locs = _locations()
    found = next((l for l in locs if l.lower() in low), None)
    is_commercial = bool(COMMERCIAL_RE.search(text))
    issue_hint = None
    for kw in ["banjir", "macet", "genangan", "jalan rusak", "longsor", "kebakaran", "sampah", "lampu mati", "air mati"]:
        if kw in low:
            issue_hint = kw
            break
    is_relevant = bool(found and issue_hint and not is_commercial)
    score = 0.9 if is_relevant else (0.2 if found else 0.05)
    if is_commercial:
        score = min(score, 0.15)
    return AnalysisResult(
        is_relevant=is_relevant,
        relevance_score=score,
        location=found if (found and not is_commercial) else (found if found else None),
        location_confidence=0.85 if found else 0.0,
        issue_hint=None if is_commercial else issue_hint,
        reason=(
            f"Heuristic {MODEL_VERSION}: "
            + ("komersial → not relevant" if is_commercial else (f"lokasi={found} isu={issue_hint}" if is_relevant else "tidak memenuhi Malang Raya + isu publik"))
        ),
    )


def analyze(post: Post) -> AnalysisResult:
    """TODO(Person 2): panggil LLM sesuai ai/prompts/relevance.txt, validasi JSON.

    Untuk sekarang pakai heuristic + hook OpenAI bila OPENAI_API_KEY ada
    (implementasi penuh milik Person 2).
    """
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        return _heuristic(post)
    # Stub integrasi LLM — Person 2 lengkapi (timeout, JSON validation).
    # Sengaja tetap heuristic agar tak merusak demo bila API gagal.
    try:
        from openai import OpenAI  # type: ignore

        prompt = PROMPT_FILE.read_text() if PROMPT_FILE.exists() else "{text}"
        client = OpenAI(api_key=api_key)
        model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt.replace("{text}", post.text)}],
            response_format={"type": "json_object"},
            timeout=20,
        )
        data = json.loads(resp.choices[0].message.content or "{}")
        return AnalysisResult(**data)
    except Exception as e:
        r = _heuristic(post)
        r.reason = f"{r.reason} (llm-fallback: {e})"
        return r
