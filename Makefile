.PHONY: test lint types hooks

PYTHON ?= .venv/bin/python

test:
	cd backend && ../$(PYTHON) -m pytest

lint:
	$(PYTHON) -m ruff check backend worker scripts

types:
	$(PYTHON) -m mypy

hooks:
	$(PYTHON) -m pre_commit install --hook-type pre-commit --hook-type pre-push
