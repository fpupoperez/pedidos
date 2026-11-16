# Pedidos

API para cargar un CSV de pedidos y responder preguntas de solo lectura sobre lo ya importado.

```text
CSV  ->  API  ->  Postgres (tasks, orders)
              ->  NATS JetStream  ->  worker  ->  Postgres
pregunta  ->  API  ->  orders_reader  ->  orders / vistas
```

El API guarda el archivo, crea una tarea y publica `orders.import`. El worker, en el grupo `orders_import_worker`, limpia el CSV y confirma los pedidos en una transacción. Una pregunta se convierte en un único `SELECT`, el guardia lo revisa y `orders_reader` lo ejecuta. No hay Celery.

## Cómo ejecutarlo

Hace falta Python 3.11 y Docker.

```bash
python3.11 -m venv .venv
.venv/bin/pip install -r backend/requirements-dev.txt
cp .env.example infra/.env
make csv
make up
```

`make csv` escribe `data/samples/orders.csv`. `make up` levanta Postgres, NATS, el API y el worker. El API aplica las migraciones al arrancar. La documentación queda en `http://127.0.0.1:8000/api/v1/docs`.

Sube el archivo:

```bash
curl -s -F "file=@data/samples/orders.csv;type=text/csv" http://127.0.0.1:8000/api/v1/imports
```

La respuesta es 202 y trae `data.taskId`. Consulta el estado, descarga el CSV original y cancela solo si sigue pendiente o en proceso:

```bash
curl -s http://127.0.0.1:8000/api/v1/tasks/TASK_ID
curl -s -D - -o pedidos.csv http://127.0.0.1:8000/api/v1/tasks/TASK_ID/file
curl -s -X POST http://127.0.0.1:8000/api/v1/tasks/TASK_ID/cancel
```

`sourceFile` es esa misma URL. Una pregunta:

```bash
curl -s -H "Content-Type: application/json" \
  -d '{"question":"¿cuánto vendimos en España en marzo?"}' \
  http://127.0.0.1:8000/api/v1/questions
```

Para correr el API y el worker fuera de Docker, crea antes la base `orders`, aplica `alembic upgrade head` desde `backend/` y exporta las variables de `.env.example`. El worker se arranca desde la raíz:

```bash
PYTHONPATH=backend .venv/bin/python -m worker.main
```

Comprobaciones:

```bash
make lint
make types
make test
```

`make test` no usa la base `orders` ni NATS. `make test-all` exige cobertura del 90 por ciento. `make hooks` instala Ruff antes del commit, y mypy con pytest antes del push.

## Decisiones

PostgreSQL 16 es la única base: las vistas, `NUMERIC` y el rol de solo lectura tienen que coincidir en local y en Compose. El CSV acepta cabeceras en español o en inglés. El país se guarda con un nombre canónico en español (`Spain` y `Espana` pasan a `España`). Un duplicado dentro del archivo conserva la primera fila. Un mismo contenido solo puede tener una tarea `pending`, `processing` o `completed`.

Cada tarea guarda un resumen de conteos. `phase` no se guarda: se deduce del estado, y `processing` se muestra como `importing`. Cancelar revierte la inserción de pedidos; los rechazos ya confirmados se quedan. Todo cambio de estado usa `SELECT ... FOR UPDATE`. Si el proceso muere en `processing`, la siguiente entrega retoma el trabajo y vuelve a insertar. El reintento de una caída de base lo hace JetStream, con esperas de 2, 4 y 8 segundos. El worker no duerme.

Cada importación es un trazo. El `traceparent` viaja en la cabecera de NATS. Sin un endpoint OpenTelemetry, los trazos de negocio salen por stdout. Las preguntas usan el rol `orders_reader`. Los tests fuerzan el proveedor `fake`. El grupo de cola de JetStream sustituye a Celery. La inserción de un archivo es una transacción.

## Con más tiempo

Activaría la autenticación que ya prevé `session_auth` y demostraría un segundo réplica del worker bajo carga.

## Cómo usé la IA

Le pedí a un asistente de código que implementara el enunciado con modelos tipados, sobre, pruebas, lint y una estructura clara, y que el trabajo en segundo plano fuera NATS en modo push con grupo de cola, no Celery. Le pedí también el bloqueo `SELECT ... FOR UPDATE`, telemetría de punta a punta con salida a stdout si no hay colector, el resumen de filas para poder actuar, y el enlace para descargar el CSV original.

Acepté el diseño en el que JetStream reintenta una caída de base y el handler no cuenta reintentos ni duerme. Acepté que `top_customers` sea el ranking global de diez y que una pregunta filtrada use `orders`. Acepté dejar los archivos de agentes fuera del repositorio.

Corregí los commits para que el autor fuera solo el mío, sin un trailer de coautor. Corregí un merge que había borrado el fixture de migraciones y las notas de la base en el README del API. No dejé ninguna clave de modelo en el repositorio: los tests usan `fake` y la clave, si hace falta, vive en `infra/.env`.
