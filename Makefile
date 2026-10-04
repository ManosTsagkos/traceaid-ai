.DEFAULT_GOAL := help

.PHONY: help install install-dev run test test-unit test-integration test-browser demo coverage lint format format-check typecheck audit check docker-build docker-up docker-down clean

help: ## Show available commands
	@awk 'BEGIN {FS = ":.*## "; printf "TraceAid AI commands:\n"} /^[a-zA-Z_-]+:.*?## / {printf "  %-18s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install: ## Install the application
	python -m pip install .

install-dev: ## Install application and development tools
	python -m pip install -e ".[dev]"

run: ## Start the development server with reload
	uvicorn traceaid.main:app --reload --host 127.0.0.1 --port 8000

test: ## Run the complete test suite
	pytest

test-unit: ## Run unit tests
	pytest tests/unit

test-integration: ## Run integration tests
	pytest tests/integration

demo: ## Build the prepared GitHub Pages demo
	python -m traceaid.static_demo --output site

test-browser: demo ## Run browser checks (requires npm ci and Playwright Chromium)
	npm test

coverage: ## Build an HTML coverage report
	pytest --cov-report=html

lint: ## Run the linter
	ruff check .

format: ## Format source and tests
	ruff format .
	ruff check . --fix

format-check: ## Verify formatting without editing files
	ruff format --check .

typecheck: ## Run static type checking
	mypy src

audit: ## Check Python dependencies for known vulnerabilities
	pip-audit

check: lint format-check typecheck test ## Run the Python core checks from CI

docker-build: ## Build the container image
	docker compose build

docker-up: ## Start the containerized app
	docker compose up --build

docker-down: ## Stop the containerized app
	docker compose down

clean: ## Remove local Python build and test artefacts
	python -c "import shutil; [shutil.rmtree(p, ignore_errors=True) for p in ('build', 'dist', 'htmlcov', '.pytest_cache', '.mypy_cache', '.ruff_cache')]"
