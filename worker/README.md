# Worker

`handler.py` imports one stored CSV. The API calls it when `NATS_DELIVERY=inline`.

`main.py` is the push consumer. From the repository root:

```text
PYTHONPATH=backend .venv/bin/python -m worker.main
```

It subscribes as queue group `orders_import_worker`, acks explicitly, and lets JetStream backoff redeliver when the database is down. The handler calls `transition_status` (`SELECT ... FOR UPDATE`) and does not sleep to retry.
