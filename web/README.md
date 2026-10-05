# Review UI — milik Person 3 (Bun + React, htmx menyusul)

> Cara tercepat: dari root repo cukup `make web` (setup + data + API + web sekaligus).

## Jalan cepat

```bash
cd web
bun install
bun run dev      # http://localhost:5173 → proxy /api ke FastAPI :8000
```

Pastikan API jalan dulu dari root:

```bash
uv run uvicorn api.main:app --reload --port 8000
```
