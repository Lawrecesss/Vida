# Thin wrapper over docker compose for the demo app (backend/ + frontend/).
# The SDK itself is not containerised — it is a library; `make test` and
# `make lint` run against the local .venv, exactly as CI does.

COMPOSE ?= docker compose
DEV     := -f compose.yaml -f compose.dev.yaml
PY      := ./.venv/bin/python

.DEFAULT_GOAL := help
.PHONY: help build up dev down restart logs ps shell-backend shell-frontend clean test lint

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

build: ## Build both images
	$(COMPOSE) build

up: ## Build and start both services in the background
	$(COMPOSE) up -d --build
	@echo "backend  http://localhost:$${BACKEND_PORT:-8000}/health"
	@echo "frontend http://localhost:$${FRONTEND_PORT:-3000}"

dev: ## Start both services in the foreground with hot reload
	$(COMPOSE) $(DEV) up --build

down: ## Stop both services, keeping uploaded media
	$(COMPOSE) down

restart: ## Recreate both services
	$(COMPOSE) up -d --force-recreate

logs: ## Follow logs from both services
	$(COMPOSE) logs -f

ps: ## Show service status
	$(COMPOSE) ps

shell-backend: ## Shell into the running backend
	$(COMPOSE) exec backend bash

shell-frontend: ## Shell into the running frontend
	$(COMPOSE) exec frontend sh

clean: ## Stop everything and delete the uploads volume
	$(COMPOSE) $(DEV) down -v --remove-orphans

test: ## Run the SDK test suite locally
	$(PY) -m pytest

lint: ## Run ruff over the repo
	$(PY) -m ruff check .
