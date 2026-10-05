# Telinga Digital — Signyal Prototype (1 Hari)

Pipeline: Source publik → Collector → Raw Posts → Cleaning + Dedup → Clean Posts → AI Relevance → DB → Review UI.
Detail pembagian kerja: `docs/PLAN.md`.

## Mulai untuk tim (clone)

```bash
git clone https://github.com/Aditya27T/prototype-sinyal-berita.git
cd prototype-sinyal-berita
cp .env.example .env
uv sync --extra dev
```

Kerja di branch masing-masing biar tidak tabrakan, contoh:

```bash
git checkout -b person-1/collector   # Person 1 — Crawler/Data
git checkout -b person-2/relevance   # Person 2 — AI/Relevance
git checkout -b person-3/backend     # Person 3 — Backend/Integration
```

Aturan folder: kerjakan hanya di folder sendiri (`docs/PLAN.md` §2).
Perubahan di `core/` harus disepakati bertiga. Jangan ubah signature fungsi di tabel Kontrak.

## Status Person 3 (Backend/Integration) — init selesai

- [x] `core/schemas.py` — kontrak `Post` + `AnalysisResult`
- [x] `database/` — SQLAlchemy models (`sources`, `posts`, `post_analysis`) + `connection.py` (Postgres utama, SQLite fallback)
- [x] `pipeline/run.py` — collect → clean → dedup → insert → analyze, idempotent
- [x] `api/main.py` — FastAPI `GET /posts/relevant`, `/posts/all`, `/health`
- [x] `web/` — Bun + React review UI (daftar relevant + link sumber asli)
- [x] `fixtures/sample_posts.json` — 12 contoh (termasuk 4 dari PRD)
- [x] `docker-compose.yml` — Postgres 16

## Cara tercepat

```bash
make web      # setup + data contoh + API + web, browser terbuka otomatis
```

Butuh `make`, `uv`, dan `bun`. Langkah manual di bawah tetap bisa dipakai sebagai rujukan.

## Cara jalan (demo end-to-end, 5 menit)

### 0. Prasyarat
Python 3.12+, `uv`, Docker (opsional utk Postgres), Bun.

### 1. Setup Python
```bash
cp .env.example .env
uv sync            # atau: uv pip install -e ".[dev]"
```

### 2. DB — pilih salah satu
```bash
# Opsi A (cepat, tanpa Docker): SQLite — default di .env
# DATABASE_URL=sqlite:///./signyal.db

# Opsi B (sesuai PLAN — Postgres):
docker compose up -d db
# lalu di .env:
# DATABASE_URL=postgresql+psycopg://signyal:signyal@localhost:5432/signyal
```

### 3. Jalankan pipeline
```bash
uv run python -m pipeline.run --limit 20
# jalankan 2x untuk buktikan idempotent (insert kedua = 0)
uv run python -m pipeline.run --limit 20
```

### 4. API
```bash
uv run uvicorn api.main:app --reload --port 8000
# buka: http://localhost:8000/posts/relevant
#      http://localhost:8000/posts/all
```

### 5. Review UI
```bash
cd web && bun install && bun run dev
# buka http://localhost:5173
```

### 6. Test
```bash
uv run pytest -q
```

## Untuk Person 1 (Crawler/Data) — mulai dari sini
- `collectors/source_one.py::collect(query, limit)` — ganti isi fixture dengan httpx/BS4.
- `processing/normalize.py::clean`, `processing/deduplicate.py::dedup_key` — lengkapi aturan.
- `config/sources.yaml`, `config/locations.yaml` — daftarkan source + seed lokasi.
- Tambah posting mentah ke `fixtures/` (target 20–50 cepat).
- Jangan ubah signature fungsi; jangan hardcode lokasi di logic.

## Untuk Person 2 (AI/Relevance) — mulai dari sini
- `ai/prompts/relevance.txt` — iterasi prompt (wajib JSON valid).
- `ai/relevance.py::analyze(post)` — ganti heuristic dengan LLM (ada hook OpenAI, tinggal lengkapi).
- Uji dengan `fixtures/sample_posts.json`, target precision ~80% (spot-check).
- Jangan ubah schema `AnalysisResult` tanpa sepakat bertiga.

## Kontrak yang dipanggil pipeline (jangan diubah signature-nya)
| Modul | Fungsi |
|---|---|
| `collectors/source_one.py` | `collect(query: str, limit: int) -> list[Post]` |
| `processing/normalize.py` | `clean(post: Post) -> Post \| None` |
| `processing/deduplicate.py` | `dedup_key(post: Post) -> str` |
| `ai/relevance.py` | `analyze(post: Post) -> AnalysisResult` |

## Definition of done (hari ini)
Crawler → raw → cleaning+dedup → AI → Relevant Posts tersimpan → operator melihat di UI + buka link asli.
