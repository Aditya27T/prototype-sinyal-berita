# Telinga Digital — Signyal Prototype (1 Hari)

Pipeline: Source publik → Collector (IG + Threads utas/tag) → Raw Posts → Cleaning + Dedup → AI Relevance → DB → Insight graph (cluster → isu + urgency → draf laporan) → Review UI.
Rencana kerja harian: `docs/WORKPLAN.md`. Detail pembagian kerja: `docs/PLAN.md`.
Roadmap setelah prototype (LangGraph ingest, MCP, PDF, cron): `docs/ROADMAP.md`.

## Alur hari ini

```
Threads 5 akun berita + balasan warga (utas)  ┐
Instagram 3 akun + #malang                     ├─ collector (SocialCrawl) → pipeline loop → relevance LLM → posts relevan
Threads tag (#malang, #karangploso malang)     ┘
        ↓ python -m graph.run insight --date today   (LangGraph serial)
   fetch_relevant → cluster_rule → analyze_events → persist → draft_report
        ↓ web (localhost:5173)
   Tab Event (urgency 1–5, isu, lokasi, posting pendukung + balasan) · Tab Laporan (draf → Setujui → approved)
```

Sumber Threads **tidak memakai keyword search** (dihapus karena noise jual-beli). Yang diambil: posting hari ini
dari akun berita + balasan warga di bawahnya, dan posting yang benar-benar ber-`topic_tag` (socialcrawl tidak punya
endpoint feed tag, jadi `threads/search` lalu disaring di klien atas `post.ext.topic_tag`).

## Cara tercepat (demo)

```bash
make demo      # pipeline dari snapshot (0 credit) → insight → web, browser terbuka otomatis
```

Butuh `make`, `uv`, dan `bun`. Target lain:

| Target | Arti |
|---|---|
| `make pipeline` | pipeline sungguhan ke SocialCrawl (memakai credit) |
| `make pipeline-snapshot` | pipeline dari `fixtures/` tanpa credit — untuk demo & uji ulang |
| `make insight` | insight graph pada data yang sudah ada di DB |
| `make db-reset` | hapus `signyal.db` lalu `create_all` |
| `make test` | pytest |
| `make api` / `make web` | FastAPI :8000 / API + web :5173 |

## Demo manual langkah demi langkah

```bash
# 1. pipeline (pakai credit SocialCrawl)
uv run python -m pipeline.run --limit 20
#    atau dari snapshot: make pipeline-snapshot

# 2. buktikan idempoten — run kedua inserted=0
uv run python -m pipeline.run --limit 20

# 3. insight graph → event + draf laporan
uv run python -m graph.run insight --date today

# cek hasil
sqlite3 signyal.db "select count(*) from events"
sqlite3 signyal.db "select period,status from reports"

# 4. API + web
make web
# buka http://localhost:5173 → tab Event, tab Laporan → Setujui
```

## Endpoint

| Endpoint | Guna |
|---|---|
| `GET /posts/relevant` | posting relevan (skor, lokasi, isu) |
| `GET /posts/all` | semua posting + `kind` (root/reply/tag), `parent_url`, `topic_tag` |
| `GET /events?date=&min_urgency=` | event hasil clustering, urut urgency |
| `GET /events/{id}` | event + posting pendukung |
| `GET /reports` · `GET /reports/{id}` | daftar/detail laporan (markdown) |
| `POST /reports/{id}/approve` | operator menyetujui draf → `approved` |

## Catatan biaya & LLM

- Credit SocialCrawl: 1 run nyata ≈ 40–70 credit (IG 3 akun + #malang, Threads 5 akun + balasan + 2 tag). Bisa dicek: `GET /v1/credits/balance`.
- `THREADS_REPLIES_PER_ACCOUNT` (default 2) = jumlah posting per akun yang **memang punya balasan**; `THREADS_REPLIES_MAX_POSTS` (default 4) = batas request balasan per akun.
- Free tier LLM sering 404/429. Karena itu `ai/insight.py` dan `ai/relevance.py` selalu punya versi heuristic, dan `post_analysis.model_version` ditulis `heuristic-fallback` bila LLM gagal — jangan pernah berlabel model LLM saat hasil dari heuristic.

## Detail pembagian kerja (3 orang, sudah selesai) — `docs/PLAN.md`

- [x] `core/schemas.py` — kontrak `Post`, `AnalysisResult`, `EventDraft`, `EventInsight`
- [x] `database/` — models (`sources`, `posts`, `post_analysis`, `events`, `event_posts`, `reports`) + `connection.py`
- [x] `collectors/source_one.py` — Instagram (akun + hashtag) & Threads (akun + balasan + tag)
- [x] `pipeline/run.py` — collect → clean → dedup → insert → analyze, idempotent
- [x] `graph/insight_graph.py` — LangGraph serial: cluster → isu/urgency → persist → draf laporan
- [x] `api/main.py` — FastAPI posts + events + reports
- [x] `web/` — Bun + React, tab Posting / Event / Laporan

## Kontrak yang dipanggil pipeline (jangan diubah signature-nya)
| Modul | Fungsi |
|---|---|
| `collectors/source_one.py` | `collect(query: str, limit: int) -> list[Post]` |
| `processing/normalize.py` | `clean(post: Post) -> Post \| None` |
| `processing/deduplicate.py` | `dedup_key(post: Post) -> str` |
| `ai/relevance.py` | `analyze(post: Post) -> AnalysisResult` |

Ditambah (hari insight, dipakai graph):
| Modul | Fungsi |
|---|---|
| `ai/insight.py` | `analyze_event(event: EventDraft) -> EventInsight` |
| `ai/insight.py` | `draft_report(events: list[dict], period: str) -> str` |

## Setup awal (dari clone)

```bash
git clone https://github.com/Aditya27T/prototype-sinyal-berita.git
cd prototype-sinyal-berita
cp .env.example .env
uv sync --extra dev
```

## Prasyarat
Python 3.12+, `uv`, Bun, Docker (opsional untuk Postgres di `docker-compose.yml`).
