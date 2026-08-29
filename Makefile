.PHONY: install backend-install frontend-install lint test build dev-backend dev-frontend compose-build compose-up compose-down compose-logs health

install: backend-install frontend-install

backend-install:
	python3 -m venv backend/.venv
	backend/.venv/bin/pip install --upgrade pip
	backend/.venv/bin/pip install -e 'backend[dev]'

frontend-install:
	npm --prefix frontend install

lint:
	cd backend && .venv/bin/ruff check .
	npm --prefix frontend run lint

test:
	cd backend && .venv/bin/pytest
	npm --prefix frontend run test -- --run

build:
	npm --prefix frontend run build

dev-backend:
	cd backend && .venv/bin/uvicorn app.main:app --reload --port 8080

dev-frontend:
	npm --prefix frontend run dev

compose-build:
	docker compose build

compose-up:
	docker compose up -d

compose-down:
	docker compose down

compose-logs:
	docker compose logs -f

health:
	curl --fail --silent http://localhost:$${APP_PORT:-8080}/health

