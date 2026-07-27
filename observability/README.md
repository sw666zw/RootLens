# RootLens local observability

This directory contains the tracked configuration for the Milestone 1 local
metrics, logs, and tracing stack. Prometheus stores application metrics. Loki
stores application logs received from Grafana Alloy. Jaeger stores traces
received through the OpenTelemetry Collector. Grafana provisions all three data
sources plus the **RootLens Inventory Overview** and
**RootLens Inventory Logs** dashboards.

The Inventory Service runs directly on the Mac. PostgreSQL, Prometheus, Loki,
Alloy, Grafana, the Collector, and Jaeger run in Docker on the shared
`rootlens` network.

## Telemetry data flow

Metrics follow this path:

```text
Inventory Service GET /metrics
  -> Prometheus at host.docker.internal:8000
  -> Grafana Prometheus data source
```

Uvicorn must listen on `0.0.0.0:8000`, because a service bound only to the
Mac's loopback interface cannot accept a scrape arriving from Docker.

Traces follow a separate path:

```text
Inventory Service on the Mac
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
timestamps, logger messages, and exception text remain JSON fields. Turning
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
ROOTLENS_FILE_LOGGING_ENABLED=true
ROOTLENS_LOG_FILE_PATH=runtime/logs/inventory.jsonl
```

Also copy any missing `OTEL_*` entries from `.env.example`. The example
database and Grafana credentials are local-development defaults only.

## Start the stack and service

Start the Compose services without deleting their named volumes:

```bash
docker compose up -d
docker compose ps
```

Load the private environment, apply the existing migration, and run the
Inventory Service in a separate terminal:

```bash
set -a
source .env
set +a
alembic -c services/inventory/alembic.ini upgrade head
uvicorn --app-dir services/inventory/src inventory_service.main:app \
  --reload --host 0.0.0.0 --port 8000 --env-file .env
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
```

The create may return `409` when the sample SKU already exists; that is useful
error traffic. Confirm the file receives one JSON object per line:

```bash
tail -n 5 runtime/logs/inventory.jsonl
```

## Query logs and follow traces

Open Grafana at <http://127.0.0.1:3000>, sign in with the private `.env`
values, and open **Explore**. Select **Loki** and start with:

```logql
{service="inventory"} | json
```

Search for one request ID:

```logql
{service="inventory"} | json | request_id="replace-with-request-id"
```

Search for one trace ID:

```logql
{service="inventory"} | json | trace_id="replace-with-32-character-trace-id"
```

The provisioned Loki data source recognizes lowercase 32-character hexadecimal
`trace_id` values. Expand a matching log row and use **View trace in Jaeger** to
open the same trace through the provisioned Jaeger data source. The
**RootLens Inventory Logs** dashboard provides recent logs, warnings/errors,
request completions, reservation outcomes, and volume grouped by level.

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
python -m ruff check services/inventory
docker compose config
docker compose run --rm --no-deps loki \
  -config.file=/etc/loki/loki.yml -verify-config=true
docker compose run --rm --no-deps alloy validate \
  /etc/alloy/config.alloy
docker compose run --rm --no-deps --entrypoint promtool prometheus \
  check config /etc/prometheus/prometheus.yml
docker compose run --rm --no-deps otel-collector validate \
  --config=/etc/otelcol-contrib/collector.yml
python3.12 -c 'import json; json.load(open("observability/grafana/dashboards/inventory-logs.json"))'
python3.12 -c 'import pathlib, yaml; [yaml.safe_load(path.read_text()) for path in pathlib.Path("observability").rglob("*.yml")]'
git check-ignore -v runtime/logs/inventory.jsonl
test -f runtime/logs/.gitkeep
! git check-ignore runtime/logs/.gitkeep
```

The container validation commands may pull their pinned images if they are not
already available locally.
