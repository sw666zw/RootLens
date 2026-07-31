# RootLens Order Service

The Order Service owns durable records of every validated order attempt. It
stores those records in its own PostgreSQL database and calls Inventory Service
to reserve stock:

```text
Client -> Order Service :8001 -> Order PostgreSQL :5433
                              -> Inventory Service :8000 -> Inventory PostgreSQL :5432
```

Each service owns its data and schema. Order never writes Inventory tables, and
Inventory never writes Order tables. This prevents one service from coupling
its releases, transactions, and failure handling to another service's private
implementation.

## Order lifecycle

After request validation, Order generates its UUID and commits a `pending` row
before contacting Inventory. Inventory is never called if that commit fails.
Storing the attempt first makes downstream failures discoverable:

- `pending`: the attempt is durable but has no final Inventory outcome yet.
- `confirmed`: Inventory reserved stock and the final state was committed.
- `rejected`: Inventory reported `item_not_found` or
  `insufficient_inventory`.
- `failed`: Inventory was unavailable or returned an invalid response.

The pending transaction commits before the HTTP call. Holding a database
transaction open while waiting on another service would occupy a connection
and make transaction duration depend on network latency. The final status is a
second committed transition.

There is one deliberate consistency gap: Inventory can reserve stock and the
subsequent confirmed-state commit can fail. Order does not retry Inventory and
returns `503 {"detail":"Order service unavailable."}` while logging
`order_consistency_risk`. Idempotency, reconciliation, compensation, and
retries are not implemented. Payments, queues, and automated diagnosis are
also outside this milestone.

## Install and configure

Use Python 3.12 and install both services with development dependencies:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e "services/inventory[dev]" -e "services/order[dev]"
cp .env.example .env
```

Do not commit `.env`. If one already exists, copy the `ORDER_POSTGRES_*` and
`ORDER_DATABASE_URL` entries from `.env.example` into it. Keep the password in
`ORDER_DATABASE_URL` consistent with `ORDER_POSTGRES_PASSWORD`. The committed
values are local-development defaults, not production credentials.

## Start databases and apply migrations

Start the two independent PostgreSQL containers:

```bash
docker compose up -d postgres order-postgres
docker compose ps postgres order-postgres
```

Load the private environment and apply each service's migration:

```bash
set -a
source .env
set +a
alembic -c services/inventory/alembic.ini upgrade head
alembic -c services/order/alembic.ini upgrade head
```

The application never creates tables automatically. Order Alembic reads only
`ORDER_DATABASE_URL`; Inventory Alembic continues to read `DATABASE_URL`.

## Run both services

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

`GET /health` is liveness and remains independent of PostgreSQL and Inventory.
`GET /health/ready` is readiness: it returns `200` only when Order PostgreSQL
answers `SELECT 1`, otherwise it returns the safe `503` response.

Stop only Order PostgreSQL and verify the distinction:

```bash
docker compose stop order-postgres
curl -i http://127.0.0.1:8001/health
curl -i http://127.0.0.1:8001/health/ready
docker compose start order-postgres
```

## Create and retrieve orders

Seed Inventory and create an order:

```bash
curl -i -X POST http://127.0.0.1:8000/items \
  -H 'Content-Type: application/json' \
  -d '{"sku":"LAPTOP-001","name":"Demo Laptop","quantity":10}'
curl -i -X POST http://127.0.0.1:8001/orders \
  -H 'Content-Type: application/json' \
  -H 'X-Request-ID: distributed-demo-001' \
  -d '{"sku":"LAPTOP-001","quantity":2}'
```

Success remains HTTP `201` with exactly `order_id`, `sku`, `quantity`,
`status`, and `remaining_inventory`. Copy the returned `order_id`, then use:

```bash
curl -i http://127.0.0.1:8001/orders
curl -i http://127.0.0.1:8001/orders/REPLACE_WITH_ORDER_ID
```

The list is ordered by `created_at` descending and UUID ascending for ties.
Both read APIs return `id`, `sku`, `quantity`, `status`,
`remaining_inventory`, `failure_reason`, `request_id`, `trace_id`,
`created_at`, and `updated_at`.

Create rejected records and inspect them:

```bash
curl -i -X POST http://127.0.0.1:8001/orders \
  -H 'Content-Type: application/json' \
  -d '{"sku":"MISSING","quantity":1}'
curl -i -X POST http://127.0.0.1:8001/orders \
  -H 'Content-Type: application/json' \
  -d '{"sku":"LAPTOP-001","quantity":1000000}'
curl -sS http://127.0.0.1:8001/orders
```

To create `inventory_unavailable`, stop the Inventory Uvicorn process, submit
an order, restart Inventory, and retrieve the failed record.

## Correlate logs, traces, and metrics

Order logs flow through Alloy to Loki. Order ID, request ID, trace ID, status,
failure reason, and SKU remain parsed JSON fields, not Loki labels. Search the
local file:

```bash
rg 'REPLACE_WITH_ORDER_ID' runtime/logs/order.jsonl
```

Useful Grafana Explore queries are:

```logql
{service="order"} | json | order_id="REPLACE_WITH_ORDER_ID"
{service="order"} | json | status="failed"
{service="order"} | json | failure_reason="inventory_unavailable"
{service=~"order|inventory"} | json | request_id="distributed-demo-001"
{service="order"} | json | trace_id="REPLACE_WITH_32_HEX_TRACE_ID"
```

Open **RootLens Distributed Service Logs** for lifecycle events. Open Jaeger at
<http://127.0.0.1:16686>, select `rootlens-order`, and search using the
`X-Trace-ID` response header or stored `trace_id`. A complete distributed trace
can include Order server, persistence, SQLAlchemy, and HTTPX spans plus
Inventory server and SQLAlchemy spans.

Prometheus continues to scrape the same Order `/metrics` target. The
distributed overview includes database readiness, lifecycle transition rate,
failed-order rate, and process-lifetime status counts:

```bash
curl -sS http://127.0.0.1:8001/metrics | grep '^rootlens_order'
open http://127.0.0.1:9090/targets
open http://127.0.0.1:3000
open http://127.0.0.1:16686
```

## Test and lint

Unit tests use dependency overrides and in-memory doubles. They require no
Docker, PostgreSQL, network, Inventory process, or observability backend:

```bash
python3.12 -m pytest services/order
python3.12 -m pytest services/inventory
python3.12 -m ruff check services/inventory services/order
```
