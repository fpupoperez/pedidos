# Worker

`handler.py` imports one stored CSV. The API calls it when `NATS_DELIVERY=inline`. The push consumer is not started yet. It will subscribe as queue group `orders_import_worker`, ack explicitly, and let JetStream backoff redeliver when the database is down.

The handler will call `transition_status` (`SELECT ... FOR UPDATE`) and will not sleep to retry.
