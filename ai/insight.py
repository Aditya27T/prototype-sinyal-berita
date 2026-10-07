"""Insight event — isu + urgency + narasi laporan per event, lalu draf laporan.

Kontrak: analyze_event(event: EventDraft) -> EventInsight
         draft_report(events: list[dict], period: str, window_date: str | None) -> str

Prinsip: heuristic dulu (deterministik, tanpa API), LLM hanya peningkatan
opsional. Kalau LLM gagal atau 429, hasil heuristic tetap dipakai. Format
narasi mengikuti docs/contohlaporan.md.
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from dotenv import load_dotenv

from ai.llm_keys import gemini_keys
from core.schemas import EventDraft, EventInsight

load_dotenv()

PROMPT_FILE = Path(__file__).resolve().parent / "prompts" / "event_insight.txt"
MERGE_PROMPT_FILE = Path(__file__).resolve().parent / "prompts" / "event_merge.txt"
MERGE_CHUNK = 25  # kandidat per panggilan LLM merge
MERGE_MIN_CONFIDENCE = 0.7
WIB = ZoneInfo("Asia/Jakarta")

HEURISTIC_VERSION = "heuristic-insight-0.2"
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "nvidia/nemotron-3-super-120b-a12b:free")
OPENROUTER_TIMEOUT = float(os.getenv("OPENROUTER_TIMEOUT", "60"))
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MAX_SAMPLE_TEXTS = 5

ISSUE_CLASSES = [
    "banjir",
    "macet_lalu_lintas",
    "kecelakaan_lalu_lintas",
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

# label manusiawi untuk laporan ("Kategori: Keamanan & Kriminalitas")
ISSUE_LABELS = {
    "banjir": "Banjir & Genangan",
    "macet_lalu_lintas": "Lalu Lintas & Kemacetan",
    "kecelakaan_lalu_lintas": "Kecelakaan Lalu Lintas",
    "jalan_dan_jembatan_rusak": "Infrastruktur Jalan & Jembatan",
    "sampah_dan_lingkungan": "Sampah & Lingkungan",
    "listrik_dan_air": "Listrik & Air Bersih",
    "keamanan_kriminalitas": "Keamanan & Kriminalitas",
    "kebakaran": "Kebakaran",
    "bencana_alam": "Bencana Alam",
    "layanan_publik": "Layanan Publik & Kebijakan",
    "harga_kebutuhan_pokok": "Harga Kebutuhan Pokok",
    "kesehatan_dan_sosial": "Kesehatan & Sosial",
    "lainnya": "Lainnya",
}

# issue_hint dari relevance → kelas isu; kata kunci lain dipetakan ke hint dulu
HINT_TO_CLASS = {
    "banjir": "banjir",
    "genangan": "banjir",
    "macet": "macet_lalu_lintas",
    "kecelakaan": "kecelakaan_lalu_lintas",
    "laka": "kecelakaan_lalu_lintas",
    "tabrak": "kecelakaan_lalu_lintas",
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

SENTIMENTS = ("negatif", "netral", "positif")
LEVELS = ("rendah", "sedang", "tinggi")
STATUSES = ("monitor", "prioritas", "selesai")

_INSIGHT_SCHEMA = {
    "type": "object",
    "properties": {
        "issue_class": {"type": "string", "enum": ISSUE_CLASSES},
        "urgency": {"type": "integer", "minimum": 1, "maximum": 5},
        "rationale": {"type": "string"},
        "title": {"type": "string"},
        "occurred_at": {"type": "string", "nullable": True},
        "summary": {"type": "string"},
        "sentiment": {"type": "string", "enum": list(SENTIMENTS)},
        "attention_level": {"type": "string", "enum": list(LEVELS)},
        "issue_character": {"type": "string"},
        "potential": {"type": "string"},
        "recommendation": {"type": "string"},
        "status": {"type": "string", "enum": list(STATUSES)},
    },
    "required": [
        "issue_class", "urgency", "rationale", "title", "occurred_at", "summary", "sentiment",
        "attention_level", "issue_character", "potential", "recommendation", "status",
    ],
}

MONTHS_ID = [
    "Januari", "Februari", "Maret", "April", "Mei", "Juni",
    "Juli", "Agustus", "September", "Oktober", "November", "Desember",
]


def provider() -> str:
    """Sama seperti ai.relevance: explicit AI_PROVIDER, else key yang tersedia."""
    forced = os.getenv("AI_PROVIDER", "").strip().lower()
    if forced:
        return forced
    if os.getenv("OPENROUTER_API_KEY", "").strip():
        return "openrouter"
    if gemini_keys():
        return "gemini"
    return "heuristic"


def insight_model_version() -> str:
    prov = provider()
    if prov == "gemini":
        return f"gemini:{GEMINI_MODEL}"
    if prov == "openrouter":
        return f"openrouter:{OPENROUTER_MODEL}"
    return HEURISTIC_VERSION


# --- Tanggal & teks bantu ---------------------------------------------------


def format_date_id(value: str | date | datetime | None) -> str:
    """'2026-10-06' → '6 Oktober 2026'."""
    if value is None:
        return "-"
    if isinstance(value, datetime):
        d = value.astimezone(WIB).date()
    elif isinstance(value, date):
        d = value
    else:
        try:
            d = date.fromisoformat(str(value)[:10])
        except ValueError:
            return str(value)
    return f"{d.day} {MONTHS_ID[d.month - 1]} {d.year}"


def format_period_id(dates: list[str]) -> str:
    """['2026-10-05','2026-10-06'] → '5–6 Oktober 2026'; beda bulan → '30 September – 1 Oktober 2026'."""
    ds = sorted({str(x)[:10] for x in dates if x})
    if not ds:
        return "-"
    first, last = date.fromisoformat(ds[0]), date.fromisoformat(ds[-1])
    if first == last:
        return format_date_id(first)
    if (first.month, first.year) == (last.month, last.year):
        return f"{first.day}–{last.day} {MONTHS_ID[first.month - 1]} {first.year}"
    return f"{format_date_id(first)} – {format_date_id(last)}"


def _source_date(src: dict) -> str | None:
    v = src.get("published_at")
    if isinstance(v, datetime):
        return v.astimezone(WIB).date().isoformat()
    if isinstance(v, str) and len(v) >= 10:
        try:
            return datetime.fromisoformat(v.replace("Z", "+00:00")).astimezone(WIB).date().isoformat()
        except ValueError:
            return v[:10]
    return None


def exposure_text(sources: list[dict]) -> str:
    """"Eksposur Media Sosial" dihitung dari sumber — fakta, jadi tidak diserahkan ke LLM."""
    if not sources:
        return "Eksposur belum dapat dihitung (tidak ada sumber tercatat)."
    platform_name = {"instagram": "Instagram", "threads": "Threads"}
    parts: list[str] = []
    for platform in sorted({s.get("platform") or "lain" for s in sources}):
        rows = [s for s in sources if (s.get("platform") or "lain") == platform]
        roots = [s for s in rows if s.get("kind") != "reply"]
        replies = [s for s in rows if s.get("kind") == "reply"]
        accounts = sorted({f"@{s['author']}" for s in roots if s.get("author")})
        name = platform_name.get(platform, platform)
        seg = []
        if roots:
            acc = ""
            if accounts:
                shown = ", ".join(accounts[:4]) + (f", +{len(accounts) - 4} lainnya" if len(accounts) > 4 else "")
                acc = f" dari {len(accounts)} akun ({shown})"
            seg.append(f"**{len(roots)} unggahan** {name}{acc}")
        if replies:
            seg.append(f"**{len(replies)} balasan/komentar warga** di {name}")
        parts.append(" dan ".join(seg))
    dates = [d for d in (_source_date(s) for s in sources) if d]
    when = f", pada {format_period_id(dates)}" if dates else ""
    return "Isu terpantau pada " + "; ".join(parts) + when + "."


# --- Heuristic ----------------------------------------------------------------


def _normalize_class(value: str | None) -> str:
    v = (value or "").strip().lower().replace(" ", "_").replace("-", "_")
    return v if v in ISSUE_CLASSES else "lainnya"


def _normalize_choice(value: str | None, allowed: tuple[str, ...], default: str) -> str:
    v = (value or "").strip().lower()
    return v if v in allowed else default


def _class_from_texts(event: EventDraft) -> str:
    """Kelas isu dari issue_hint; kalau kosong, dari kata kunci di teks."""
    hint = (event.issue_hint or "").strip().lower()
    if hint in HINT_TO_CLASS:
        return HINT_TO_CLASS[hint]
    for kw, cls in HINT_TO_CLASS.items():
        if kw in hint:
            return cls
    blob = " ".join(event.sample_texts).lower()
    for kw, cls in HINT_TO_CLASS.items():
        if kw in blob:
            return cls
    return "lainnya"


def level_for(urgency: int) -> str:
    return "tinggi" if urgency >= 4 else "sedang" if urgency == 3 else "rendah"


def status_for(urgency: int) -> str:
    return "prioritas" if urgency >= 4 else "monitor"


def heuristic_insight(event: EventDraft) -> EventInsight:
    """Tanpa LLM: kelas dari issue_hint/teks, urgency dari jumlah posting, narasi template."""
    n = len(event.post_ids) or 1
    urgency = min(5, 1 + n // 3)
    issue_class = _class_from_texts(event)
    where = event.location or "lokasi tidak disebut"
    label = ISSUE_LABELS[issue_class]
    first = (event.sample_texts[0].strip().replace("\n", " ") if event.sample_texts else "")
    summary = (
        f"Terpantau {n} unggahan terkait {label.lower()} di {where}. "
        + (f"Kutipan unggahan: \"{first[:220]}{'…' if len(first) > 220 else ''}\"" if first else "")
    ).strip()
    return EventInsight(
        issue_class=issue_class,
        urgency=urgency,
        rationale=(
            f"Heuristic: {n} posting tentang {where}"
            f" dengan indikasi isu '{event.issue_hint or 'tidak jelas'}'."
        ),
        title=f"{label} di {where}" if event.location else label,
        occurred_at=None,
        summary=summary,
        exposure=exposure_text(event.sources),
        sentiment="negatif" if issue_class != "lainnya" else "netral",
        attention_level=level_for(urgency),
        issue_character="Insidental / kejadian lokal",
        potential=(
            "Isu masih sebatas penyampaian kejadian oleh akun lokal; perlu dipantau apakah "
            "berkembang menjadi keluhan atau kritik terhadap penanganan."
        ),
        recommendation=(
            "Lakukan monitoring lanjutan terhadap perkembangan unggahan dan komentar warga; "
            "naikkan prioritas bila volume percakapan atau keluhan meningkat."
        ),
        status=status_for(urgency),
    )


# --- LLM ------------------------------------------------------------------------


def _sources_block(event: EventDraft) -> str:
    rows = []
    for s in event.sources[:10]:
        when = _source_date(s) or "-"
        kind = " (balasan)" if s.get("kind") == "reply" else ""
        rows.append(f"- @{s.get('author') or '?'} · {s.get('platform') or '?'} · {when}{kind}")
    return "\n".join(rows) or "- (tidak tercatat)"


def _prompt_for(event: EventDraft) -> str:
    texts = "\n---\n".join(t.strip()[:400] for t in event.sample_texts[:MAX_SAMPLE_TEXTS])
    template = PROMPT_FILE.read_text(encoding="utf-8") if PROMPT_FILE.exists() else "{texts}"
    return (
        template.replace("{location}", event.location or "-")
        .replace("{issue_hint}", event.issue_hint or "-")
        .replace("{n_posts}", str(len(event.post_ids)))
        .replace("{sources}", _sources_block(event))
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


def _should_retry(err: Exception, attempt: int) -> bool:
    """Sama seperti ai.relevance: kuota harian habis tidak perlu di-retry."""
    from ai.relevance import _is_daily_quota_error

    if _is_daily_quota_error(err):
        return False
    if attempt >= 3:
        return False
    status = getattr(getattr(err, "response", None), "status_code", None)
    return status in (429, 500, 502, 503)


def llm_unavailable() -> bool:
    """Sama seperti relevance: kuota habis (semua key) → sisa event pakai heuristic."""
    from ai.relevance import llm_unavailable as _rel

    return _rel()


def mark_llm_unavailable(err: Exception) -> None:
    from ai.relevance import _mark_quota_if_exhausted

    _mark_quota_if_exhausted(err)


def _validate(raw: dict, event: EventDraft) -> EventInsight:
    """Normalisasi output LLM; field narasi yang kosong diisi dari heuristic."""
    base = heuristic_insight(event)
    urgency = max(1, min(5, int(raw.get("urgency", 1) or 1)))

    def _text(key: str, fallback: str | None) -> str | None:
        v = raw.get(key)
        return v.strip() if isinstance(v, str) and v.strip() else fallback

    return EventInsight(
        issue_class=_normalize_class(raw.get("issue_class")),
        urgency=urgency,
        rationale=_text("rationale", None) or "tanpa keterangan",
        title=_text("title", base.title),
        occurred_at=_text("occurred_at", None),
        summary=_text("summary", base.summary),
        exposure=exposure_text(event.sources),  # fakta, selalu dari data
        sentiment=_normalize_choice(raw.get("sentiment"), SENTIMENTS, base.sentiment or "negatif"),
        attention_level=_normalize_choice(raw.get("attention_level"), LEVELS, level_for(urgency)),
        issue_character=_text("issue_character", base.issue_character),
        potential=_text("potential", base.potential),
        recommendation=_text("recommendation", base.recommendation),
        status=_normalize_choice(raw.get("status"), STATUSES, status_for(urgency)),
    )


def _insight_gemini(event: EventDraft) -> EventInsight:
    from ai.relevance import gemini_generate  # satu pool key untuk relevance & insight

    payload = {
        "contents": [{"parts": [{"text": _prompt_for(event)}]}],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 1024,
            "responseMimeType": "application/json",
            "responseSchema": _INSIGHT_SCHEMA,
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }
    return _validate(_extract_json(gemini_generate(payload)), event)


def _insight_openrouter(event: EventDraft) -> EventInsight:
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY kosong")
    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [{"role": "user", "content": _prompt_for(event)}],
        "temperature": 0.2,
        "max_tokens": 900,
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
            return _validate(_extract_json(body["choices"][0]["message"]["content"] or "{}"), event)
        except Exception as e:  # noqa: BLE001 — fallback heuristic di analyze_event
            last_err = e
            if _should_retry(e, attempt):
                time.sleep(5 * attempt)  # free-tier throttle
                continue
            break
    raise RuntimeError(f"openrouter gagal: {last_err}")


def analyze_event(event: EventDraft) -> EventInsight:
    """Kontrak: heuristic selalu tersedia, LLM hanya meningkatkan kualitas."""
    prov = provider()
    if prov in ("gemini", "openrouter") and not llm_unavailable():
        try:
            insight = _insight_gemini(event) if prov == "gemini" else _insight_openrouter(event)
        except Exception as e:  # noqa: BLE001 — demo tidak boleh berhenti karena LLM
            mark_llm_unavailable(e)
            result = heuristic_insight(event)
            result.rationale = f"{result.rationale} (llm-fallback: {e})"
            return result
        pace = float(os.getenv("AI_PACE_SECONDS", "5"))
        if pace > 0 and prov == "openrouter":
            time.sleep(pace)  # OpenRouter free-tier; Gemini sudah bergilir antar key
        return insight
    return heuristic_insight(event)


# --- Merge event berbasis LLM ----------------------------------------------------
# Rule-based merge (graph.insight_graph.merge_similar) tidak bisa tahu bahwa video
# konvoi "di Suhat" memperlihatkan kecelakaan Jalan Veteran. LLM membaca konteks
# berita; balasan/komentar ikut induknya karena sudah ada di post_ids draft.

_MERGE_SCHEMA = {
    "type": "object",
    "properties": {
        "groups": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "members": {"type": "array", "items": {"type": "integer"}},
                    "location": {"type": "string", "nullable": True},
                    "title": {"type": "string", "nullable": True},
                    "reason": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": ["members", "reason", "confidence"],
            },
        }
    },
    "required": ["groups"],
}


def _merge_candidates_block(drafts: list[EventDraft]) -> str:
    rows = []
    for i, d in enumerate(drafts, 1):
        srcs = ", ".join(
            f"@{s.get('author')}·{s.get('platform')}" for s in d.sources[:4] if s.get("author")
        )
        texts = " | ".join(t.replace("\n", " ")[:260] for t in d.sample_texts[:3])
        rows.append(
            f"[{i}] lokasi_label={d.location or '-'} · hint={d.issue_hint or '-'} · "
            f"{len(d.post_ids)} posting · sumber: {srcs or '-'}\n    teks: {texts}"
        )
    return "\n".join(rows)


def _merge_prompt(drafts: list[EventDraft]) -> str:
    template = MERGE_PROMPT_FILE.read_text(encoding="utf-8") if MERGE_PROMPT_FILE.exists() else "{candidates}"
    return template.replace("{candidates}", _merge_candidates_block(drafts))


def _merge_call(drafts: list[EventDraft]) -> dict:
    """Satu panggilan LLM → {"groups": [...]}. Dipisah agar mudah di-monkeypatch di test."""
    prov = provider()
    if prov == "gemini":
        from ai.relevance import gemini_generate

        payload = {
            "contents": [{"parts": [{"text": _merge_prompt(drafts)}]}],
            "generationConfig": {
                "temperature": 0.0,
                "maxOutputTokens": 2048,
                "responseMimeType": "application/json",
                "responseSchema": _MERGE_SCHEMA,
                "thinkingConfig": {"thinkingBudget": 0},
            },
        }
        return _extract_json(gemini_generate(payload))
    if prov == "openrouter":
        api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
        payload = {
            "model": OPENROUTER_MODEL,
            "messages": [{"role": "user", "content": _merge_prompt(drafts)}],
            "temperature": 0.0,
            "max_tokens": 1500,
            "response_format": {"type": "json_object"},
        }
        with httpx.Client(timeout=OPENROUTER_TIMEOUT) as client:
            resp = client.post(
                OPENROUTER_URL, headers={"Authorization": f"Bearer {api_key}"}, json=payload
            )
            resp.raise_for_status()
            return _extract_json(resp.json()["choices"][0]["message"]["content"] or "{}")
    return {"groups": []}


def apply_merge_groups(drafts: list[EventDraft], groups: list[dict]) -> list[EventDraft]:
    """Terapkan grup LLM (nomor 1-based) ke drafts; anggota di luar rentang/ganda diabaikan."""
    taken: set[int] = set()
    merged: list[EventDraft] = []
    consumed: set[int] = set()
    for g in groups:
        try:
            conf = float(g.get("confidence", 0))
        except (TypeError, ValueError):
            conf = 0.0
        members = [
            int(m) - 1 for m in g.get("members", [])
            if isinstance(m, (int, float)) and 1 <= int(m) <= len(drafts)
        ]
        members = [m for m in dict.fromkeys(members) if m not in taken]
        if conf < MERGE_MIN_CONFIDENCE or len(members) < 2:
            continue
        base = drafts[members[0]].model_copy(deep=True)
        for idx in members[1:]:
            d = drafts[idx]
            base.post_ids.extend(pid for pid in d.post_ids if pid not in base.post_ids)
            for t in d.sample_texts:
                if len(base.sample_texts) < MAX_SAMPLE_TEXTS and t not in base.sample_texts:
                    base.sample_texts.append(t)
            base.sources.extend(d.sources)
            if not base.issue_hint:
                base.issue_hint = d.issue_hint
        loc = (g.get("location") or "").strip()
        if loc:
            base.location = loc
        taken.update(members)
        consumed.update(members)
        merged.append(base)
        print(
            f"[insight] LLM merge: {len(members)} kandidat → '{g.get('title') or base.location}' "
            f"({conf:.2f}): {g.get('reason', '')[:120]}"
        )
    for i, d in enumerate(drafts):
        if i not in consumed:
            merged.append(d)
    return merged


def llm_merge_active() -> bool:
    """LLM merge jalan bila provider LLM tersedia dan tidak dimatikan (INSIGHT_LLM_MERGE=0)."""
    if os.getenv("INSIGHT_LLM_MERGE", "1") == "0":
        return False
    return provider() in ("gemini", "openrouter") and not llm_unavailable()


def merge_events_llm(drafts: list[EventDraft]) -> list[EventDraft]:
    """Gabungkan kandidat event yang satu konteks berita menurut LLM.

    Tanpa LLM (heuristic / kuota habis / INSIGHT_LLM_MERGE=0) kandidat dikembalikan apa adanya.
    Kandidat diurutkan per kelas isu supaya yang mungkin sama jatuh di chunk yang sama.
    """
    if len(drafts) < 2 or not llm_merge_active():
        return drafts
    ordered = sorted(drafts, key=lambda d: (_class_from_texts(d), d.location or ""))
    out: list[EventDraft] = []
    for start in range(0, len(ordered), MERGE_CHUNK):
        chunk = ordered[start : start + MERGE_CHUNK]
        try:
            groups = _merge_call(chunk).get("groups") or []
        except Exception as e:  # noqa: BLE001 — merge gagal → lanjut tanpa merge
            mark_llm_unavailable(e)
            print(f"[insight] LLM merge dilewati: {e}")
            out.extend(chunk)
            continue
        out.extend(apply_merge_groups(chunk, groups))
    return out


# --- Draf laporan --------------------------------------------------------------

_URGENCY_EMOJI = {5: "🔴", 4: "🔴", 3: "🟠", 2: "🟡", 1: "🟡"}
_SENTIMENT = {"negatif": "🔴 Negatif", "netral": "⚪ Netral", "positif": "🟢 Positif"}
_LEVEL = {"tinggi": "🔴 Tinggi", "sedang": "🟠 Sedang", "rendah": "🟢 Rendah"}
_STATUS = {"monitor": "🟡 Monitor", "prioritas": "🔴 Prioritas", "selesai": "🟢 Selesai"}


def _event_section(e: dict) -> list[str]:
    n = e.get("narrative") or {}
    urgency = int(e.get("urgency") or 1)
    issue_class = e.get("issue_class") or "lainnya"
    label = ISSUE_LABELS.get(issue_class, issue_class)
    loc = e.get("location") or "lokasi tidak disebut"
    sources = e.get("sources") or []
    title = n.get("title") or f"{label} di {loc}"
    lines = [
        f"### {_URGENCY_EMOJI.get(urgency, '🟡')} {title}",
        f"**Kategori:** {label}  ",
        f"**Lokasi:** {loc}  ",
        f"**Waktu kejadian:** {n.get('occurred_at') or 'tidak disebut dalam unggahan'}",
        "",
        "**Ringkasan Isu**  ",
        n.get("summary") or e.get("rationale") or "-",
        "",
        "**Eksposur Media Sosial**  ",
        n.get("exposure") or exposure_text(sources),
        "",
        f"**Sentimen:** {_SENTIMENT.get(n.get('sentiment') or 'negatif', '🔴 Negatif')}  ",
        f"**Level perhatian:** {_LEVEL.get(n.get('attention_level') or level_for(urgency))}  ",
        f"**Karakter isu:** {n.get('issue_character') or 'Insidental / kejadian lokal'}",
        "",
        "**Potensi Isu**  ",
        n.get("potential") or "-",
        "",
        "**Rekomendasi**  ",
        n.get("recommendation") or "-",
        "",
        f"**Status:** {_STATUS.get(n.get('status') or status_for(urgency))}",
        "",
    ]
    if sources:
        lines.append("**Sumber**  ")
        for src in sources[:6]:
            author = f" — @{src['author']}" if src.get("author") else ""
            kind = " (balasan)" if src.get("kind") == "reply" else ""
            url = src.get("url")
            text = (src.get("text") or "").strip().replace("\n", " ")[:110]
            text = text or (src.get("platform") or "sumber")
            lines.append(f"- [{text}]({url}){author}{kind}" if url else f"- {text}{author}{kind}")
        lines.append("")
    return lines


def draft_report(events: list[dict], period: str, window_date: str | None = None) -> str:
    """Draf laporan markdown bergaya docs/contohlaporan.md (satu bagian per isu)."""
    dates = [window_date] if window_date else []
    for e in events:
        dates += [d for d in (_source_date(s) for s in (e.get("sources") or [])) if d]
    if not dates and period not in ("today", "week", "month"):
        dates = [period]
    periode = format_period_id(dates) if dates else format_date_id(datetime.now(WIB))

    ordered = sorted(events, key=lambda e: (-int(e.get("urgency") or 0), str(e.get("location") or "")))
    urgent = [e for e in ordered if int(e.get("urgency") or 0) >= 4]
    lines = [
        "## LAPORAN MONITORING ISU MEDIA SOSIAL",
        f"**Periode: {periode}**",
        "",
        (
            f"_Dibuat {datetime.now(WIB).strftime('%d-%m-%Y %H:%M')} WIB · {len(ordered)} isu · "
            f"{len(urgent)} prioritas · model insight: {insight_model_version()}_"
        ),
        "",
    ]
    if not ordered:
        lines.append("Tidak ada isu publik yang terpantau pada periode ini.")
        return "\n".join(lines) + "\n"
    for e in ordered:
        lines += _event_section(e)
    return "\n".join(lines).rstrip() + "\n"
