PYTHON ?= python3
VENV ?= .venv
VENV_PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

.PHONY: help venv install test test-unit compile ci-smoke clean

help:
	@echo "Common commands:"
	@echo "  make venv       Create/update repo-local virtualenv"
	@echo "  make test       Run compile + pytest using repo-local virtualenv"
	@echo "  make ci-smoke   Run the same smoke checks as CI with unittest"
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
	$(VENV_PYTHON) -m pytest -q

test: compile test-unit

ci-smoke: venv
	$(VENV_PYTHON) -m py_compile scripts/*.py
	$(VENV_PYTHON) -m unittest discover -s tests -v

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache
	find scripts tests -type d -name __pycache__ -prune -exec rm -rf {} +
