# Orders

HTTP API and worker that import a CSV of orders into PostgreSQL and answer read-only questions about the imported rows.

## Architecture

```text
                         +------------------+
                         |      client      |
                         +---------+--------+
                                   |
                    CSV, status, file, orders, question
                                   |
                                   v
                    +------------------------------+
                    | API  FastAPI  :8000          |
                    | backend/                     |
                    |                              |
                    |  POST /imports               |
                    |    write CSV under DATA_DIR  |
                    |    insert task               |
                    |  GET  /tasks, /orders, /file |
                    |  POST /questions             |
                    |    provider -> SQL guard     |
                    +--+-----------+------------+--+
                       |           |            |
          orders.import|           |            | SELECT
          {"taskId"}   |           |            |
                       v           |            v
              +----------------+   |   +----------------------+
              | NATS JetStream |   |   | orders_reader        |
              | stream ORDERS  |   |   | read-only            |
              | :4222          |   |   +----------+-----------+
              +--------+-------+   |              |
                       |           |              |
                       | push      |              |
                       v           |              |
              +----------------+   |              |
              | worker         |   |              |
              | queue group    |   |              |
              | orders_import_ |   |              |
              | worker         |   |              |
              +--------+-------+   |              |
                       |           |              |
                       | read CSV  | write task,  |
                       | clean     | orders,      |
                       v           | rejections   v
              +----------------------------------------------+
              | PostgreSQL 16  :5432                         |
              |  tasks, orders, import_rejections            |
              |  sales_by_month_country, top_customers       |
              +----------------------------------------------+

  DATA_DIR/uploads is one directory shared by the API and the worker.
  With NATS_DELIVERY=inline the API calls the worker in process and skips NATS.
```

| Piece | Role |
| --- | --- |
| `backend/` | FastAPI service. Accepts the CSV, stores the task, and serves status, the original file, orders, and questions. |
| `worker/` | JetStream push consumer. Queue group `orders_import_worker`. Cleans one file and commits its orders. |
| PostgreSQL 16 | Tasks, orders, rejections, and the views `sales_by_month_country` and `top_customers`. |
| NATS JetStream | Stream `ORDERS`, subject `orders.import`. The message body is `{"taskId": "<uuid>"}`. |
| `orders_reader` | Read-only role used by questions. |

The API publishes after the task row is committed. The worker and the API share the upload directory. Questions run one checked `SELECT`. OpenAPI is at `/api/v1/docs`.

## Run

Requires Python 3.11.

```bash
python3.11 -m venv .venv
.venv/bin/pip install -r backend/requirements-dev.txt
```

Generate the sample file and start the API from `backend/`:

```bash
make csv
cd backend && ../.venv/bin/python -m uvicorn app.main:app --reload
```

Apply the schema once, against the database in `DATABASE_URL`:

```bash
cd backend && ../.venv/bin/alembic upgrade head
```

Start the worker from the repository root, with the same database, `DATA_DIR`, and `NATS_URL` as the API:

```bash
PYTHONPATH=backend .venv/bin/python -m worker.main
```

Copy `.env.example` and export the variables you need. `NATS_DELIVERY=inline` runs the import in the API process. `jetstream` publishes to NATS. Tests use `orders_test` and `LLM_PROVIDER=fake`.

```bash
make lint
make types
make test
```

Upload, poll, download, and ask:

```bash
curl -s -F "file=@data/samples/orders.csv;type=text/csv" http://127.0.0.1:8000/api/v1/imports
curl -s http://127.0.0.1:8000/api/v1/tasks/TASK_ID
curl -s -o pedidos.csv http://127.0.0.1:8000/api/v1/tasks/TASK_ID/file
curl -s -H "Content-Type: application/json" \
  -d '{"question":"¿cuánto vendimos en España en marzo?"}' \
  http://127.0.0.1:8000/api/v1/questions
```

## Deploy

Docker Compose runs PostgreSQL, NATS, the API, and the worker. Images copy the source. The API runs `alembic upgrade head` on startup. Both services mount one volume at `/app/data`.

```bash
cp .env.example infra/.env
make up
```

Set `LLM_API_KEY`, `LLM_API_BASE`, and `LLM_MODEL` in `infra/.env` when `LLM_PROVIDER=litellm`. That file is not committed.

Published ports: PostgreSQL `5432`, NATS `4222`, API `8000`. After a code change, rebuild the service you changed:

```bash
docker compose --env-file infra/.env -f infra/compose.yaml up --build
```
