.PHONY: test lint format help

PYTHON ?= python3

help:
	@echo "make test    - run unit tests"
	@echo "make lint    - run pyflakes on scripts/"
	@echo "make format  - reformat with ruff if available"

test:
	$(PYTHON) -m unittest discover -s scripts/tests -t . -v

lint:
	$(PYTHON) -m pyflakes scripts/ || true

format:
	@command -v ruff >/dev/null 2>&1 && ruff format scripts/ || echo "ruff not installed; skipping"
