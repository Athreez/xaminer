# Run from the repository root. Requires uv (backend) and npm (frontend).
.PHONY: setup check lint typecheck test format \
        backend-lint backend-typecheck backend-test frontend-lint frontend-typecheck frontend-test \
        up down ps logs platform-admin api-client \
        create-institution create-admin invite-user list-institutions list-languages \
        runners runners-check sandbox-check demo-https demo-data

# Regenerate the frontend's typed API client after changing backend endpoints. Commit the result.
api-client:
	cd backend && uv run python -m app.export_openapi ../frontend/src/api/openapi.json
	cd frontend && npm run api:types

COMPOSE = docker compose -f deploy/docker-compose.yml

# Language runner images (runners/<key>/Dockerfile): build, then load into sandbox-docker, where
# student code runs (stack must be up; NO_LOAD=1 only builds). runners-check runs a hello-world
# in each, here and in the sandbox, with the sandbox's container restrictions.
runners:
	cd backend && uv run python ../runners/build.py $(if $(NO_LOAD),--no-load,)

runners-check:
	cd backend && uv run python ../runners/smoke_test.py
	cd backend && uv run python ../runners/smoke_test.py --sandbox

# The sandbox on real containers: the profile as the engine applies it, and programs that try to
# escape, flood output, fork, allocate or loop (needs `make runners` first; uses this machine's Docker).
sandbox-check: export SANDBOX_TESTS = 1
sandbox-check:
	cd backend && uv run pytest -q -p no:randomly tests/sandbox

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

# The demo (README, "Run the demo"): HTTPS for this laptop's Wi-Fi address, then demo data.
demo-https:
	python scripts/demo_https.py $(if $(IP),--ip $(IP),)

demo-data:
	cd backend && uv run --with requests python ../scripts/demo_data.py

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

# Test files run in parallel (one file stays on one worker); tests marked serial run after.
backend-test:
	cd backend && uv run pytest -q -n auto --maxprocesses 8 --dist loadfile -m "not serial" 		&& uv run pytest -q -m serial

frontend-lint:
	cd frontend && npm run lint && npm run format:check

frontend-typecheck:
	cd frontend && npm run typecheck

frontend-test:
	cd frontend && npm test

format:
	cd backend && uv run ruff format . && uv run ruff check --fix .
	cd frontend && npm run format
