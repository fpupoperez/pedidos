# Infra

Compose is not written yet. When it is, `infra/.env` holds secrets and is not committed. Images copy the source. Rebuild the service you changed.

Postgres will be published on the host. NATS client port is `4222`. The API listens on `8000`.
