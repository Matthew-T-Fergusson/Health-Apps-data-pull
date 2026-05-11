PYTHON ?= python3
VENV ?= .venv
VENV_PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

.PHONY: help venv install test test-unit compile lint typecheck quality ci-smoke test-db-up test-db-down test-integration clean

help:
	@echo "Common commands:"
	@echo "  make venv       Create/update repo-local virtualenv"
	@echo "  make test       Run compile + pytest using repo-local virtualenv"
	@echo "  make lint       Run ruff lint checks"
	@echo "  make typecheck  Run mypy type checks"
	@echo "  make quality    Run lint + typecheck"
	@echo "  make ci-smoke   Run the same smoke checks as CI with unittest"
	@echo "  make test-integration  Run isolated Docker/Postgres integration tests"
	@echo "  make clean      Remove local caches"

$(VENV_PYTHON):
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt -r requirements-dev.txt

venv: $(VENV_PYTHON)

install: venv
	$(PIP) install -r requirements.txt -r requirements-dev.txt

compile: venv
	$(VENV_PYTHON) -m compileall -q scripts tests

test-unit: venv
	$(VENV_PYTHON) -m pytest -q tests/test_*.py

test: compile test-unit

lint: venv
	$(VENV_PYTHON) -m ruff check scripts tests

typecheck: venv
	$(VENV_PYTHON) -m mypy scripts

quality: lint typecheck

ci-smoke: venv
	$(VENV_PYTHON) -m py_compile scripts/*.py
	$(VENV_PYTHON) -m unittest discover -s tests -v

.env.test:
	cp .env.test.example .env.test

test-db-up: .env.test
	docker compose up -d postgres-test
	@echo "Waiting for isolated test Postgres on port 55432..."
	@for i in $$(seq 1 30); do \
		if docker exec health-pull-test-postgres psql -U health_test -d health_ops_test -c 'select 1' >/dev/null 2>&1; then \
			echo "Test Postgres is ready"; \
			exit 0; \
		fi; \
		sleep 1; \
	done; \
	echo "Timed out waiting for test Postgres"; \
	docker compose logs postgres-test; \
	exit 1

test-db-down:
	docker compose down -v

test-integration: venv test-db-up
	APP_ENV=test ENV_PATH=.env.test $(VENV_PYTHON) -m pytest -q tests/integration

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache
	find scripts tests -type d -name __pycache__ -prune -exec rm -rf {} +
