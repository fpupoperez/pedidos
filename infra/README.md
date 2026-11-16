# Infra

`compose.yaml` runs Postgres 16, NATS JetStream, the API, and the worker. Images copy the source. Rebuild the service you changed.

Secrets belong in `infra/.env`. That file is not committed. Copy the example and put the model key only there:

```bash
cp ../.env.example .env
```

`make up` from the repository root builds and starts the stack. Postgres is on port 5432, NATS on 4222, and the API on 8000. The API and the worker share the upload volume.
