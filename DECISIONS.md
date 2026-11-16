# Decisions

- `QUESTION_ROW_LIMIT` is 200.
- `QUESTION_TIMEOUT_MS` is 3000.
- `IMPORT_BATCH_SIZE` is 200.
- `MAX_UPLOAD_BYTES` is 5242880.
- JetStream backoff is 2, 4, 8 seconds and `max_deliver` is 4. The handler does not sleep.
- `ack_wait` is 120 seconds.
- Allowed SQL relations are `orders`, `sales_by_month_country`, and `top_customers`.
- `top_customers` is the global 10. A filtered question uses `orders`.
- Cancel rolls back the order insert. Rejection rows already committed stay.
- `totalRows = acceptedRows + rejectedRows`. `phase` is derived from `status`. `processing` is shown as `importing`.
- One `pending`, `processing`, or `completed` task per content hash.
- Countries are stored as the canonical Spanish names in `app/domain/countries.py`.
- Stdout span export drops SQLAlchemy spans. An OTLP endpoint exports them.
- Span attributes omit file bytes, raw CSV lines, prompts, model keys, and rejected SQL text.
