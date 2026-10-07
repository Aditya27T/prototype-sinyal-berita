# Telinga Digital — Signyal Prototype (1 Hari)

Pipeline: Source publik → Collector (IG + Threads utas/tag) → Raw Posts → Cleaning + Dedup → AI Relevance → DB → Insight graph (cluster → isu + urgency → draf laporan) → Review UI.
Rencana kerja harian: `docs/WORKPLAN.md`. Detail pembagian kerja: `docs/PLAN.md`.
Roadmap setelah prototype (LangGraph ingest, MCP, PDF, cron): `docs/ROADMAP.md`.

## Alur hari ini

```
Threads 5 akun berita + balasan warga (utas)  ┐
Instagram 3 akun + komentar teratasnya     ├─ collector (SocialCrawl) → pipeline loop → relevance LLM → posts relevan
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
| `make comments` | komentar teratas posting relevan yang belum diambil (5 credit/posting). `N=5` untuk jumlah, `DRY_RUN=1` untuk lihat kandidat tanpa bayar |
| `make db-reset` | hapus `signyal.db` lalu `create_all` |
| `make insight` | insight graph pada data yang sudah ada di DB |
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
| `GET /posts/all?days=&kind=` | semua posting + `kind` (root/reply/tag), `parent_url`, `topic_tag`, `comment_count`; `days` = N hari terakhir |
| `GET /posts/{id}/comments` | komentar/balasan turunan satu posting (isi dropdown "Komentar" di web) |
| `GET /events?date=&min_urgency=` | event hasil clustering, urut urgency |
| `GET /events/{id}` | event + posting pendukung |
| `GET /reports` · `GET /reports/{id}` | daftar/detail laporan (markdown) |
| `POST /reports/{id}/approve` | operator menyetujui draf → `approved` |

## Catatan biaya & LLM

- Credit SocialCrawl: 1 run nyata ≈ 40–70 credit (IG 3 akun + komentar 3 posting relevan, Threads 5 akun + balasan + 2 tag). Bisa dicek: `GET /v1/credits/balance`.
- **Hashtag Instagram dihapus** (6 Okt 2026): `search/hashtag` 5 credit/halaman dan isinya didominasi unggahan jual-beli/fashion, bukan isu publik. Sumber IG hanya 3 akun berita + komentar teratas posting relevan.
- `THREADS_REPLIES_PER_ACCOUNT` (default 2) = jumlah posting per akun yang **memang punya balasan**; `THREADS_REPLIES_MAX_POSTS` (default 4) = batas request balasan per akun.
- Komentar Instagram diambil **setelah** relevance, hanya untuk posting relevan dengan komentar terbanyak (`IG_COMMENTS_MAX_POSTS`, default 3 posting × 5 credit; `IG_COMMENTS_TOP_N` komentar teratas disimpan). Komentar masuk sebagai baris `kind=reply` dengan `parent_post_id`, ikut event induknya di insight graph.
- `make demo DATE=2026-10-06` memutar ulang snapshot hari itu; tanpa `DATE`, demo otomatis memakai snapshot terbaru bila hari ini belum ada run nyata.
- **Laporan** mengikuti format `docs/contohlaporan.md`: satu bagian per isu (Kategori, Lokasi, Waktu kejadian, Ringkasan Isu, Eksposur Media Sosial, Sentimen, Level perhatian, Karakter isu, Potensi Isu, Rekomendasi, Status, Sumber). Narasi ditulis Gemini per event (satu panggilan per event, fallback template); Eksposur selalu dihitung dari data.
- **Ekspor**: `GET /reports/{id}.pdf` (tombol "Unduh PDF" di web) — **tanpa bagian Rekomendasi** (internal tim); `?with_recommendation=true` untuk versi lengkap. `GET /reports/{id}.md` markdown lengkap.
- **3 API key Gemini**: isi `GEMINI_API_KEY`, `GEMINI_API_KEY_2`, `GEMINI_API_KEY_3` (atau `GEMINI_API_KEYS=a,b,c`). Dipakai bergilir; key yang 429/kuota habis dilewati otomatis, heuristic hanya dipakai bila semua habis.
- **Clustering dua tahap**: (1) aturan — satu utas (induk + balasan/komentar) = satu kandidat, duplikat teks dan lokasi-spesifik+kelas sama digabung; (2) **LLM merge** (`ai/prompts/event_merge.txt`, satu panggilan Gemini per ≤25 kandidat) menyatukan kandidat yang satu konteks berita walau akun/platform/label lokasinya beda (mis. berita IG + Threads + video konvoi tentang kecelakaan yang sama), hanya bila confidence ≥ 0,7. Matikan dengan `INSIGHT_LLM_MERGE=0` (lalu aturan teks ketat dipakai). Run ulang `make insight` memperbarui event (yang tergabung dihapus), bukan menumpuk.
- Free tier LLM sering 404/429. Karena itu `ai/insight.py` dan `ai/relevance.py` selalu punya versi heuristic, dan `post_analysis.model_version` ditulis `heuristic-fallback` bila LLM gagal — jangan pernah berlabel model LLM saat hasil dari heuristic.

## Detail pembagian kerja (3 orang, sudah selesai) — `docs/PLAN.md`

- [x] `core/schemas.py` — kontrak `Post`, `AnalysisResult`, `EventDraft`, `EventInsight`
- [x] `database/` — models (`sources`, `posts`, `post_analysis`, `events`, `event_posts`, `reports`) + `connection.py`
- [x] `collectors/source_one.py` — Instagram (3 akun + komentar posting relevan) & Threads (akun + balasan + tag)
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
