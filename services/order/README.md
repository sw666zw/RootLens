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
`order_consistency_risk`. A keyed retry finds the durable `pending` row and
does not reserve again. A later reconciliation milestone will address orders
that remain pending permanently. Reconciliation, compensation, automatic
retries, payments, queues, and automated diagnosis are outside this milestone.

## Retry-safe creation with Idempotency-Key

Clients may retry a POST when a connection closes or a response is lost, even
though the server may already have completed the work. Reserving stock twice
for one intended order is dangerous. `POST /orders` therefore accepts an
optional `Idempotency-Key` header. Unkeyed requests retain the original
behavior and every request is a separate attempt; clients that need retry-safe
creation must supply a key and reuse it only for the same logical order.

Order trims surrounding key whitespace, rejects blank keys and keys longer
than 255 characters, and otherwise preserves the key exactly. It stores the
key with a SHA-256 fingerprint of the normalized SKU and quantity. The stable
fingerprint prevents one key from representing two different orders, without
storing the raw request body. A PostgreSQL partial unique index atomically
claims non-null keys while allowing any number of unkeyed orders.

Repeated keyed requests behave as follows:

- `confirmed` returns the original HTTP 201 body and
  `Idempotency-Replayed: true`.
- `rejected` replays the original safe 404 or 409 and adds that header.
- `failed` replays the safe Inventory 503 and adds that header. It is not
  automatically tried again because an ambiguous request must not later
  reserve stock a second time.
- `pending` returns HTTP 409 with `Retry-After: 1`; it is not marked replayed
  because processing has no stored terminal result.
- A matching key with a different normalized SKU or quantity returns HTTP 409.

Automatic HTTP retries are intentionally absent. Retry policy belongs to the
caller, and only a caller-provided idempotency key makes an Order POST safe to
repeat.

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

The application never creates tables automatically. Order migration `0002`
adds the paired idempotency columns, format checks, and partial unique index.
Order Alembic reads only `ORDER_DATABASE_URL`; Inventory Alembic continues to
read `DATABASE_URL`.

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

Create a retry-safe order, replay it, and then demonstrate rejected key reuse:

```bash
curl -i -X POST http://127.0.0.1:8001/orders \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: demo-order-001' \
  -d '{"sku":"LAPTOP-001","quantity":2}'
curl -i -X POST http://127.0.0.1:8001/orders \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: demo-order-001' \
  -d '{"sku":"LAPTOP-001","quantity":2}'
curl -i -X POST http://127.0.0.1:8001/orders \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: demo-order-001' \
  -d '{"sku":"LAPTOP-001","quantity":3}'
```

The second response contains `Idempotency-Replayed: true` and the same
`order_id` and `remaining_inventory`. Compare Inventory before and after both
matching POSTs; its quantity changes once:

```bash
curl -sS http://127.0.0.1:8000/items/LAPTOP-001
```

To demonstrate an in-progress conflict, send two simultaneous requests. The
loser returns HTTP 409 with `Retry-After: 1` if the first request is still
between its pending commit and terminal commit:

```bash
printf '%s\n' 1 2 | xargs -P2 -I{} curl -i -X POST \
  http://127.0.0.1:8001/orders \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: concurrent-demo-001' \
  -d '{"sku":"LAPTOP-001","quantity":1}'
```

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

For repeatable local incidents, enable Inventory's development-only controls
and use the scenario runner described in
[`tools/scenario_runner/README.md`](../../tools/scenario_runner/README.md).
`inventory-unavailable` exercises Order's existing safe translation: Inventory
returns 503 before reservation, Order persists the failed attempt, and the
client receives `{"detail":"Inventory service unavailable."}`. The runner
adds no retries or compensation. Stopping Inventory or a real database remains
a separate manual outage exercise.

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
{service="order"} | json | message="order_idempotency_claimed"
{service="order"} | json | message="order_idempotency_replayed"
{service="order"} | json | message="order_idempotency_conflict" | reason="payload_mismatch"
{service="order"} | json | message="order_idempotency_conflict" | reason="in_progress"
```

The raw idempotency key is never logged and never used as a Loki or Prometheus
label. Logs contain only its SHA-256 hash for safe correlation.

Open **RootLens Distributed Service Logs** for lifecycle events. Open Jaeger at
<http://127.0.0.1:16686>, select `rootlens-order`, and search using the
`X-Trace-ID` response header or stored `trace_id`. A complete distributed trace
can include Order server, persistence, SQLAlchemy, and HTTPX spans plus
Inventory server and SQLAlchemy spans.

Prometheus continues to scrape the same Order `/metrics` target. The
distributed overview includes database readiness, lifecycle transition rate,
failed-order rate, process-lifetime status counts, and idempotency events by
the bounded `outcome` label:

```bash
curl -sS http://127.0.0.1:8001/metrics | grep '^rootlens_order'
curl -sS http://127.0.0.1:8001/metrics | grep '^rootlens_order_idempotency_events_total'
open http://127.0.0.1:9090/targets
open http://127.0.0.1:3000
open http://127.0.0.1:16686
```

In Jaeger, keyed Order server spans expose only
`rootlens.order.idempotency_key_present` and the bounded
`rootlens.order.idempotency_outcome`. A replay trace has no outgoing Inventory
HTTP span because its response comes from stored Order state.

## Test and lint

Unit tests use dependency overrides and in-memory doubles. They require no
Docker, PostgreSQL, network, Inventory process, or observability backend:

```bash
python3.12 -m pytest services/order
python3.12 -m pytest services/inventory
python3.12 -m ruff check services/inventory services/order
```
