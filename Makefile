SHELL := /bin/bash
PY := backend/.venv/bin/python
PIP := backend/.venv/bin/pip

.PHONY: help install dev api web worker test lint migrate admin clean

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

install: ## install backend + web dependencies
	python3 -m venv backend/.venv
	$(PIP) install -q --upgrade pip
	$(PIP) install -q -r backend/requirements-dev.txt
	cd web && npm install --no-audit --no-fund
	@test -f .env || cp .env.example .env
	@test -f backend/.env || cp .env.example backend/.env
	@echo "Done. Run 'make dev'."

dev: ## run api (:8000) and web (:3000)
	@trap 'kill 0' EXIT; \
	( cd backend && .venv/bin/python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 ) & \
	( cd web && BACKEND_URL=http://127.0.0.1:8000 npm run dev ) & \
	wait

api: ## api only
	cd backend && .venv/bin/python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

web: ## web only
	cd web && BACKEND_URL=http://127.0.0.1:8000 npm run dev

worker: ## background worker
	cd backend && .venv/bin/python -m app.worker

test: ## run the backend test suite
	cd backend && .venv/bin/python -m pytest -q

lint: ## ruff + typescript
	cd backend && .venv/bin/python -m ruff check app tests scripts || true
	cd web && npx tsc --noEmit

migrate: ## apply migrations
	cd backend && .venv/bin/alembic upgrade head

admin: ## create the first admin account
	cd backend && .venv/bin/python -m scripts.create_admin

clean:
	rm -rf backend/armx.db backend/armx.db-wal backend/armx.db-shm backend/var web/.next
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
