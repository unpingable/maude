SHELL := /bin/bash
PY ?= python3

.PHONY: test lint fmt ci

test:
	$(PY) -m pytest tests/ -q

lint:
	$(PY) -m ruff check .

fmt:
	$(PY) -m ruff format .

ci: lint test
