# API

FastAPI service in `backend/app`. JSON routes return `{session_auth, errors, success, data}`.

## What exists

| Path | Role |
| --- | --- |
| `app/api/v1/health.py` | `get_health`. No body. Does not check Postgres or NATS. |
| `app/schemas/envelope.py` | `ErrorResponse` and `error_responses`. |
| `app/services/cleaning.py` | Pure CSV cleaner. Raises `CleanError` only for a bad header. |
| `app/domain/countries.py` | Canonical country names. |
| `app/core/telemetry.py` | Stdout when no OTLP endpoint is set. Tests use an in-memory exporter. |
| `app/db/models.py` | Tasks, orders, and rejections. |
| `migrations/` | Alembic. `001` creates the tables and views. `002` creates `orders_reader`. |
| `app/api/v1/imports.py` | `create_import`. Inline delivery finishes before the 202 response. |
| `app/api/v1/tasks.py` | Status, cancel, retry, rejections, and the original file. |
| `worker/handler.py` | Claims the task with `SELECT ... FOR UPDATE` and commits the orders. |
| `app/nats/publisher.py` | Publishes `orders.import` when delivery is `jetstream`. |
| `worker/main.py` | Push consumer. Queue group `orders_import_worker`. |
| `app/sql/validator.py` | One read-only SELECT. Other relations and writes are refused. |
| `app/api/v1/questions.py` | `ask_question`. Tests use the fake provider. |
| `app/providers/litellm.py` | OpenAI-compatible chat completion. The key stays in the environment. |

OpenAPI is `/api/v1/docs`. `operation_id` values stay stable.

Run from `backend/`:

```bash
../.venv/bin/python -m uvicorn app.main:app --reload
```
