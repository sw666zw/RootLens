# RootLens local monitoring

This directory contains the tracked configuration for the Milestone 1 local
metrics stack. Prometheus scrapes and stores time-series metrics. Grafana uses
Prometheus as its provisioned default data source and loads the tracked
**RootLens Inventory Overview** dashboard.

The Inventory Service continues to run directly on the developer's Mac.
PostgreSQL, Prometheus, and Grafana run in Docker on the shared `rootlens`
Compose network. PostgreSQL is not scraped directly.

## Data flow

The Inventory Service exposes Prometheus exposition text at `GET /metrics`.
Prometheus requests that endpoint every five seconds at
`host.docker.internal:8000`. Docker Desktop resolves
`host.docker.internal` to the Mac host from inside a container. The additional
`host-gateway` mapping is compatible with Docker Desktop and also helps Docker
Engine installations that support that special gateway value.

Uvicorn must listen on `0.0.0.0:8000` for this path to work. A server listening
only on `127.0.0.1` accepts connections only from the Mac loopback interface,
not connections arriving from the Docker network.

Grafana queries Prometheus over the Compose network at
`http://prometheus:9090`. The provisioned data-source UID is
`rootlens-prometheus`, and the dashboard UID is
`rootlens-inventory-overview`. Provisioned dashboard files are mounted
read-only, UI saves are disabled, and UI deletion does not remove the tracked
source.

## Configure the local environment

From the repository root, create the ignored local environment file:

```bash
cp .env.example .env
```

The example defines `GRAFANA_ADMIN_USER` and `GRAFANA_ADMIN_PASSWORD`. Its
values, and the matching Compose fallback values, are for local development
only. They are not production credentials. Use independently managed secrets
and a stronger authentication configuration outside local development. Do not
commit `.env`.

## Start PostgreSQL, Prometheus, and Grafana

Start the complete Compose stack without deleting or recreating its named
volumes:

```bash
docker compose up -d postgres prometheus grafana
docker compose ps
```

Compose exposes PostgreSQL at `127.0.0.1:5432`, Prometheus at
`127.0.0.1:9090`, and Grafana at `127.0.0.1:3000` by default.

## Start the Inventory Service

Use Python 3.12 with the service's dependencies already installed. Load the
local environment and apply the existing migration:

```bash
set -a
source .env
set +a
alembic -c services/inventory/alembic.ini upgrade head
```

Then run the service on the Mac in a separate terminal:

```bash
uvicorn --app-dir services/inventory/src inventory_service.main:app \
  --reload --host 0.0.0.0 --port 8000 --env-file .env
```

Confirm that the metrics endpoint is available from the Mac:

```bash
curl -sS http://127.0.0.1:8000/metrics | grep '^rootlens_'
```

## Verify Prometheus

Open <http://127.0.0.1:9090/targets> and confirm that the
`inventory-service` target is `UP`. The target is expected to be down until the
Inventory Service is running on `0.0.0.0:8000`.

You can also verify the target and an application metric through the Prometheus
HTTP API:

```bash
curl -sS --get http://127.0.0.1:9090/api/v1/query \
  --data-urlencode 'query=up{job="inventory-service"}'
curl -sS --get http://127.0.0.1:9090/api/v1/query \
  --data-urlencode 'query=rootlens_inventory_http_requests_total'
```

## Generate sample traffic

Create a sample item once. A repeated create returns `409`, which is also useful
error traffic:

```bash
curl -sS -X POST http://127.0.0.1:8000/items \
  -H 'Content-Type: application/json' \
  -d '{"sku":"LAPTOP-001","name":"Demo Laptop","quantity":10}'
```

Generate representative successful, missing-route, and reservation outcomes:

```bash
curl -sS http://127.0.0.1:8000/health
curl -sS http://127.0.0.1:8000/items
curl -sS http://127.0.0.1:8000/items/LAPTOP-001
curl -sS http://127.0.0.1:8000/does-not-exist
curl -sS -X POST http://127.0.0.1:8000/items/LAPTOP-001/reserve \
  -H 'Content-Type: application/json' -d '{"quantity":1}'
curl -sS -X POST http://127.0.0.1:8000/items/LAPTOP-001/reserve \
  -H 'Content-Type: application/json' -d '{"quantity":1000000}'
curl -sS -X POST http://127.0.0.1:8000/items/MISSING/reserve \
  -H 'Content-Type: application/json' -d '{"quantity":1}'
```

Repeat those requests for a minute if you want clearer rate and latency lines.
Prometheus scrapes every five seconds, and the dashboard refreshes every five
seconds.

## Open Grafana

Open <http://127.0.0.1:3000> and sign in with the local values of
`GRAFANA_ADMIN_USER` and `GRAFANA_ADMIN_PASSWORD`. Navigate to
**Dashboards > RootLens > RootLens Inventory Overview**. The dashboard defaults
to the last 15 minutes and includes target status, overall request rate, error
rate, p95 latency, request rate by normalized route and status code, and
reservation outcomes by bounded outcome and reason.

The dashboard intentionally does not use SKU, request ID, timestamp, or other
high-cardinality labels. Logs and traces are not collected into this dashboard.
There is no alerting, tracing, incident diagnosis, or log aggregation in this
stack.

## Stop or reset the stack

Stop and remove the containers and Compose network while preserving all three
named volumes:

```bash
docker compose down
```

The next `docker compose up` reuses the stored PostgreSQL data, Prometheus time
series, and Grafana application data.

To deliberately reset all local stored data, run:

```bash
docker compose down -v
```

`docker compose down -v` deletes the PostgreSQL, Prometheus, and Grafana named
volumes. This is destructive and cannot be undone through Compose.

## Validate tracked configuration

Run these checks from the repository root:

```bash
docker compose config
docker compose run --rm --no-deps --entrypoint promtool prometheus \
  check config /etc/prometheus/prometheus.yml
python3.12 -c 'import json; json.load(open("observability/grafana/dashboards/inventory-overview.json"))'
python3.12 -c 'import pathlib, yaml; [yaml.safe_load(path.read_text()) for path in pathlib.Path("observability").rglob("*.yml")]'
git check-ignore -v .env
python -m pytest services/inventory
python -m ruff check services/inventory
```

The Prometheus validation command may pull the pinned image if it is not
already present. Python's standard library validates the dashboard JSON; the
YAML command uses the development environment's existing PyYAML installation.
