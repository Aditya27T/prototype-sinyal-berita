# Plan Kerja 1 Hari, 1 Orang — Telinga Digital

Turunan dari `ROADMAP.md`, dipadatkan menjadi **satu fase, satu orang, satu hari** (09.00–17.00). Tidak ada kontrak antar-orang yang perlu dibekukan; urutan di bawah dikerjakan berurutan, setiap langkah menghasilkan sesuatu yang bisa dijalankan sebelum lanjut.

## Target (demo 16.45)

```
Threads utas (5 akun berita + balasan) + Threads tag (#malang, #beritamalang, …) + IG
   →  ingest (loop yang ada)  →  relevance (yang ada)
   →  insight graph (LangGraph serial): cluster (rule) → isu + urgency (1 panggilan LLM) → draft laporan (template)
   →  web: halaman Event + halaman Laporan (markdown, tombol Setujui)
```

**Masuk:** collector Threads akun + balasan + tag; skema `events`/`event_posts`/`reports` + `posts.parent_post_id`; `ai/insight.py` dengan heuristic + 1 prompt LLM; `graph/insight_graph.py` serial; API `events`/`reports`; web Event + Laporan.

**Tidak masuk (tetap di ROADMAP):** `merge_clusters` LLM, taxonomy terpisah, eval/spot-check tertulis, checkpointer/resume, `Send`, MCP, PDF, cron, Postgres bersama, efisiensi credit IG, `clean()` khusus balasan (filter dilakukan di collector).

Prinsip: **heuristic dulu, LLM belakangan, template dulu, LLM kalau sisa waktu.** Tiap langkah punya versi tanpa LLM supaya demo tidak bergantung pada free tier.

## Credit SocialCrawl (100 gratis)

Satu run nyata ±25–40 credit (Threads akun 5 + balasan ≤ 10 + tag 4–8 + IG 10–15). **Hanya 1 run nyata** (11.30); sisanya snapshot. `THREADS_REPLIES_PER_ACCOUNT=2`. Kalau saldo di bawah 40 sebelum run → beli Starter £15 atau turunkan replies ke 1.

## Threads tag — cara ambilnya

SocialCrawl tidak punya endpoint feed tag Threads; topic tag hanya ada di `post.ext.topic_tag` pada hasil `threads/search`. Jadi `source_type: tag` = `threads/search` dengan `query=<tag>`, `start_date=end_date=hari ini`, `limit=20`, lalu **saring di klien: simpan hanya posting dengan `ext.topic_tag == tag`** (case-insensitive, tanpa `#`). Posting yang hanya menyebut kata "malang" tanpa tag dibuang. Tag awal: `malang`, `beritamalang`, `malangraya`, `infomalang`; sesuaikan setelah melihat `ext.topic_tag` di snapshot. 1–2 credit per tag.

## Skema dan kontrak (ditulis di langkah 1)

```python
# core/schemas.py
class EventDraft(BaseModel):
    key: str                      # f"{location}|{issue_hint}|{date}"
    location: str | None
    issue_hint: str | None
    post_ids: list[str]
    sample_texts: list[str]       # ≤ 5 teks untuk LLM

class EventInsight(BaseModel):    # satu panggilan LLM mengisi keduanya
    issue_class: str              # dari daftar 12 kelas di prompt
    urgency: int                  # 1–5
    rationale: str
```

`database/models.py` (`create_all`, tanpa migrasi): `posts.parent_post_id` nullable; `events` (id, key, location, issue_class, urgency, rationale, window_date, created_at); `event_posts` (event_id, post_id); `reports` (id, period, body_md, status `draft|approved`, approved_at).

`ai/insight.py`: `analyze_event(event: EventDraft) -> EventInsight` (heuristic → LLM, pola sama dengan `analyze()`), `draft_report(events: list[dict], period: str) -> str` (template markdown).

## Urutan kerja

| Jam | Langkah | Hasil yang bisa dicek sebelum lanjut |
|---|---|---|
| **09.00–09.30** | **1. Fondasi.** Branch `feature/insight-day`. `core/schemas.py`: `EventDraft`, `EventInsight`. `database/models.py`: `parent_post_id`, `events`, `event_posts`, `reports`. Hapus `signyal.db`, `init_db()`. | `sqlite3 signyal.db .tables` menampilkan 3 tabel baru |
| **09.30–11.30** | **2. Collector Threads** di `collectors/source_one.py`: `_fetch_threads_user_posts(handle)` (`since` hari ini), `_fetch_threads_replies(url)`, `_reply_to_post` (`raw_data.kind="reply"`, `parent_post_id`, `parent_url`; buang teks < 15 karakter / `flags.deleted`), `_fetch_threads_tag(tag)` (search + saring `topic_tag`, `kind="tag"`, `source_query="#tag"`), dispatch `_source_posts` per `(platform, source_type)`, hapus `_fetch_threads_search` dan cabang `search`. `config/sources.yaml`: hapus search, tambah 5 akun `replies: true` + 4 tag. Snapshot `threads:account:*`, `threads:replies:*`, `threads:tag:*`. `pipeline/run.py`: isi `PostRow.parent_post_id` dari `raw_data`. Test offline `tests/test_threads_collector.py` (mapper reply, saringan tag, dispatch dengan fetcher di-monkeypatch). | `uv run pytest -q` hijau; `_source_posts` dengan fetcher palsu mengembalikan induk + balasan |
| **11.30–12.00** | **3. Run nyata #1** (`make pipeline`, ±30 credit). Cek jumlah `kind='reply'`, `kind='tag'`, `parent_post_id`; cek `ext.topic_tag` di snapshot dan perbaiki daftar tag bila perlu. Run kedua dari snapshot → `inserted=0`. | `select kind, count(*) from posts ... group by json_extract(raw_data,'$.kind')` berisi root/reply/tag |
| **12.00–12.30** | Istirahat / buffer langkah 2–3. | |
| **12.30–14.00** | **4. Insight.** `ai/insight.py`: `analyze_event` heuristic (kelas dari dict `issue_hint→kelas`, urgency `min(5, 1 + n_posts//3)`), lalu LLM via helper yang dipakai bersama `_analyze_openrouter` (prompt `ai/prompts/event_insight.txt`: 12 kelas isu + rubric urgency 1–5, output JSON), fallback heuristic. `draft_report` template markdown (judul periode, tabel event urut urgency, isu dominan per lokasi, link sumber). `graph/state.py`, `graph/insight_graph.py` (`StateGraph` serial: `fetch_relevant → cluster_rule → analyze_events → persist → draft_report`; `cluster_rule` = group by (location, issue_hint, hari), balasan ikut induknya via `parent_post_id`), `graph/run.py insight --date today`. Jalankan pada data run #1. | `select count(*) from events` ≥ 3 dengan `issue_class` + `urgency`; 1 baris `reports` status draft; `tests/test_insight.py` (cluster_rule + heuristic) hijau |
| **14.00–15.00** | **5. API** di `api/main.py`: `GET /events?date=`, `GET /events/{id}` (dengan posting pendukung), `GET /reports`, `GET /reports/{id}`, `POST /reports/{id}/approve`; `/posts/all` mengembalikan `kind`, `parent_url`. | `curl localhost:8000/events` dan `/reports` berisi data; approve mengubah status |
| **15.00–16.15** | **6. Web** di `web/src/`: tab/halaman **Event** (kartu urgency 1–5, isu, lokasi, posting pendukung + balasan, link sumber), **Laporan** (daftar, render markdown, tombol Setujui, status), label "balasan @handle" di kartu post. Tanpa library baru selain renderer markdown ringan (mis. `marked`). | Klik Setujui di browser → status approved tanpa reload server |
| **16.15–16.45** | **7. Rapikan.** `make demo` = pipeline (snapshot) → `graph.run insight` → `make web`. README: alur baru + perintah. Commit, PR. Jalankan demo penuh sekali dari awal. | Demo end-to-end lolos sekali tanpa intervensi manual |
| **16.45–17.00** | **Demo.** | |

## Definisi selesai

1. `make pipeline` memasukkan posting induk + balasan dari ≥ 3 akun Threads (`kind='reply'` > 0, `parent_post_id` terisi) dan posting ber-tag (`kind='tag'`, semua `topic_tag` cocok).
2. `python -m graph.run insight --date today` membentuk ≥ 3 event dengan `issue_class` + `urgency` dan 1 `reports` draft.
3. Web menampilkan Event dan Laporan; Setujui → approved.
4. `uv run pytest -q` hijau.

## Pagar

- **Jam 14.00 insight harus jalan dengan heuristic.** Kalau belum, langkah 5–6 dikerjakan dengan data heuristic; LLM menyusul kalau ada waktu.
- LangGraph menyulitkan > 30 menit → panggil node berurutan sebagai fungsi biasa; bungkus ke `StateGraph` di langkah 7 kalau sempat. Hasil demo sama.
- LLM 429/gagal → heuristic, demo tidak berhenti.
- Akun Threads belum posting hari ini → `since` dimundurkan 2 hari untuk demo.
- Tag hasil saring 0 → ganti daftar tag dari `ext.topic_tag` snapshot, jangan longgarkan ke keyword.
- Langkah 6 kehabisan waktu → halaman Laporan dulu (lebih kecil), Event tampil sebagai tabel polos.
- Tidak menambah fitur di luar daftar "Masuk" sebelum 16.15.

## Yang digeser ke hari berikutnya (urutan)

1. `merge_clusters` LLM dan taxonomy terpisah; spot-check event tertulis di `docs/EVAL.md`.
2. Efisiensi credit IG (`since`/`stop_at_id`/`seen`) + log `credits.used` ke tabel `runs`.
3. Eval 100 label + precision/recall; `model_version` jujur saat fallback.
4. LangGraph ingest (RetryPolicy, Send, checkpointer, resume).
5. MCP di insight: `budget_guard`, `enrich_cluster`, `pull_comments`, `cross_platform_check`.
6. PDF laporan, cron 17.00, Postgres bersama, monitors/cohorts.
