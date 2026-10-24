# Run from the repository root. Requires uv (backend) and npm (frontend).
.PHONY: setup check lint typecheck test format \
        backend-lint backend-typecheck backend-test frontend-lint frontend-typecheck

setup:
	cd backend && uv sync
	cd frontend && npm install

check: lint typecheck test

lint: backend-lint frontend-lint
typecheck: backend-typecheck frontend-typecheck
test: backend-test

backend-lint:
	cd backend && uv run ruff check . && uv run ruff format --check .

backend-typecheck:
	cd backend && uv run mypy

backend-test:
	cd backend && uv run pytest -q

frontend-lint:
	cd frontend && npm run lint && npm run format:check

frontend-typecheck:
	cd frontend && npm run typecheck

format:
	cd backend && uv run ruff format . && uv run ruff check --fix .
	cd frontend && npm run format
