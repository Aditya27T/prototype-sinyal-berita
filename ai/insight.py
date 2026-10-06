"""Insight event — isu + urgency per event, lalu draf laporan.

Kontrak: analyze_event(event: EventDraft) -> EventInsight
         draft_report(events: list[dict], period: str) -> str

Prinsip: heuristic dulu (deterministik, tanpa API), LLM hanya peningkatan
opsional. Kalau LLM gagal atau 429, hasil heuristic tetap dipakai.
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from dotenv import load_dotenv

from core.schemas import EventDraft, EventInsight

load_dotenv()

PROMPT_FILE = Path(__file__).resolve().parent / "prompts" / "event_insight.txt"
WIB = ZoneInfo("Asia/Jakarta")

HEURISTIC_VERSION = "heuristic-insight-0.1"
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
GEMINI_TIMEOUT = float(os.getenv("GEMINI_TIMEOUT", "30"))
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "nvidia/nemotron-3-super-120b-a12b:free")
OPENROUTER_TIMEOUT = float(os.getenv("OPENROUTER_TIMEOUT", "60"))
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MAX_SAMPLE_TEXTS = 5

ISSUE_CLASSES = [
    "banjir",
    "macet_lalu_lintas",
    "jalan_dan_jembatan_rusak",
    "sampah_dan_lingkungan",
    "listrik_dan_air",
    "keamanan_kriminalitas",
    "kebakaran",
    "bencana_alam",
    "layanan_publik",
    "harga_kebutuhan_pokok",
    "kesehatan_dan_sosial",
    "lainnya",
]

# issue_hint dari relevance → kelas isu; kata kunci lain dipetakan ke hint dulu
HINT_TO_CLASS = {
    "banjir": "banjir",
    "genangan": "banjir",
    "macet": "macet_lalu_lintas",
    "jalan rusak": "jalan_dan_jembatan_rusak",
    "jembatan": "jalan_dan_jembatan_rusak",
    "longsor": "bencana_alam",
    "kebakaran": "kebakaran",
    "sampah": "sampah_dan_lingkungan",
    "lampu mati": "listrik_dan_air",
    "listrik": "listrik_dan_air",
    "air mati": "listrik_dan_air",
    "keamanan": "keamanan_kriminalitas",
    "kriminalitas": "keamanan_kriminalitas",
    "harga": "harga_kebutuhan_pokok",
    "layanan": "layanan_publik",
    "kesehatan": "kesehatan_dan_sosial",
}

_INSIGHT_SCHEMA = {
    "type": "object",
    "properties": {
        "issue_class": {"type": "string", "enum": ISSUE_CLASSES},
        "urgency": {"type": "integer", "minimum": 1, "maximum": 5},
        "rationale": {"type": "string"},
    },
    "required": ["issue_class", "urgency", "rationale"],
}


def provider() -> str:
    """Sama seperti ai.relevance: explicit AI_PROVIDER, else key yang tersedia."""
    forced = os.getenv("AI_PROVIDER", "").strip().lower()
    if forced:
        return forced
    if os.getenv("OPENROUTER_API_KEY", "").strip():
        return "openrouter"
    if os.getenv("GEMINI_API_KEY", "").strip():
        return "gemini"
    return "heuristic"


def insight_model_version() -> str:
    prov = provider()
    if prov == "gemini":
        return f"gemini:{GEMINI_MODEL}"
    if prov == "openrouter":
        return f"openrouter:{OPENROUTER_MODEL}"
    return HEURISTIC_VERSION


def _normalize_class(value: str | None) -> str:
    v = (value or "").strip().lower().replace(" ", "_").replace("-", "_")
    return v if v in ISSUE_CLASSES else "lainnya"


def _class_from_texts(event: EventDraft) -> str:
    """Kelas isu dari issue_hint; kalau kosong,/USD dari kata kunci di teks."""
    hint = (event.issue_hint or "").strip().lower()
    if hint in HINT_TO_CLASS:
        return HINT_TO_CLASS[hint]
    blob = " ".join(event.sample_texts).lower()
    for kw, cls in HINT_TO_CLASS.items():
        if kw in blob:
            return cls
    return "lainnya"


def heuristic_insight(event: EventDraft) -> EventInsight:
    """Tanpa LLM: kelas dari issue_hint/teks, urgency dari jumlah posting."""
    n = len(event.post_ids) or 1
    urgency = min(5, 1 + n // 3)
    issue_class = _class_from_texts(event)
    where = event.location or "lokasi tidak disebut"
    return EventInsight(
        issue_class=issue_class,
        urgency=urgency,
        rationale=(
            f"Heuristic: {n} posting tentang {where}"
            f" dengan indikasi isu '{event.issue_hint or 'tidak jelas'}'."
        ),
    )


def _prompt_for(event: EventDraft) -> str:
    texts = "\n---\n".join(t.strip()[:400] for t in event.sample_texts[:MAX_SAMPLE_TEXTS])
    template = PROMPT_FILE.read_text(encoding="utf-8") if PROMPT_FILE.exists() else "{texts}"
    return (
        template.replace("{location}", event.location or "-")
        .replace("{issue_hint}", event.issue_hint or "-")
        .replace("{n_posts}", str(len(event.post_ids)))
        .replace("{texts}", texts)
    )


def _extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            raise ValueError("tidak ada objek JSON pada output LLM")
        return json.loads(m.group(0))


def _validate(raw: dict) -> EventInsight:
    return EventInsight(
        issue_class=_normalize_class(raw.get("issue_class")),
        urgency=max(1, min(5, int(raw.get("urgency", 1)))),
        rationale=(raw.get("rationale") or "").strip() or "tanpa keterangan",
    )


def _insight_gemini(event: EventDraft) -> EventInsight:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY kosong")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
    payload = {
        "contents": [{"parts": [{"text": _prompt_for(event)}]}],
        "generationConfig": {
            "temperature": 0.0,
            "maxOutputTokens": 512,
            "responseMimeType": "application/json",
            "responseSchema": _INSIGHT_SCHEMA,
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
            return _validate(json.loads(body["candidates"][0]["content"]["parts"][0]["text"]))
        except Exception as e:  # noqa: BLE001 — fallback heuristic di analyze_event
            last_err = e
            status = getattr(getattr(e, "response", None), "status_code", None)
            if status in (429, 503) and attempt < 3:
                time.sleep(5 * attempt)
                continue
            break
    raise RuntimeError(f"gemini gagal: {last_err}")


def _insight_openrouter(event: EventDraft) -> EventInsight:
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY kosong")
    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [{"role": "user", "content": _prompt_for(event)}],
        "temperature": 0.0,
        "max_tokens": 400,
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "HTTP-Referer": "https://github.com/Aditya27T/prototype-sinyal-berita",
        "X-Title": "Telinga Digital",
    }
    last_err: Exception | None = None
    for attempt in (1, 2, 3):
        try:
            with httpx.Client(timeout=OPENROUTER_TIMEOUT) as client:
                resp = client.post(OPENROUTER_URL, headers=headers, json=payload)
                resp.raise_for_status()
                body = resp.json()
            return _validate(_extract_json(body["choices"][0]["message"]["content"] or "{}"))
        except Exception as e:  # noqa: BLE001 — fallback heuristic di analyze_event
            last_err = e
            status = getattr(getattr(e, "response", None), "status_code", None)
            if status in (429, 500, 502, 503) and attempt < 3:
                time.sleep(5 * attempt)  # free-tier throttle
                continue
            break
    raise RuntimeError(f"openrouter gagal: {last_err}")


def analyze_event(event: EventDraft) -> EventInsight:
    """Kontrak: heuristic selalu tersedia, LLM hanya meningkatkan kualitas."""
    prov = provider()
    if prov in ("gemini", "openrouter"):
        try:
            insight = _insight_gemini(event) if prov == "gemini" else _insight_openrouter(event)
        except Exception as e:  # noqa: BLE001 — demo tidak boleh berhenti karena LLM
            result = heuristic_insight(event)
            result.rationale = f"{result.rationale} (llm-fallback: {e})"
            return result
        pace = float(os.getenv("AI_PACE_SECONDS", "5"))
        if pace > 0:
            time.sleep(pace)  # hormati rate-limit free-tier antar event
        return insight
    return heuristic_insight(event)


def draft_report(events: list[dict], period: str) -> str:
    """Draf laporan markdown dari daftar event (tanpa LLM)."""
    label = {"today": "harian", "week": "mingguan", "month": "bulanan"}.get(period, period)
    lines = [
        f"# Laporan isu publik Malang Raya — {label} {period}",
        "",
        (
            f"_Dibuat {datetime.now(WIB).strftime('%d-%m-%Y %H:%M')} WIB · "
            f"{len(events)} event · model insight: {insight_model_version()}_"
        ),
        "",
    ]
    if not events:
        lines.append("Tidak ada event pada periode ini.")
        return "\n".join(lines) + "\n"

    ordered = sorted(events, key=lambda e: (-int(e.get("urgency") or 0), str(e.get("location") or "")))
    urgent = [e for e in ordered if int(e.get("urgency") or 0) >= 4]
    lines.append("## Ringkasan")
    lines.append(
        f"- Total event: **{len(ordered)}** · event dengan urgency ≥ 4: **{len(urgent)}**"
    )
    lines.append(
        "- Urutan di bawah dari urgency tertinggi; posting sumber memakai tautan aslinya."
    )
    lines.append("")

    lines.append("## Isu dominan per lokasi")
    per_loc: dict[str, list[str]] = {}
    for e in ordered:
        per_loc.setdefault(str(e.get("location") or "lokasi tidak disebut"), []).append(
            str(e.get("issue_class") or "lainnya")
        )
    for loc, classes in sorted(per_loc.items(), key=lambda kv: -len(kv[1])):
        top = max(set(classes), key=classes.count)
        lines.append(f"- **{loc}** — {len(classes)} event, dominan: `{top}`")
    lines.append("")

    lines.append("## Daftar event")
    for e in ordered:
        loc = e.get("location") or "lokasi tidak disebut"
        lines.append(
            f"### [{e.get('urgency')}/5] {e.get('issue_class')} — {loc}"
        )
        if e.get("rationale"):
            lines.append(f"- Alasan: {e['rationale']}")
        lines.append(f"- Key: `{e.get('key')}` · {len(e.get('post_ids') or [])} posting pendukung")
        for src in (e.get("sources") or [])[:5]:
            author = f" — @{src['author']}" if src.get("author") else ""
            kind = " (balasan)" if src.get("kind") == "reply" else ""
            url = src.get("url")
            text = (src.get("text") or "").strip().replace("\n", " ")[:120]
            lines.append(f"  - [{text}]({url}){author}{kind}" if url else f"  - {text}{author}{kind}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"