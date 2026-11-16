.PHONY: test test-all lint types hooks csv up

PYTHON ?= .venv/bin/python

test:
	cd backend && ../$(PYTHON) -m pytest -m "not nats"

test-all:
	cd backend && ../$(PYTHON) -m pytest -m "not nats" --cov=app --cov=worker --cov-fail-under=90

lint:
	$(PYTHON) -m ruff check backend worker scripts

types:
	$(PYTHON) -m mypy

hooks:
	$(PYTHON) -m pre_commit install --hook-type pre-commit --hook-type pre-push

csv:
	PYTHONPATH=backend $(PYTHON) -m scripts.generate_orders_csv

up:
	docker compose --env-file infra/.env -f infra/compose.yaml up --build
