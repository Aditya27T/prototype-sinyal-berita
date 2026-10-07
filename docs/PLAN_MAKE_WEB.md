# `make web` — satu perintah untuk melihat review UI

## Context

Saat ini melihat web butuh 5 langkah manual di 2 terminal (salin `.env`, `uv sync`, jalankan pipeline, jalankan uvicorn, `bun install && bun run dev`). Person 1 dan 2 yang baru clone repo harus bisa cukup mengetik `make web` dan langsung melihat halaman review berisi data. Belum ada `Makefile` di repo.

## Perubahan

### 1. `Makefile` baru di root

| Target | Yang dilakukan |
|---|---|
| `make web` | setup → isi data jika DB kosong → jalankan API + web bersamaan → buka browser |
| `make setup` | cek `uv` dan `bun` ada; salin `.env.example` → `.env` jika belum ada; `uv sync --extra dev`; `bun install` di `web/` |
| `make pipeline` | `uv run python -m pipeline.run --limit 20` |
| `make api` | hanya FastAPI (`uvicorn api.main:app --reload --port 8000`) |
| `make test` | `uv run pytest -q` |
| `make help` | daftar target (target default) |

Detail `make web`:

1. Bergantung pada `setup`, jadi aman dijalankan di clone baru maupun berulang (`uv sync` dan `bun install` cepat jika sudah terpasang).
2. **Isi data hanya jika tabel `posts` kosong** — one-liner Python yang memakai `init_db` dan `get_session_factory` dari `database/connection.py`, lalu memanggil `pipeline.run`. Alasannya: begitu collector asli Person 1 masuk, `make web` tidak boleh crawling ulang setiap kali dibuka. Untuk menyegarkan data pakai `make pipeline`.
3. Jalankan uvicorn di background dan Vite di foreground dalam satu shell, dengan `trap 'kill 0' INT TERM EXIT` supaya **Ctrl+C mematikan keduanya** (tidak ada uvicorn yatim yang menahan port 8000).
4. Tunggu `GET /health` merespons (maks ±15 detik) sebelum Vite dimulai, supaya halaman pertama tidak menampilkan error "Gagal memuat".
5. Vite dijalankan dengan `--open` sehingga browser langsung terbuka di `http://localhost:5173`.

Port tetap 8000 (API) dan 5173 (web), sesuai proxy di `web/vite.config.js`. Jika `uv` atau `bun` tidak ditemukan, `make` berhenti dengan pesan cara memasangnya.

### 2. `README.md`

Tambahkan bagian singkat "Cara tercepat" di atas langkah manual:

```bash
make web      # setup + data contoh + API + web, browser terbuka otomatis
```

Langkah manual yang sudah ada dipertahankan sebagai rujukan.

### 3. `web/README.md`

Satu baris yang menunjuk ke `make web` dari root.

## Tidak diubah

`api/`, `pipeline/`, `web/src/`, `vite.config.js`, `package.json`.

## Verifikasi

```bash
make help                 # daftar target tampil
make web                  # browser terbuka; 4 angka ringkasan dan kartu posting terisi
# Ctrl+C, lalu:
lsof -i :8000 -i :5173    # kosong — kedua proses sudah mati
mv signyal.db /tmp/ && make web   # DB kosong → pipeline jalan otomatis, data muncul lagi
make test                 # test yang ada tetap hijau
```

---
**Status: selesai** — diimplementasikan di commit `c82b09e` (`make web`).
