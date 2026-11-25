# Common tasks. `make help` lists them.
.DEFAULT_GOAL := help
SHELL := /bin/bash

# Host ports come from .env (same values docker compose uses).
-include .env
POSTGRES_PORT ?= 5432
REDIS_PORT ?= 6379
S3_PORT ?= 9000
API_PORT ?= 8000

# Native dev (API/worker on your Mac, infra in Docker) talks to localhost.
LOCAL_ENV := DATABASE_URL=postgresql+psycopg://sift:sift@localhost:$(POSTGRES_PORT)/sift \
             REDIS_URL=redis://localhost:$(REDIS_PORT)/0 \
             S3_ENDPOINT_URL=http://localhost:$(S3_PORT) \
             LLM_API_BASE=http://localhost:11434 \
             LOG_JSON=false

.PHONY: help setup up down logs infra migrate dev-api dev-worker test test-unit lint fmt check clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

setup: ## Install deps, git hooks, and create .env
	@test -f .env || (cp .env.example .env && echo "Created .env — change the secrets.")
	UV_HTTP_TIMEOUT=$${UV_HTTP_TIMEOUT:-300} uv sync
	uv run pre-commit install

up: ## Run the whole stack in Docker (profile from .env)
	docker compose up --build -d
	@echo "API docs: http://localhost:8000/docs   Storage console: http://localhost:9001"

down: ## Stop the stack (keeps data)
	docker compose down

logs: ## Follow api + worker logs
	docker compose logs -f api worker

infra: ## Start only Postgres, Redis and object storage (for native dev)
	docker compose up -d postgres redis objectstore

migrate: ## Apply migrations (native dev)
	$(LOCAL_ENV) uv run alembic upgrade head
	$(LOCAL_ENV) uv run python -m sift.scripts.ensure_bucket

dev-api: ## Run the API natively with hot reload
	$(LOCAL_ENV) uv run uvicorn sift.main:create_app --factory --reload --port $(API_PORT)

dev-worker: ## Run a Celery worker natively
	$(LOCAL_ENV) uv run celery -A sift.workers.celery_app worker -Q ocr,llm,default -c 2 -n worker@%h --loglevel INFO

test-unit: ## Fast tests, no external services
	uv run pytest tests/unit -q

test: ## All tests (integration uses running infra via `make infra`)
	INTEGRATION_DATABASE_URL=postgresql+psycopg://sift:sift@localhost:$(POSTGRES_PORT)/sift_test \
	INTEGRATION_REDIS_URL=redis://localhost:$(REDIS_PORT)/15 \
	uv run pytest --cov

lint: ## Lint, type-check, architecture check
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy
	uv run lint-imports

fmt: ## Auto-format and fix
	uv run ruff format .
	uv run ruff check --fix .

check: lint test ## Everything CI runs

clean: ## Remove containers AND volumes (deletes local data)
	docker compose down -v
