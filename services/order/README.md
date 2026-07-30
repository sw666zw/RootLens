# RootLens Order Service

The Order Service is RootLens's second independently deployable FastAPI
business service. It accepts a transient order, asks Inventory Service to
atomically reserve its stock in PostgreSQL, and confirms the order only after
that reservation succeeds:

```text
Client -> Order Service :8001 -> Inventory Service :8000 -> PostgreSQL
```

Order Service generates a UUID only after successful reservation. It does not
persist that UUID or any order data. Order persistence, idempotency,
compensation, payments, queues, circuit breakers, and automated diagnosis are
future milestones. Reservation calls are deliberately not retried: without an
idempotency key, retrying an ambiguous request could subtract stock twice.

## Install and configure

From the repository root, use Python 3.12 and install both independently
deployable services with their development dependencies:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e "services/inventory[dev]" -e "services/order[dev]"
cp .env.example .env
```

The committed example uses Order port `8001`, Inventory URL
`http://localhost:8000`, trace service name `rootlens-order`, and file
`runtime/logs/order.jsonl`. A real `.env` is private and ignored.

## Run both services

Start the existing Compose stack and migrate only the Inventory database:

```bash
docker compose up -d
set -a
source .env
set +a
alembic -c services/inventory/alembic.ini upgrade head
```

Run Inventory in one terminal:

```bash
uvicorn --app-dir services/inventory/src inventory_service.main:app \
  --reload --host 0.0.0.0 --port 8000 --env-file .env
```

Run Order in another:

```bash
uvicorn --app-dir services/order/src order_service.main:app \
  --reload --host 0.0.0.0 --port 8001 --env-file .env
```

Both bind to `0.0.0.0` so Prometheus in Docker can scrape the host services.
Order's `GET /health` is an independent liveness check and never calls
Inventory.

## Create orders and exercise outcomes

Seed stock through Inventory, then create an order:

```bash
curl -i -X POST http://127.0.0.1:8000/items \
  -H 'Content-Type: application/json' \
  -d '{"sku":"LAPTOP-001","name":"Demo Laptop","quantity":10}'
curl -i -X POST http://127.0.0.1:8001/orders \
  -H 'Content-Type: application/json' \
  -H 'X-Request-ID: distributed-demo-001' \
  -d '{"sku":"LAPTOP-001","quantity":2}'
```

A successful request returns HTTP `201` with exactly `order_id`, `sku`,
`quantity`, `status`, and `remaining_inventory`. Trigger the principal failure
paths with:

```bash
# Missing item: Order returns 404.
curl -i -X POST http://127.0.0.1:8001/orders \
  -H 'Content-Type: application/json' \
  -d '{"sku":"MISSING","quantity":1}'

# Insufficient stock: Order returns 409.
curl -i -X POST http://127.0.0.1:8001/orders \
  -H 'Content-Type: application/json' \
  -d '{"sku":"LAPTOP-001","quantity":1000000}'

# Unavailable Inventory: stop only Inventory's Uvicorn process, then Order returns 503.
curl -i -X POST http://127.0.0.1:8001/orders \
  -H 'Content-Type: application/json' \
  -d '{"sku":"LAPTOP-001","quantity":1}'
```

## Correlate logs, traces, and metrics

Order preserves a nonblank caller `X-Request-ID`, or generates a UUID, and
sends that same value to Inventory. Search both JSONL files directly:

```bash
rg 'distributed-demo-001' \
  runtime/logs/order.jsonl runtime/logs/inventory.jsonl
```

Or query both services in Grafana's Loki data source:

```logql
{service=~"order|inventory"} | json | request_id="distributed-demo-001"
```

Open **RootLens Distributed Service Logs** for dedicated Order and Inventory
panels and a request-ID textbox. Request IDs stay parsed JSON fields rather
than high-cardinality Loki labels.

Open Jaeger at <http://127.0.0.1:16686>, select `rootlens-order`, and open the
trace returned as `X-Trace-ID`. FastAPI extracts incoming W3C `traceparent`;
HTTPX injects the active context into the Inventory call automatically. One
trace therefore contains Order server/client spans plus Inventory server and
SQLAlchemy spans.

Inspect both metrics endpoints and Prometheus targets:

```bash
curl -sS http://127.0.0.1:8000/metrics | grep '^rootlens_'
curl -sS http://127.0.0.1:8001/metrics | grep '^rootlens_'
open http://127.0.0.1:9090/targets
```

In Grafana at <http://127.0.0.1:3000>, open **RootLens Distributed Services
Overview** for target status, request/error rates, p95 latency, order outcomes,
and reservation outcomes.

## Test and lint

Normal tests use HTTPX `MockTransport`; they require no network, Docker,
database, Inventory process, or observability backend:

```bash
python -m pytest services/order
python -m pytest services/inventory
python -m ruff check services/inventory services/order
```
