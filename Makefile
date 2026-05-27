.PHONY: test lint format help

PYTHON ?= python3
SKILL_DIR := skills/hub-doc-pr-generator

help:
	@echo "make test    - run unit tests"
	@echo "make lint    - run pyflakes on the skill scripts"
	@echo "make format  - reformat with ruff if available"

test:
	$(PYTHON) -m unittest discover -s $(SKILL_DIR)/scripts/tests -t $(SKILL_DIR) -v

lint:
	$(PYTHON) -m pyflakes $(SKILL_DIR)/scripts/ || true

format:
	@command -v ruff >/dev/null 2>&1 && ruff format $(SKILL_DIR)/scripts/ || echo "ruff not installed; skipping"
