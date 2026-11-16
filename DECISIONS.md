# Decisions

The numbers below are the ones the code treats as fixed. The sections after them say why the import is an event and how a question becomes one checked `SELECT`.

## Numbers

- `QUESTION_ROW_LIMIT` is 200. The SQL guard adds that `LIMIT` when the statement has none, and shortens a larger numeric limit. `truncated` is true only when the guard added or shortened the limit. A limit of 200 or less stays and is not marked truncated.
- `QUESTION_TIMEOUT_MS` is 3000. The reader runs `SET LOCAL statement_timeout` to that value. The model does not choose the timeout.
- `LLM_TIMEOUT_SECONDS` defaults to 5 so a test does not wait on a model. `.env.example` sets 60 because a real chat completion is slower than the test default. The HTTP client uses that timeout for the whole completion call.
- `IMPORT_BATCH_SIZE` is 200. The worker inserts accepted orders in batches of that size and checks for cancel between batches.
- `MAX_UPLOAD_BYTES` is 5242880. A larger CSV is rejected before a task row is stored.
- JetStream backoff is 2, 4, and 8 seconds. `max_deliver` is 4. The handler does not sleep. A `nak` lets the server wait and redeliver.
- `ack_wait` is 120 seconds. A `processing` task older than that may be retried. A newer `processing` task is left alone because a handler may still hold it.
- The JetStream duplicate window is 120 seconds. `Nats-Msg-Id` is the task id, so a second publish of the same task inside that window is one message.
- Stream messages are file-stored and expire after 7 days. Retention is limits, not work-queue deletion on ack.
- Allowed SQL relations are `orders`, `sales_by_month_country`, and `top_customers`. An optional `public.` prefix is the same relation. A CTE name is local and is not a foreign table.
- `top_customers` is the global 10. A question that filters by country, month, or product uses `orders`. A month and country total may use `sales_by_month_country`.
- Countries are stored as the canonical Spanish names in `app/domain/countries.py`.
- One `pending`, `processing`, or `completed` task per content hash. The partial unique index is `uq_tasks_active_hash`. A duplicate active hash returns 409 and names the existing task id.
- `totalRows = acceptedRows + rejectedRows`. A break of that invariant is `summary_mismatch` and is not retried. `phase` is derived from `status` when the task is read. The stored summary has counts only. `processing` is shown as `importing`.
- Cancel from `pending` or `processing` rolls back the order insert. Rejection rows already committed stay. `importedRows` is 0. Cancel after `completed` is 409.
- Stdout span export drops SQLAlchemy spans. An OTLP endpoint exports them. Span attributes omit file bytes, raw CSV lines, prompts, model keys, and rejected SQL text.

## NATS instead of Celery and Redis

The import worker is a JetStream push consumer. There is no Celery app, no Redis broker, and no result backend.

Celery would add a broker plus a result store, and the task row would still be the source of truth for status. JetStream already gives a durable subject, explicit ack, redelivery, backoff, and a dedupe key. The PostgreSQL task row remains the status record. The message does not carry the CSV, the summary, or a Celery task id.

`NATS_DELIVERY=inline` calls `handle_import` in the API process and does not publish. Tests and a single-process run use that mode. `NATS_DELIVERY=jetstream` publishes after the task row is committed. Compose runs `jetstream`.

The API and the worker share one upload directory, `DATA_DIR/uploads`. The message only points at the task. The worker reads the file from that directory. A publish failure does not delete the file. It marks the task `failed` with `publish_failed` and the route returns 502. Retry republishes that task.

## How an import is delivered

`deliver` in `app/nats/publisher.py` is the only handoff. From a sync route it runs the publish coroutine in one worker thread, because the API may already be inside an event loop.

The stream is `ORDERS`. Subjects are `orders.>`. The import subject is `orders.import`. The body is `{"taskId": "<uuid>"}`. Headers are the current W3C `traceparent` and `tracestate`, injected by OpenTelemetry, plus `Nats-Msg-Id` set to the task UUID. Connect and publish each wait at most 2 seconds. The publisher creates the stream only when it is missing. An existing stream is left as the server has it.

The worker process is `python -m worker.main`. It ensures the same stream and subscribes with manual ack. The durable name, queue group, and deliver group are all `orders_import_worker`. The deliver subject is `deliver_orders_import`. Deliver policy is all, ack policy is explicit, `max_ack_pending` is 1, and the filter subject is `orders.import`. One replica therefore holds one file at a time.

`worker/consumer.py` decodes `taskId`. A body that is not a task id is acknowledged so JetStream does not redeliver it forever. A valid id continues the trace from the message headers and calls `handle_import` on a thread. `ack` means the outcome is stored or the task is already finished. `nak` means a transient database error and the status was left unchanged. `num_delivered` is the attempt count. On the last attempt the handler writes `retries_exhausted` and acknowledges when that write succeeds. If the status write itself fails, it still naks.

Permanent failures are acknowledged and are not redelivered: `invalid_header`, `file_missing`, `file_unreadable`, and `summary_mismatch`. A completed, cancelled, or otherwise terminal task is acknowledged without inserting again.

Status changes go through `transition_status` and `SELECT ... FOR UPDATE`. The handler claims `pending` or `processing` into `processing` before it reads the file. Cleaning commits rejection rows and the file counts first. The order insert is a later transaction: `pg_advisory_xact_lock` on the task id, delete the task's orders, then insert batches. The lock dies with the transaction. Between batches the handler looks for cancel. Cancel rolls that transaction back and sets `importedRows` to 0. A second delivery of a completed task does not insert again.

Retry accepts a `failed` task whose reason is `publish_failed` or `retries_exhausted`, or a `processing` task whose `updated_at` is older than `ack_wait`. Completed, cancelled, and permanent failures stay 409.

## How the model is called

There are two providers, `fake` and `litellm`. There is no third provider. Tests force `fake`. An unknown provider name is 502 and does not touch the database.

`FakeProvider` does not open a socket. It maps two folded question strings to fixed SQL: the March España total, and the top customers. Every other question gets `SELECT country, total_amount FROM sales_by_month_country`. `mode = "invalid"` returns the text `not-json` so the parser test can see a 502. Token counts stay 0.

`LiteLLMProvider` is the real call. It is not tied to one vendor. It POSTs `{LLM_API_BASE}/chat/completions`, which is the OpenAI chat-completions shape. A local Ollama server is used by setting `LLM_API_BASE` to `http://host:11434/v1` and `LLM_MODEL` to the Ollama model name. No Ollama-specific client is added. `LLM_API_KEY` is optional. When it is set, the header is `Authorization: Bearer <key>`. The key stays in the environment and is not written into the repository.

The JSON body is:

- `model`: `LLM_MODEL`
- `temperature`: 0, so the same question tends to produce the same SQL
- `messages`: one `system` message and one `user` message

The user message is the question text unchanged. The system message is the shared prompt plus two notes built at call time. A missing base URL or model name is 502 before the HTTP call. An HTTP error, a non-JSON body, or a body without `choices[0].message.content` as a string is 502 with the public text "The model response was not valid." Usage `prompt_tokens` and `completion_tokens` are recorded when present, otherwise 0. Tests pass an `httpx` mock transport and never dial a model.

The question service does not execute the model text. It parses one JSON object, keeps the `sql` string, and ignores extra keys. A non-object, invalid JSON, or an empty `sql` is 502. That failure happens before the SQL guard and before the query runs.

## How the prompt is built

`SYSTEM_PROMPT` in `app/providers/base.py` is the same text for every provider. It is fixed at import. It tells the model to reply with one JSON object and no other text, with a single string field `sql` whose value is one PostgreSQL `SELECT`.

The prompt names the only relations the guard allows, and the columns:

- `orders(order_date, customer, country, product, amount, status)`
- `sales_by_month_country(sale_month, country, order_count, total_amount)`
- `top_customers(customer, country, order_count, total_amount)`

It states the rules the model keeps getting wrong when they are left implicit:

- `top_customers` is already the global ten. Do not use it when the question filters.
- A filtered total uses `orders`. A month and country total may use the month view.
- Countries are compared with the canonical Spanish names listed in the prompt. The question may be in any language, and a country word must be translated into that list.
- Product names are stored in Spanish. The model must use a stored spelling, not the word in the question.
- Do not invent a year or a `BETWEEN` range. Use a year only when the question names one. A month with no year is `EXTRACT(MONTH FROM order_date) = N`.
- `este año` and `este mes` follow today's date, not the years present in the table.
- `cuántas` or `cuántos` is `COALESCE(COUNT(*), 0) AS sales`. `cuánto vendimos` is `COALESCE(SUM(amount), 0) AS total_amount`.

At call time `LiteLLMProvider` appends two notes to that text. They are not part of the static prompt because they depend on the clock and the loaded rows.

The date note always starts with today's ISO date and says `este año` means `EXTRACT(YEAR FROM order_date) = <that year>`, even when every imported row is from another year. When `MIN(order_date)` and `MAX(order_date)` are present, it adds that range so the model can see which years were loaded. Those reads use the same read-only executor as a question. A missing table or a failed read leaves the today sentence in place and does not fail the question.

The product note is `SELECT DISTINCT product FROM orders`, sorted, and a sentence that says to translate the question's product into one of those names. An empty or unread table adds nothing.

The model is still not trusted. The notes and the prompt steer it. The next section rewrites the SQL the model returns.

## How the query is built

`ask` in `app/services/questions.py` is the only path from a question to rows. The order is fixed: call the provider, parse JSON, translate stored names, count rows when the question asks how many, run the SQL guard, then execute the guard's SQL.

Translation runs before the guard. `sqlglot` parses the statement as Postgres. For `=`, `<>`, and `IN`, a string compared with `country` or `product` is replaced when it is a known alias. `LOWER(column)` and `LOWER('text')` are accepted as those sides. A statement that does not parse, or is not a single `SELECT`, is left unchanged and the guard rejects it later.

Country aliases live in `app/domain/countries.py`. Folding lowercases and strips accents, so `Spain` and `Espana` become `España`, `France` becomes `Francia`, and `United States` becomes `Estados Unidos`. An unknown country word is left as the model wrote it.

Product aliases live in `app/domain/products.py`. A folded word that is already stored wins, so a file that really contains `Keyboard` is not rewritten to `Teclado`. Otherwise the catalog alias is used only when that Spanish spelling is among the stored products. The catalog covers the sample names `Teclado`, `Monitor`, `Silla`, `Cable`, and `Lampara`, including English, French, German, and Portuguese words such as `keyboard`, `keyboards`, `clavier`, `chair`, `stuhl`, and `lampe`. An unknown product word is left unchanged.

`cuántas` and `cuántos`, with or without the accent, mean a count of rows. If the parsed statement sums the `amount` column, each `SUM(amount)` becomes `COUNT(*)`. Aliases `total_amount` and `total_sales` on that statement become `sales`. `cuánto vendimos` does not match, so a sum of amount stays a sum. A question that already counts is not rewritten.

The guard in `app/sql/validator.py` is the last editor of the text. `sqlglot` parses with `read="postgres"`. The database later receives `statement.sql(dialect="postgres")`, not the model string. One statement is required, and it must be a `SELECT`. `WITH ... SELECT` is a `Select`. These are rejected and become 422 `Rejected by sql_guard: <rule>`:

- empty, or more than one statement: `empty`, `multiple_statements`
- not a select, `SELECT INTO`, or row locks: `not_select`, `select_into`, `locking`
- insert, update, delete, merge, drop, alter, create, command, grant, truncate, copy, transaction, commit, rollback, set: `write_statement`
- a function whose name starts with `pg_`, including `pg_sleep` parsed as an anonymous function: `function_not_allowed`
- a table outside the three relations, or a schema other than empty or `public`: `relation_not_allowed`
- a non-numeric `LIMIT`: `limit_not_constant`

Product comparisons are folded after the relation check. `product = 'teclado'` and the swapped form become `LOWER(product) = LOWER('teclado')`. `product IN (...)` lowercases the column and each string. `product LIKE 'pattern'` becomes `ILIKE`. `ILIKE` is left as it is. Country comparisons are not lowercased, because the stored country is the canonical spelling. The select list `SELECT product` is not wrapped.

The guard then applies `QUESTION_ROW_LIMIT`. The checked SQL, the string cells, the row count, and `truncated` are what the API returns. The raw model text is not returned.

Execution uses `DATABASE_READ_URL` as `orders_reader`. The migration grants that role `CONNECT` and `SELECT` on `orders` and the two views, and revokes `tasks` and `import_rejections`. Each question opens a transaction, runs `SET TRANSACTION READ ONLY`, sets the local statement timeout, executes the checked SQL with no parameters, and rolls the transaction back. A database error is 422 "The query could not be executed." Cells are JSON strings. `NULL` is `""`. `Decimal` keeps its plain format. Dates and timestamps use `isoformat`.

A bad model payload never reaches the guard or the database. A guard rejection never reaches the database. The read-only role is what runs the statement that does.
