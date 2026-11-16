# Orders

API for loading a CSV of orders and, later, asking read-only questions about them.

## Run the API

From this directory, with Python 3.11:

```bash
python3.11 -m venv .venv
.venv/bin/pip install -r backend/requirements-dev.txt
cd backend && ../.venv/bin/python -m uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000/api/v1/docs`. `GET /api/v1/health` returns the JSON envelope.

## Checks

```bash
make lint
make types
make test
```

`make test` refuses a database named `orders`. Point `DATABASE_URL` at `orders_test`.

Imports, the worker, and questions are not wired yet. The cleaner and the sample CSV generator are in place:

```bash
PYTHONPATH=backend .venv/bin/python -m scripts.generate_orders_csv
```
