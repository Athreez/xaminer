# Run from the repository root. Requires uv (backend) and npm (frontend).
.PHONY: setup check lint typecheck test format \
        backend-lint backend-typecheck backend-test frontend-lint frontend-typecheck frontend-test \
        up down ps logs platform-admin api-client \
        create-institution create-admin invite-user list-institutions list-languages

# Regenerate the frontend's typed API client after changing backend endpoints. Commit the result.
api-client:
	cd backend && uv run python -m app.export_openapi ../frontend/src/api/openapi.json
	cd frontend && npm run api:types

COMPOSE = docker compose -f deploy/docker-compose.yml

# Hide Docker Desktop's "What's next: Debug this with Gordon" advert after failed commands.
export DOCKER_CLI_HINTS = false

ADMIN_CLI = $(COMPOSE) run --rm --no-deps api python -m cli

# platform-admin shortcuts (stack must be up). Values go in variables, which works the same in
# PowerShell, cmd and bash, e.g.:  make create-admin INSTITUTION="ABC College" EMAIL=a@abc.edu NAME="Asha Rao"
create-institution:
	$(ADMIN_CLI) create-institution --name "$(NAME)" --timezone "$(or $(TIMEZONE),Asia/Kolkata)"

create-admin:
	$(ADMIN_CLI) create-admin --institution "$(INSTITUTION)" --email "$(EMAIL)" --name "$(NAME)"

# ROLE is ADMIN, TEACHER or STUDENT; ROLL_NO is optional.
invite-user:
	$(ADMIN_CLI) invite-user --institution "$(INSTITUTION)" --email "$(EMAIL)" --name "$(NAME)" --role "$(ROLE)" $(if $(ROLL_NO),--roll-no "$(ROLL_NO)",)

list-institutions:
	$(ADMIN_CLI) list-institutions

list-languages:
	$(ADMIN_CLI) list-languages

# Any other platform-admin command. Avoid nested quotes here in Windows PowerShell 5.1.
platform-admin:
	$(ADMIN_CLI) $(ARGS)

up:
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) down

ps:
	$(COMPOSE) ps

logs:
	$(COMPOSE) logs -f --tail=100

setup:
	cd backend && uv sync
	cd frontend && npm install

check: lint typecheck test

lint: backend-lint frontend-lint
typecheck: backend-typecheck frontend-typecheck
test: backend-test frontend-test

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

frontend-test:
	cd frontend && npm test

format:
	cd backend && uv run ruff format . && uv run ruff check --fix .
	cd frontend && npm run format
