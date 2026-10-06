UV = uv
API_PORT = 8000
WEB_PORT = 5173

.PHONY: help setup pipeline pipeline-snapshot insight db-reset demo api test web

.DEFAULT_GOAL := help

help: ## daftar target make
	@echo "Telinga Digital — target make:"
	@echo "  make demo        pipeline (snapshot) -> insight -> web, untuk demo end-to-end"
	@echo "  make web         setup + data bila DB kosong + API & web, browser terbuka"
	@echo "  make setup       cek uv & bun, salin .env, uv sync, bun install"
	@echo "  make pipeline    pipeline sungguhan (collector SocialCrawl, memakai credit)"
	@echo "  make pipeline-snapshot  pipeline dari snapshot fixtures (0 credit, untuk demo)"
	@echo "  make insight     insight graph: cluster -> isu+urgency -> draf laporan"
	@echo "  make db-reset    hapus signyal.db lalu create_all"
	@echo "  make api         hanya FastAPI di :8000"
	@echo "  make test        pytest"

setup: ## cek uv & bun, siapkan .env, install deps Python + web
	@command -v uv >/dev/null 2>&1 || (echo "E: 'uv' tidak ditemukan. Pasang: curl -LsSf https://astral.sh/uv/install.sh | sh" && exit 1)
	@command -v bun >/dev/null 2>&1 || (echo "E: 'bun' tidak ditemukan. Pasang: curl -fsSL https://bun.sh/install | bash" && exit 1)
	@test -f .env || { cp .env.example .env; echo ".env dibuat dari .env.example"; }
	uv sync --extra dev
	cd web && bun install

pipeline: ## collect -> clean -> dedup -> insert -> analyze (memakai credit SocialCrawl)
	uv run python -m pipeline.run --limit 20

pipeline-snapshot: ## pipeline dari snapshot fixtures, tanpa credit SocialCrawl
	SOCIALCRAWL_API_KEY= uv run python -m pipeline.run --limit 20

insight: ## insight graph (cluster -> isu+urgency -> draf laporan)
	uv run python -m graph.run insight --date today

db-reset: ## hapus DB lalu create_all (data hilang)
	rm -f signyal.db
	uv run python -c "from database.connection import init_db; init_db(); print('db dibuat ulang')"

demo: pipeline-snapshot insight web ## demo end-to-end: pipeline snapshot -> insight -> web

api: ## hanya FastAPI (tanpa web)
	uv run uvicorn api.main:app --reload --port $(API_PORT)

test: ## pytest
	uv run pytest -q

web: setup ## setup + isi data bila kosong + API & web + buka browser
	@n=$$(uv run python -c "from sqlalchemy import func, select; from database.connection import init_db, get_session_factory; from database.models import PostRow; init_db(); s = get_session_factory()(); print(s.execute(select(func.count()).select_from(PostRow)).scalar()); s.close()"); \
	if [ "$$n" = "0" ]; then \
		echo "DB kosong - mengisi data contoh via pipeline..."; \
		$(MAKE) pipeline-snapshot; \
	else \
		echo "DB sudah berisi $$n posts - lewati pipeline (refresh manual: make pipeline)"; \
	fi
	@trap 'kill 0' INT TERM EXIT; \
	uv run uvicorn api.main:app --port $(API_PORT) & \
	for i in $$(seq 1 15); do \
		if curl -sf http://localhost:$(API_PORT)/health >/dev/null; then break; fi; \
		sleep 1; \
	done; \
	curl -sf http://localhost:$(API_PORT)/health >/dev/null || { echo "E: API tidak merespons di :$(API_PORT)"; exit 1; }; \
	cd web && bun run dev --open