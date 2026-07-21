# RootLens

RootLens is a planned observability and automated incident-diagnosis platform for distributed services. Modern systems emit logs, metrics, and distributed traces across many components, but investigating an incident still requires engineers to manually connect those signals. RootLens will collect and correlate telemetry, reconstruct the context around failures, and surface evidence-backed likely root causes so teams can diagnose incidents faster.

## Planned architecture

RootLens is expected to include telemetry ingestion for logs, metrics, and traces; a shared correlation and storage layer; an analysis engine for detecting incidents and ranking likely causes; and APIs or interfaces for investigating the supporting evidence. The architecture will evolve milestone by milestone as the project validates each capability.

## Initial milestone roadmap

1. Build a small inventory service that will later serve as a system under observation.
2. Instrument the inventory service and establish collection of logs, metrics, and distributed traces.
3. Correlate telemetry across requests, services, and time windows.
4. Detect representative incidents and generate evidence-backed root-cause hypotheses.
5. Provide an investigation experience for reviewing incidents, correlated signals, and likely causes.

Milestone 1 is underway with Inventory Service health endpoints, request IDs,
structured request logging, Prometheus-compatible application metrics, a local
PostgreSQL foundation, and the first persistent inventory-item create/read API.
Concurrency-safe stock reservation is also implemented with a PostgreSQL row
lock to prevent overselling. A local Prometheus server now scrapes the service,
and a provisioned Grafana dashboard visualizes its HTTP and reservation metrics.
Logs and traces are not collected into this dashboard, and tracing is not
implemented. Update, delete, restocking, reservation history, and an Order
Service remain planned.

## Local monitoring quick start

Prometheus collects and stores the numeric measurements exposed by the
Inventory Service at `GET /metrics`. Grafana queries Prometheus and displays
those measurements in the provisioned **RootLens Inventory Overview**
dashboard. The Inventory Service still runs directly on the developer's Mac;
only PostgreSQL, Prometheus, and Grafana run in Docker.

Copy the local-development environment example, start the Compose services,
apply the Inventory Service migration, and run the service on all host
interfaces:

```bash
cp .env.example .env
docker compose up -d postgres prometheus grafana
set -a
source .env
set +a
alembic -c services/inventory/alembic.ini upgrade head
uvicorn --app-dir services/inventory/src inventory_service.main:app \
  --reload --host 0.0.0.0 --port 8000 --env-file .env
```

Binding Uvicorn to `0.0.0.0` is required because Prometheus reaches the Mac
host from its container through `host.docker.internal:8000`; binding only to
`127.0.0.1` would accept requests solely from the Mac's own loopback interface.
Docker Desktop supplies `host.docker.internal` as the container-to-host DNS
name, and the Compose `host-gateway` mapping improves portability on compatible
Docker engines.

Open the Prometheus targets page at <http://127.0.0.1:9090/targets> and confirm
that `inventory-service` is `UP`. Open Grafana at <http://127.0.0.1:3000>, sign
in with `GRAFANA_ADMIN_USER` and `GRAFANA_ADMIN_PASSWORD`, then open
**Dashboards > RootLens > RootLens Inventory Overview**. The defaults in
`.env.example` are convenient local-development credentials and are not safe
for production.

See [observability/README.md](observability/README.md) for configuration details,
sample-traffic commands, verification steps, and safe shutdown guidance. See
[services/inventory/README.md](services/inventory/README.md) for the Inventory
Service API and development workflow.
