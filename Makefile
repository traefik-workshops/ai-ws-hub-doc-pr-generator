.PHONY: test lint format help

PYTHON ?= python3
SKILLS_ROOT := plugins/hub-doc-pr-generator/skills
SKILLS := hub-doc-pr-generator release-notes-generator

help:
	@echo "make test    - run unit tests for every skill"
	@echo "make lint    - run pyflakes on every skill's scripts"
	@echo "make format  - reformat with ruff if available"

test:
	@for s in $(SKILLS); do \
		echo "== $$s =="; \
		$(PYTHON) -m unittest discover -s $(SKILLS_ROOT)/$$s/scripts/tests -t $(SKILLS_ROOT)/$$s -v || exit 1; \
	done

lint:
	@for s in $(SKILLS); do \
		echo "== $$s =="; \
		$(PYTHON) -m pyflakes $(SKILLS_ROOT)/$$s/scripts/ || true; \
	done

format:
	@for s in $(SKILLS); do \
		command -v ruff >/dev/null 2>&1 && ruff format $(SKILLS_ROOT)/$$s/scripts/ || echo "ruff not installed; skipping $$s"; \
	done
