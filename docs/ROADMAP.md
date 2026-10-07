# Roadmap Telinga Digital

Rangkuman seluruh plan setelah prototype 1 hari: Threads utas, hardening, LangGraph, clustering + MCP, laporan, biaya, risiko, keputusan tim. Urutan kerja hari ini (1 orang, 1 fase): `WORKPLAN.md`. Dokumen pendukung: `PLAN.md` (prototype 1 hari), `PLAN_MAKE_WEB.md` (selesai).

## 1. Status sekarang (Oktober 2026)

Prototype 1 hari tercapai: collector Instagram (3 akun + #malang) dan Threads via SocialCrawl, relevance LLM (OpenRouter Qwen free / Gemini, fallback heuristic), pipeline idempotent, FastAPI, web React, `make web`, eval 30 posting nyata.

| Area | Celah |
|---|---|
| Collector | Threads masih keyword `malang` → noise jual-beli; paging IG boros credit; tidak ada log `credits.used` |
| Relevance | Skor LLM tidak terkalibrasi; fallback heuristic tercatat sebagai model LLM; eval hanya 30 |
| Pipeline | Loop serial, tidak bisa resume, tanpa jadwal |
| Web/API | Tidak ada status run; tidak ada aksi operator |
| Data | SQLite per orang; belum ada DB bersama |

## 2. Prinsip

1. Kontrak `Post`/`AnalysisResult` dan 4 signature (`collect`, `clean`, `dedup_key`, `analyze`) tetap.
2. Tiap fase punya kriteria selesai yang bisa dicek dengan perintah.
3. Biaya (credit SocialCrawl, token LLM) dihitung sebelum fitur ditambah.
4. Fase berikutnya dimulai setelah fase sebelumnya terbukti dengan data nyata.
5. Validitas confidence **dikesampingkan dulu**; fokus workflow dan clustering.

## 3. Fase 0 — Threads utas + hardening (minggu 1)

### 3a. Threads: utas dari akun berita + tag, tanpa keyword search (prioritas pertama)

Keputusan: di Threads **tidak ada keyword search**. Yang diambil = (1) posting hari ini dari akun berita Malang **+ balasan warga di bawahnya** (utas), dan (2) posting ber-**tag** (`malang`, `beritamalang`, `malangraya`, `infomalang`). SocialCrawl tidak punya endpoint feed tag Threads, jadi tag diambil lewat `threads/search` dengan `query=<tag>` lalu disaring di klien: hanya posting dengan `post.ext.topic_tag == tag` yang disimpan.

Akun terbukti ada di Threads: `malangraya_info`, `infomalangan`, `jawaposradarmalang`, `malangposcomedia`, `infomalangraya`.

| Endpoint SocialCrawl | Biaya | Untuk |
|---|---|---|
| `threads/user/posts` (`handle`, `since`) | 1 credit ≈ 15 posting | posting induk |
| `threads/post/comments` (`url`) | 1 credit ≈ 20 balasan | balasan utas |
| `threads/search` (`query=<tag>`, `start_date`, `end_date`, `limit=20`) + saring `ext.topic_tag` | 1–2 credit per tag | posting ber-tag |

Perubahan (branch `feature/threads-utas`, PR ke Person 1):
- `config/sources.yaml`: hapus `threads/search/malang`; tambah 5 akun `platform: threads, source_type: account, replies: true` dan 4 entri `platform: threads, source_type: tag`.
- `collectors/source_one.py`: `_fetch_threads_user_posts`, `_fetch_threads_replies`, `_reply_to_post` (balasan → `Post` dengan `raw_data.parent_post_id`, `kind="reply"`); `_fetch_threads_tag` (search + saring `topic_tag`, `kind="tag"`); dispatch `_source_posts` per `(platform, source_type)`; hapus cabang `search`; balasan < 15 karakter dibuang; maks `THREADS_REPLIES_PER_ACCOUNT=3` posting per akun yang balasannya diambil.
- Snapshot: `threads:account:<handle>`, `threads:replies:<handle>`, `threads:tag:<tag>`.
- DB tidak berubah; `parent_post_id` jadi kolom di Fase 2.
- Test offline `tests/test_threads_collector.py`.
- Biaya Threads 9–23 credit/run (akun + balasan + tag).

### 3b. Efisiensi credit Instagram (Person 1)
`profile/posts` pakai `since`/`stop_at_id`; `search/hashtag` pakai `max_age_days=1`, `seen`; log `credits.used` → `stats["credits"]`. Target: run kedua di hari yang sama ≤ 5 credit.

### 3c. Relevance (Person 2)
`model_version` jujur saat fallback (`heuristic-fallback`); prompt menyatakan teks posting adalah data, bukan instruksi; eval 30 → 100 label dengan precision + recall. Kalibrasi skor ditunda.

### 3d. Operasional (Person 3)
Postgres bersama jadi default; cron `make pipeline` 3×/hari; `.mcp.json` berisi `https://mcp.socialcrawl.dev/mcp` untuk tooling dev P1; web menampilkan run terakhir + credit terpakai + label "balasan" pada kartu reply.

**Selesai jika:** utas Threads masuk DB dan tampil di web; run kedua ≤ 5 credit; cron 3 hari tanpa 402; `make web` di mesin anggota lain menampilkan data sama.

## 4. Fase 1 — Orkestrasi LangGraph (minggu 2–3, Person 3)

Loop `pipeline/run.py` → `graph/ingest_graph.py`; modul P1/P2 tidak berubah.

```
load_config → collect ─Send(per post)─▶ clean → dedup_check ─┬─ sudah ada → END
                                                             └─ baru → persist_raw → analyze (RetryPolicy)
                                                                         ├─ gagal → heuristic_fallback
                                                                         └─ ok → persist_analysis → END
```

- State `IngestItem`/`IngestState` (TypedDict, reducer `operator.add`), folder `graph/{state.py,nodes/,ingest_graph.py,insight_graph.py,run.py}`.
- 1A Setara: serial, `--engine loop|graph`, stats identik di fixture.
- 1B Tangguh: `RetryPolicy`, `Send` fan-out `max_concurrency=2–3` (ganti `AI_PACE_SECONDS`), checkpointer Postgres, `--resume <thread_id>`.
- Dependensi: `langgraph`, `langgraph-checkpoint-postgres`; LLM tetap `httpx` di `ai/relevance.py`.
- **Selesai jika:** proses dimatikan di tengah lalu `--resume` melanjutkan tanpa analisis ulang; test hijau kedua engine; `--engine loop` dihapus.

## 5. Fase 2 — Clustering + MCP (minggu 4–6, Person 2 + 3)

PRD §16: Event Clustering → Issue Classification → Urgency Scoring.

```
fetch_relevant → cluster_events → enrich_cluster (MCP) → pull_comments (MCP)
              → cross_platform_check (MCP) → classify_issue → score_urgency → persist
budget_guard (MCP account balance) di awal: saldo rendah → lewati enrich
```

- Tabel baru: `events`, `event_issue`, `event_urgency`; kolom `posts.parent_post_id` (utas Threads jadi satu unit cluster).
- Clustering awal: kelompok per (lokasi, issue_hint, hari) + LLM menggabungkan yang serupa; embedding hanya jika > 500 posting/hari.
- Taxonomy isu 10–15 kelas; rubric urgency 1–5.
- **MCP dimaksimalkan di sini** via `langchain-mcp-adapters` (`MultiServerMCPClient`, transport streamable_http, header `x-api-key`), tool yang diekspos hanya `find/estimate/request/collect`, pagar: maks 3 tool call dan `max_credits=10` per cluster:
  - `enrich_cluster`: keyword lahir dari cluster ("banjir Sawojajar") → `socialcrawl_find` → `socialcrawl_collect` lintas platform.
  - `pull_comments`: komentar IG/Threads sebagai sinyal intensitas dan koreksi lokasi.
  - `cross_platform_check`: event di ≥ 2 platform naik urgency.
- Web: halaman "Event" (urgency, posting pendukung, link sumber).
- Ingest rutin **tetap REST**, bukan MCP.
- **Selesai jika:** dari ≥ 100 relevant posts nyata, operator menyetujui ≥ 70 % cluster pada spot-check.

## 6. Fase 3 — Generate laporan (minggu 7–8, Person 3)

Tidak ada alert/push ke Telegram atau WhatsApp. Keluaran fase ini adalah **laporan** yang dibuat dari insight graph dan dibaca operator di web atau diunduh.

- Node `draft_report` di akhir insight graph: dari `events` + `event_issue` + `event_urgency` → ringkasan eksekutif per jendela waktu (harian, mingguan): daftar event ber-urgency, isu dominan per lokasi, tren vs periode sebelumnya, posting sumber dengan link asli.
- `interrupt()` sebelum laporan dipublikasikan: operator meninjau draf di UI, mengoreksi/menghapus event yang salah, lalu menyetujui → laporan disimpan ke tabel `reports` (periode, isi markdown, status draft/approved, disetujui_oleh).
- API: `GET /reports`, `GET /reports/{id}`, `POST /reports/{id}/approve`, `GET /reports/{id}.pdf` (render markdown → PDF via WeasyPrint/`md-to-pdf`).
- Web: halaman "Laporan" — daftar periode, pratinjau draf, tombol setuju, unduh PDF/Markdown (cocok untuk htmx yang direncanakan).
- Pemicu: cron harian 17.00 menjalankan insight graph + `draft_report`; SocialCrawl **monitors** → webhook `POST /webhooks/socialcrawl` → ingest graph tetap boleh dipakai untuk menggantikan cron ingest. **Cohorts** (panel akun media/pemkot/BPBD) sebagai sumber cluster kedua.
- **Selesai jika:** laporan harian terbentuk otomatis 5 hari berturut, hanya berstatus approved setelah operator menyetujui, dan PDF-nya bisa diunduh dari web.

## 7. Biaya

SocialCrawl tidak berlangganan; credit sekali beli, tidak hangus, halaman kosong di-refund. 1 credit = 1 request standar; hashtag IG 5 credit; Threads search/user/comments metered ±1 credit per window.

| Paket | Harga | Credit |
|---|---|---|
| Free | $0 | 100 |
| Starter | £15 (±Rp 320 rb) | 2.500 |
| Growth | £49 (±Rp 1,05 jt) | 20.000 |
| Pro | £299 (±Rp 6,4 jt) | 150.000 |

| Fase | Credit/bulan | Paket | LLM | Infra |
|---|---|---|---|---|
| 0 (3 run/hari, IG + Threads utas) | 1.200–3.600 | Starter, habis 1–2 bulan | Qwen free; cadangan berbayar ±$1–3 | laptop + Docker |
| 2–3 (+enrich 10 event/hari, monitors, laporan) | 3.000–6.000 | Growth, tahan 3–6 bulan | ±$5–10 | VPS kecil ±Rp 100–150 rb |

## 8. Risiko

| Risiko | Mitigasi |
|---|---|
| Credit habis diam-diam (402) | log `credits.used`, `budget_guard`, saldo di web |
| Threads hanya mengekspos sebagian balasan tanpa login | terima ±20–50 balasan per utas; jangan `limit>25` |
| Model free tier tidak stabil | fallback heuristic berlabel jujur; model berbayar cadangan |
| Over-engineering sebelum data cukup | gate antar fase; Fase 2 hanya setelah ≥ 100 relevant posts nyata |
| LangGraph API berubah | pin versi; isolasi di `graph/`; loop lama tersedia sampai 1B stabil |
| Kontrak menyimpang | `core/schemas.py` satu-satunya kontrak; PR wajib lolos `uv run pytest` |

## 9. Keputusan tim

1. Beli Starter sekarang atau tunggu 100 credit habis?
2. Postgres bersama: laptop P3 (Docker) atau hosting gratis (Neon/Supabase)?
3. Relevance: tetap Qwen free atau model berbayar murah saat run harian?
4. Laporan: cukup harian, atau harian + mingguan? Format PDF saja atau juga Markdown/Docx?
5. `THREADS_REPLIES_PER_ACCOUNT`: 3 (lebih lengkap, 20 credit) atau 1 (hemat, 10 credit)?
