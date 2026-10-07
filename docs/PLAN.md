# Telinga Digital — Plan Prototype 1 Hari

Sumber: `Telinga_Digital_PRD_Prototype_1_Hari.pdf` (root repo). Dokumen ini merangkum PRD menjadi pembagian kerja dan kontrak antar-modul supaya tiga orang bisa mulai paralel.

## 1. Tujuan

Dari sekumpulan posting publik mentah, sistem menghasilkan **Relevant Posts Malang Raya** yang masuk akal dan tetap punya link sumber asli.

```
Source publik → Collector → Raw Posts → Cleaning + Dedup → Clean Posts
             → AI Relevance Filter → Relevant / Not Relevant → Database → Review UI
```

**In scope:** 1 source publik, seed lokasi di config, collector sederhana, normalisasi + dedup, LLM relevance filter, PostgreSQL, review UI sederhana, link sumber asli.

**Out of scope:** urgency score, sentiment, clustering, deteksi bot, analisis gambar/video, alert Telegram/WhatsApp, dashboard eksekutif, training model, multi-platform.

Jika satu source belum stabil, jangan menambah source kedua. Keberhasilan hari pertama adalah pipeline selesai, bukan coverage.

## 2. Siapa pegang folder mana

| Orang | Folder | Yang dihasilkan |
|---|---|---|
| Person 1 — Crawler/Data | `collectors/`, `processing/`, `config/` | Clean Posts berformat `Post` |
| Person 2 — AI/Relevance | `ai/`, `ai/prompts/` | `AnalysisResult` untuk tiap Post |
| Person 3 — Backend/Integration | `pipeline/`, `database/`, `api/`, `web/` | Prototype end-to-end |
| Bersama | `core/`, `fixtures/`, `tests/`, `docs/` | Kontrak data, data contoh, test |

```
signyal-prototype/
├── core/          # kontrak data bersama (schemas.py)
├── collectors/    # Person 1 — base.py, source_one.py
├── processing/    # Person 1 — normalize.py, deduplicate.py
├── config/        # Person 1 — sources.yaml, locations.yaml
├── ai/            # Person 2 — relevance.py
│   └── prompts/   # Person 2 — file prompt
├── fixtures/      # posting contoh untuk tes tanpa crawler
├── pipeline/      # Person 3 — script yang merangkai semua modul
├── database/      # Person 3 — models.py, connection.py
├── api/           # Person 3 — FastAPI
├── web/           # Person 3 — review UI (Bun + React, htmx menyusul)
├── tests/
└── docs/
```

Folder masih kosong. Aturan sederhana: kerjakan hanya di folder sendiri; perubahan di `core/` harus disepakati bertiga.

## 3. Kontrak data

Ini yang harus disepakati sebelum mulai (slot 09.00–10.00). Akan dituangkan sebagai model Pydantic di `core/schemas.py`.

### 3.1 Post — keluaran Person 1, masukan Person 2

```json
{
  "id": "uuid",
  "platform": "threads",
  "platform_post_id": "12345",
  "url": "https://...",
  "text": "Sawojajar banjir maneh sam",
  "author": "public_account",
  "published_at": "2026-10-05T10:00:00+07:00",
  "collected_at": "2026-10-05T10:03:00+07:00",
  "source_query": "sawojajar",
  "raw_data": {}
}
```

- `platform` dan `text` wajib. `platform_post_id`, `url`, `author`, `published_at` boleh null jika sumber tidak menyediakan.
- `raw_data` berisi respons asli dari sumber, apa adanya.

### 3.2 AnalysisResult — keluaran Person 2

```json
{
  "is_relevant": true,
  "relevance_score": 0.92,
  "location": "Sawojajar",
  "location_confidence": 0.85,
  "issue_hint": "banjir",
  "reason": "Posting membahas genangan jalan di Sawojajar"
}
```

- Skor dan confidence bernilai 0–1.
- `location` null jika model tidak cukup yakin.

### 3.3 Signature fungsi antar-modul

| Modul | Fungsi | Pemilik |
|---|---|---|
| `collectors/source_one.py` | `collect(query: str, limit: int) -> list[Post]` | Person 1 |
| `processing/normalize.py` | `clean(post: Post) -> Post \| None` (None = dibuang) | Person 1 |
| `processing/deduplicate.py` | `dedup_key(post: Post) -> str` | Person 1 |
| `ai/relevance.py` | `analyze(post: Post) -> AnalysisResult` | Person 2 |

Pipeline Person 3 hanya memanggil empat fungsi ini. Selama signature dipenuhi, isi di dalamnya bebas.

## 4. Tugas per orang

### Person 1 — Crawler/Data

1. Pilih **satu** source publik yang paling realistis; utamakan API resmi atau akses publik. Tidak bypass login, CAPTCHA, akun privat, atau proteksi platform.
2. Isi `config/sources.yaml` (platform, source_type, source_value, active) dan `config/locations.yaml` (seed lokasi: Sawojajar, Dinoyo, Suhat, Batu, Kepanjen, dst.). Lokasi tidak boleh di-hardcode di logic.
3. Tulis collector yang mengembalikan `list[Post]`. Stack: `httpx`, `BeautifulSoup`; Playwright hanya sebagai fallback.
4. `clean()`: rapikan whitespace, buang posting kosong.
5. `dedup_key()`: `platform + platform_post_id`; jika ID tidak ada, pakai hash dari URL, lalu hash dari text.
6. Simpan 20–50 posting asli ke `fixtures/` secepat mungkin supaya Person 2 bisa menguji prompt dengan data nyata.

Selesai jika: sekitar 100 posting berformat `Post` bisa dihasilkan, dan menjalankan ulang tidak menghasilkan duplikat.

### Person 2 — AI/Relevance

1. Pilih provider LLM (PRD tidak mengunci). Tanpa training atau fine-tuning.
2. Tulis prompt di `ai/prompts/` dengan aturan:
   - output wajib JSON valid sesuai `AnalysisResult`;
   - Relevant = konteks Malang Raya **dan** isu publik;
   - iklan, promosi, jual-beli = Not Relevant walaupun lokasinya benar;
   - jangan menyebut lokasi jika tidak cukup yakin;
   - `issue_hint` boleh kasar, belum perlu taxonomy.
3. Tulis `analyze(post)` yang memanggil LLM dan memvalidasi hasilnya; tangani JSON tidak valid dan timeout.
4. Uji dengan 20–50 posting dan cek manual. Mulai dari empat contoh PRD:

| Posting | Harapan |
|---|---|
| Sawojajar banjir maneh sam, banyune wes nutup dalan | Relevant — Sawojajar — banjir |
| Kos murah dekat Dinoyo, hubungi WA | Not Relevant — komersial |
| Macet parah arah Suhat dari tadi | Relevant — Suhat — kemacetan |
| Promo makanan Batu diskon 30 persen | Not Relevant — promosi |

Selesai jika: setiap posting mendapat label, dan spot-check menunjukkan precision sekitar 80% (indikatif).

### Person 3 — Backend/Integration

1. PostgreSQL + tabel:
   - `sources`: id, platform, source_type, source_value, active, created_at
   - `posts`: id, source_id, platform, platform_post_id, url, text, author, published_at, collected_at, raw_data — `UNIQUE(platform, platform_post_id)`
   - `post_analysis`: id, post_id, is_relevant, relevance_score, location, location_confidence, issue_hint, reason, model_version, processed_at
   - Relevant Posts = `posts JOIN post_analysis WHERE is_relevant = true`, tanpa tabel terpisah.
2. Pipeline: collect → clean → dedup → insert → analyze → simpan analysis. Idempotent: posting yang sudah ada tidak diproses ulang.
3. FastAPI: endpoint baca relevant posts.
4. Review UI di `web/` dengan Bun + React (htmx menyusul): daftar relevant posts dan link ke URL asli.
5. Demo end-to-end + README.

## 5. Jadwal

| Waktu | Person 1 | Person 2 | Person 3 |
|---|---|---|---|
| 09.00–10.00 | Sepakati source + schema | Sepakati output AI | DB schema + repo setup |
| 10.00–12.00 | Build collector | Build relevance prompt | PostgreSQL + pipeline skeleton |
| 12.00–13.00 | Cleaning + dedup | Test sample real posts | Insert/read endpoint |
| 13.00–15.00 | Stabilize collector | Improve prompt & JSON | Integrasi crawler + AI + DB |
| 15.00–16.30 | Support integration | Validate results | Build review UI |
| 16.30–17.30 | Fix bug | Manual spot-check | Demo end-to-end & README |

## 6. Acceptance criteria

| ID | Kriteria | Pemilik |
|---|---|---|
| AC-01 | Minimal satu source publik menghasilkan data | P1 |
| AC-02 | Sekitar 100 posts masuk pipeline jika sumber memungkinkan | P1, P3 |
| AC-03 | Duplicate tidak diproses berulang | P1, P3 |
| AC-04 | Setiap clean post mendapat Relevant / Not Relevant | P2, P3 |
| AC-05 | Relevant Posts dapat dilihat di review UI | P3 |
| AC-06 | URL sumber asli tersedia bila sumber menyediakannya | P1, P3 |
| AC-07 | Spot-check manual layak, precision indikatif sekitar 80% | P2 |

**Definition of done:** jalankan crawler → raw posts masuk → cleaning + dedup → AI memproses → Relevant Posts tersimpan → operator melihat hasil dan membuka link asli, didemokan end-to-end pada hari yang sama.

## 7. Risiko

| Risiko | Mitigasi |
|---|---|
| Akses platform berubah atau terbatas | Satu source paling realistis; API resmi bila ada |
| Crawler tidak stabil | Browser automation bukan ketergantungan utama demo; `fixtures/` sebagai cadangan |
| AI salah klasifikasi | Structured output + spot-check 20–50 posts |
| Waktu terlalu pendek | Tidak menambah fitur sebelum flow utama selesai |
| Data sensitif | Hanya data publik |

## 8. Langkah berikutnya

1. Sepakati kontrak di bagian 3, lalu tulis `core/schemas.py`.
2. Siapkan `pyproject.toml` (Python 3.12, `uv`), `.env.example`, `.gitignore`, dan `git init`.
3. Person 1 dan 2 mulai di folder masing-masing; Person 3 mulai dari `database/` dan `pipeline/`.

## 9. Lanjutan

Roadmap setelah prototype 1 hari ada di `ROADMAP.md`.
