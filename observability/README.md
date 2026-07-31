# RootLens local observability

This directory contains the tracked configuration for the local
metrics, logs, and tracing stack. Prometheus stores application metrics. Loki
stores application logs received from Grafana Alloy. Jaeger stores traces
received through the OpenTelemetry Collector. Grafana provisions all three data
sources plus Inventory-specific and distributed service dashboards.

The Inventory and Order services run directly on the Mac. Their two independent
PostgreSQL containers, Prometheus, Loki, Alloy, Grafana, the Collector, and
Jaeger run in Docker on the shared `rootlens` network.

## Telemetry data flow

Metrics follow this path:

```text
Inventory Service GET /metrics
  -> Prometheus at host.docker.internal:8000
  -> Grafana Prometheus data source
Order Service GET /metrics
  -> Prometheus at host.docker.internal:8001
  -> Grafana Prometheus data source
```

Uvicorn must listen on `0.0.0.0` for both ports, because a service bound only
to the Mac's loopback interface cannot accept a scrape arriving from Docker.

Traces follow a separate path:

```text
Client -> Order Service -> Order PostgreSQL
                       -> Inventory Service -> Inventory PostgreSQL
Order Service and Inventory Service on the Mac
  -> OTLP/gRPC localhost:4317
  -> OpenTelemetry Collector in Docker
  -> OTLP/gRPC jaeger:4317
  -> Jaeger and the Grafana Jaeger data source
```

Centralized logging keeps logs in a queryable shared backend instead of only in
ephemeral Terminal scrollback. Logs follow this path:

```text
Inventory Service on the Mac
  -> Terminal JSON output
  -> runtime/logs/inventory.jsonl
  -> Grafana Alloy in Docker
  -> Grafana Loki in Docker
  -> Grafana Explore and RootLens Inventory Logs
Order Service on the Mac
  -> Terminal JSON output
  -> runtime/logs/order.jsonl
  -> Grafana Alloy in Docker
  -> Grafana Loki in Docker
  -> Grafana Explore and RootLens Distributed Service Logs
```

File output is additional: it does not replace Terminal output and it does not
capture Uvicorn's own logs. Each application event occupies exactly one JSON
line so Alloy can tail incrementally and parse each event independently. The
original line stays intact in Loki, enabling LogQL's `| json` parser.

Alloy is Grafana's current telemetry collector and is used instead of the
legacy Promtail agent. It discovers and tails the mounted file, parses the
application timestamp and level, maintains file positions in `alloy_data`, and
pushes entries to Loki.

Loki indexes a deliberately bounded set of labels: `service`, `environment`,
`level`, and `job`. Request IDs, trace IDs, span IDs, SKUs, paths, quantities,
idempotency-key hashes, timestamps, logger messages, and exception text remain
JSON fields. Raw idempotency keys are never logged. Turning
those request-specific values into labels would create an ever-growing index;
parsing them at query time keeps correlation available without that
high-cardinality cost.

This is not a production deployment. Loki has no authentication, runs as one
process, and uses local filesystem storage. Jaeger uses in-memory storage. The
stack has no alerting or automated diagnosis.

## Configure the private environment

From the repository root, create the ignored local environment file:

```bash
cp .env.example .env
```

If `.env` already exists, add these values without committing the file:

```dotenv
ORDER_POSTGRES_DB=rootlens_orders
ORDER_POSTGRES_USER=rootlens_order
ORDER_POSTGRES_PASSWORD=rootlens_order_dev_password
ORDER_POSTGRES_PORT=5433
ORDER_DATABASE_URL=postgresql+asyncpg://rootlens_order:rootlens_order_dev_password@localhost:5433/rootlens_orders
ROOTLENS_FILE_LOGGING_ENABLED=true
ROOTLENS_LOG_FILE_PATH=runtime/logs/inventory.jsonl
ROOTLENS_ORDER_LOG_FILE_PATH=runtime/logs/order.jsonl
```

Also copy any missing `OTEL_*` entries from `.env.example`. The example
database and Grafana credentials are local-development defaults only.

## Start the stack and service

Start the Compose services without deleting their named volumes:

```bash
docker compose up -d
docker compose ps
```

Load the private environment, apply both service-owned migrations, and run the
Inventory Service in a separate terminal:

```bash
set -a
source .env
set +a
alembic -c services/inventory/alembic.ini upgrade head
alembic -c services/order/alembic.ini upgrade head
uvicorn --app-dir services/inventory/src inventory_service.main:app \
  --reload --host 0.0.0.0 --port 8000 --env-file .env
```

Run Order Service in another terminal:

```bash
uvicorn --app-dir services/order/src order_service.main:app \
  --reload --host 0.0.0.0 --port 8001 --env-file .env
```

The application creates `runtime/logs` when file logging is enabled. Generated
JSONL files are ignored by Git.

## Generate representative telemetry

```bash
curl -sS http://127.0.0.1:8000/health
curl -sS http://127.0.0.1:8000/items
curl -sS http://127.0.0.1:8000/does-not-exist
curl -sS -X POST http://127.0.0.1:8000/items \
  -H 'Content-Type: application/json' \
  -d '{"sku":"LAPTOP-001","name":"Demo Laptop","quantity":10}'
curl -sS -X POST http://127.0.0.1:8000/items/LAPTOP-001/reserve \
  -H 'Content-Type: application/json' -d '{"quantity":1}'
curl -sS -X POST http://127.0.0.1:8000/items/LAPTOP-001/reserve \
  -H 'Content-Type: application/json' -d '{"quantity":1000000}'
curl -sS -X POST http://127.0.0.1:8000/items/MISSING/reserve \
  -H 'Content-Type: application/json' -d '{"quantity":1}'
curl -i -X POST http://127.0.0.1:8001/orders \
  -H 'Content-Type: application/json' \
  -H 'X-Request-ID: distributed-demo-001' \
  -d '{"sku":"LAPTOP-001","quantity":1}'
```

The create may return `409` when the sample SKU already exists; that is useful
error traffic. Confirm the file receives one JSON object per line:

```bash
tail -n 5 runtime/logs/inventory.jsonl
tail -n 5 runtime/logs/order.jsonl
```

## Query logs and follow traces

Open Grafana at <http://127.0.0.1:3000>, sign in with the private `.env`
values, and open **Explore**. Select **Loki** and start with:

```logql
{service="inventory"} | json
{service="order"} | json
{service=~"inventory|order"} | json
```

Search for one request ID:

```logql
{service=~"inventory|order"} | json | request_id="replace-with-request-id"
{service="order"} | json | order_id="replace-with-order-id"
{service="order"} | json | status="failed"
{service="order"} | json | failure_reason="inventory_unavailable"
{service="order"} | json | message="order_idempotency_claimed"
{service="order"} | json | message="order_idempotency_replayed"
{service="order"} | json | message="order_idempotency_conflict" | reason="payload_mismatch"
{service="order"} | json | message="order_idempotency_conflict" | reason="in_progress"
```

Search for one trace ID:

```logql
{service=~"inventory|order"} | json | trace_id="replace-with-32-character-trace-id"
```

The provisioned Loki data source recognizes lowercase 32-character hexadecimal
`trace_id` values. Expand a matching log row and use **View trace in Jaeger** to
open the same trace through the provisioned Jaeger data source. The
**RootLens Distributed Service Logs** dashboard provides both services and a
request-ID textbox for following one operation across the boundary. Its Order
Idempotency Events panel exposes claims, replays, and both conflict reasons
without creating per-key Loki labels.

Inspect Alloy's component graph and status at <http://127.0.0.1:12345>. Check
Loki directly and query recent entries with:

```bash
curl -fsS http://127.0.0.1:3100/ready
curl -fsS -G http://127.0.0.1:3100/loki/api/v1/query_range \
  --data-urlencode 'query={service="inventory"} | json' \
  --data-urlencode 'limit=20'
```

Grafana's data-source health endpoints confirm that it can reach each backend:

```bash
curl -fsS -u "${GRAFANA_ADMIN_USER}:${GRAFANA_ADMIN_PASSWORD}" \
  http://127.0.0.1:3000/api/datasources/uid/loki/health
curl -fsS -u "${GRAFANA_ADMIN_USER}:${GRAFANA_ADMIN_PASSWORD}" \
  http://127.0.0.1:3000/api/datasources/uid/rootlens-prometheus/health
```

Prometheus targets are at <http://127.0.0.1:9090/targets>; Jaeger is at
<http://127.0.0.1:16686>. The Collector health endpoint is
<http://127.0.0.1:13133/>.

Inspect the bounded idempotency counter and its provisioned dashboard panel:

```bash
curl -sS http://127.0.0.1:8001/metrics | \
  grep '^rootlens_order_idempotency_events_total'
```

The only label is `outcome`, with `claimed`, `replayed`, `payload_mismatch`,
or `in_progress`. In Jaeger, keyed Order server spans contain the safe
`rootlens.order.idempotency_key_present` and
`rootlens.order.idempotency_outcome` attributes. Replayed traces have no
outgoing Inventory HTTP span.

## Stop safely

Stop and remove containers and the Compose network while preserving
PostgreSQL, Prometheus, Grafana, Loki, and Alloy state:

```bash
docker compose down
```

Do not add `-v` unless you intentionally want to delete every named volume.

## Validate tracked configuration

Run from the repository root:

```bash
python -m pytest services/inventory
python -m pytest services/order
python -m ruff check services/inventory services/order
docker compose config
docker compose run --rm --no-deps loki \
  -config.file=/etc/loki/loki.yml -verify-config=true
docker compose run --rm --no-deps alloy validate \
  /etc/alloy/config.alloy
docker compose run --rm --no-deps --entrypoint promtool prometheus \
  check config /etc/prometheus/prometheus.yml
docker compose run --rm --no-deps otel-collector validate \
  --config=/etc/otelcol-contrib/collector.yml
python3.12 -c 'import json, pathlib; [json.load(path.open()) for path in pathlib.Path("observability/grafana/dashboards").glob("*.json")]'
python3.12 -c 'import pathlib, yaml; [yaml.safe_load(path.read_text()) for path in pathlib.Path("observability").rglob("*.yml")]'
git check-ignore -v runtime/logs/inventory.jsonl
git check-ignore -v runtime/logs/order.jsonl
test -f runtime/logs/.gitkeep
! git check-ignore runtime/logs/.gitkeep
```

The container validation commands may pull their pinned images if they are not
already available locally.
