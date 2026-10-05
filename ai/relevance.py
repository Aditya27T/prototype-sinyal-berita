"""Relevance filter — milik Person 2. Kontrak: analyze(post) -> AnalysisResult."""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

import httpx
import yaml
from dotenv import load_dotenv

from core.schemas import AnalysisResult, Post

load_dotenv()

PROMPT_FILE = Path(__file__).resolve().parent / "prompts" / "relevance.txt"
LOCATIONS_FILE = (
    Path(__file__).resolve().parent.parent / "config" / "locations.yaml"
)

COMMERCIAL_RE = re.compile(
    r"\b(kos|kontrakan|dijual|disewakan|promo|diskon|hubungi|wa\b|whatsapp|murah|order|jualan|jual|beli|harga|dp|cicilan)\b",
    re.IGNORECASE,
)
MODEL_VERSION = os.getenv("AI_MODEL_VERSION", "heuristic-0.1")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
GEMINI_TIMEOUT = float(os.getenv("GEMINI_TIMEOUT", "30"))

_ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "is_relevant": {"type": "boolean"},
        "relevance_score": {"type": "number"},
        "location": {"type": "string", "nullable": True},
        "location_confidence": {"type": "number"},
        "issue_hint": {"type": "string", "nullable": True},
        "reason": {"type": "string", "nullable": True},
    },
    "required": ["is_relevant", "relevance_score", "location_confidence"],
}


def provider() -> str:
    """Provider aktif: explicit AI_PROVIDER, atau gemini bila ada key, else heuristic."""
    forced = os.getenv("AI_PROVIDER", "").strip().lower()
    if forced:
        return forced
    if os.getenv("GEMINI_API_KEY", "").strip():
        return "gemini"
    return "heuristic"


def _locations() -> list[str]:
    try:
        data = yaml.safe_load(LOCATIONS_FILE.read_text()) or {}
        locs = data.get("locations", [])
        return [str(x) for x in locs]
    except Exception:
        return ["Sawojajar", "Dinoyo", "Suhat", "Batu", "Kepanjen"]


def _prompt_for(text: str) -> str:
    template = PROMPT_FILE.read_text(encoding="utf-8") if PROMPT_FILE.exists() else "{text}"
    return template.replace("{text}", text).replace("{locations}", ", ".join(_locations()))


def _heuristic(post: Post) -> AnalysisResult:
    """Fallback tanpa LLM agar pipeline tetap demo bila API gagal / tanpa key."""
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


def _analyze_gemini(post: Post) -> AnalysisResult:
    """Panggil Gemini (JSON mode + responseSchema). Raise bila gagal → fallback heuristic."""
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY kosong")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
    payload = {
        "contents": [{"parts": [{"text": _prompt_for(post.text)}]}],
        "generationConfig": {
            "temperature": 0.0,
            "maxOutputTokens": 1024,
            "responseMimeType": "application/json",
            "responseSchema": _ANALYSIS_SCHEMA,
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }
    last_err: Exception | None = None
    for attempt in (1, 2, 3):
        try:
            with httpx.Client(timeout=GEMINI_TIMEOUT) as client:
                resp = client.post(url, headers={"x-goog-api-key": api_key}, json=payload)
                resp.raise_for_status()
                body = resp.json()
            text = body["candidates"][0]["content"]["parts"][0]["text"]
            return AnalysisResult(**json.loads(text))
        except Exception as e:
            last_err = e
            status = getattr(getattr(e, "response", None), "status_code", None)
            if status in (429, 503) and attempt < 3:
                time.sleep(5 * attempt)  # free-tier throttle: 5s, 10s
                continue
            break
    raise RuntimeError(f"gemini gagal: {last_err}")


def analyze(post: Post) -> AnalysisResult:
    """Kontrak Person 2. Provider LLM bila key ada; fallback heuristic bila gagal."""
    if provider() == "gemini":
        try:
            result = _analyze_gemini(post)
            return result
        except Exception as e:
            r = _heuristic(post)
            r.reason = f"{r.reason} (llm-fallback: {e})"
            return r
    return _heuristic(post)


def model_version() -> str:
    return f"gemini:{GEMINI_MODEL}" if provider() == "gemini" else MODEL_VERSION
