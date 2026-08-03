# RootLens scenario runner

The scenario runner is a Python 3.12 local-development tool that produces
repeatable business traffic for controlled incidents. RootLens needs these
known outcomes so a later diagnosis engine can be evaluated against independent
ground truth. Fault injection creates the condition; it does not detect,
query, correlate, or diagnose it. The runner never queries Prometheus, Loki,
Grafana, or Jaeger and has no web server or database.

## Safety boundary

Inventory fault injection is disabled by default. Set this only in the private,
Git-ignored `.env` used for local development:

```dotenv
ROOTLENS_FAULT_INJECTION_ENABLED=true
ROOTLENS_INCIDENT_OUTPUT_DIR=runtime/incidents
INVENTORY_SERVICE_URL=http://localhost:8000
ORDER_SERVICE_URL=http://localhost:8001
```

Do not enable it in production. The controls are absent (normal HTTP 404) when
disabled. When enabled, they are hidden from OpenAPI and accept only loopback
clients. This narrow boundary is intentional: the controls have no production
authentication because they are not a production chaos interface.

Control requests under `/internal/faults` are scenario setup, not business
traffic, so Inventory excludes them from HTTP metrics, request-completion logs,
and traces. The actual Order and Inventory reservation requests remain fully
observable. No application log reveals the configured injection mode; the
separate report is the evaluation ground truth.

## Install and start

From the repository root, install the runner and its development dependencies
in the same Python 3.12 virtual environment as the services:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e "services/inventory[dev]"
python -m pip install -e "services/order[dev]"
python -m pip install -e "tools/scenario_runner[dev]"
```

Copy `.env.example` to `.env`, change
`ROOTLENS_FAULT_INJECTION_ENABLED=true`, load it, start the Docker stack, apply
the existing migrations, and start both host services:

```bash
cp .env.example .env
set -a
source .env
set +a
docker compose up -d
alembic -c services/inventory/alembic.ini upgrade head
alembic -c services/order/alembic.ini upgrade head
uvicorn --app-dir services/inventory/src inventory_service.main:app \
  --reload --host 0.0.0.0 --port 8000 --env-file .env
```

In another terminal:

```bash
uvicorn --app-dir services/order/src order_service.main:app \
  --reload --host 0.0.0.0 --port 8001 --env-file .env
```

## Run scenarios

Every run checks both `/health` endpoints first, creates a unique stocked item,
sends uniquely identified and idempotent requests through Order, resets the
fault in a `finally` block, prints a summary, and writes one JSON report.

```bash
rootlens-scenario run baseline
rootlens-scenario run baseline --requests 20 --concurrency 5
rootlens-scenario run inventory-latency --delay-ms 1500
rootlens-scenario run inventory-unavailable
rootlens-scenario reset
```

- `baseline` clears faults and expects every Order response to be HTTP 201.
- `inventory-latency` delays each Inventory reservation asynchronously and
  expects HTTP 201 without using an exact timing threshold.
- `inventory-unavailable` prevents the reservation repository call, expects
  Order HTTP 503 responses, and checks stock remains unchanged when practical.
- `reset` clears reservation faults without creating traffic or a report.

`--requests` defaults to 20 and must be positive. `--concurrency` defaults to 5,
must be positive, and cannot exceed requests. `--delay-ms` defaults to 1500 and
is limited to 1–10000. Use `--output-dir` or
`ROOTLENS_INCIDENT_OUTPUT_DIR` to override the report directory.

Reports are written atomically as `runtime/incidents/<scenario-id>.json` with
stable, sorted JSON formatting. They include timestamps, expected cause and
symptoms, response counts and durations, request IDs, and only valid returned
trace IDs. Raw idempotency keys, bodies, credentials, environment contents,
and stack traces are never stored. Generated reports are ignored by Git and the
directory is not mounted into Alloy, so ground truth is not sent to Loki.

An unexpected broad result still produces a report and a reset, then exits
nonzero. Run tests and lint without any live dependency:

```bash
python -m pytest tools/scenario_runner
python -m ruff check tools/scenario_runner
```

All tests use HTTPX `MockTransport` and temporary directories; no test performs
a real network request.

## Inspect effects

Open the **RootLens Distributed Services Overview** and **RootLens Distributed
Service Logs** dashboards in Grafana. Use the report's request or trace IDs to
filter Loki and Jaeger. Prometheus shows the affected Order and reservation
status/latency while Jaeger shows the Order-to-Inventory path. The control calls
themselves will not appear because they are deliberately excluded.

Stopping a real database remains a separate manual outage exercise; the runner
does not stop or restart Docker. Automated diagnosis is the next major
milestone.
