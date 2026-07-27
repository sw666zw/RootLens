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
OpenTelemetry now traces HTTP requests and SQLAlchemy calls through a local
OpenTelemetry Collector into Jaeger. Grafana Alloy tails the service's
additional JSON-lines log file and sends those logs to Loki, while Grafana
provides a provisioned log dashboard and trace links into Jaeger. Update,
delete, restocking, reservation history, automated diagnosis, and an Order
Service remain planned.

## Local observability quick start

Prometheus collects and stores the numeric measurements exposed by the
Inventory Service at `GET /metrics`. Grafana queries Prometheus and displays
those measurements in the provisioned **RootLens Inventory Overview**
dashboard. OpenTelemetry records request and database spans, the Collector
receives and forwards them, and Jaeger stores and displays the resulting traces.
Centralized logging makes application events queryable instead of leaving them
only in Terminal scrollback. The service writes the same structured JSON to the
Terminal and to `runtime/logs/inventory.jsonl`; Alloy tails that file, Loki
stores it, and Grafana loads the provisioned **RootLens Inventory Logs**
dashboard. The Inventory Service still runs directly on the developer's Mac;
PostgreSQL, Prometheus, Loki, Alloy, Grafana, the Collector, and Jaeger run in
Docker.

Copy the local-development environment example, start the Compose services,
apply the Inventory Service migration, and run the service on all host
interfaces:

```bash
cp .env.example .env
docker compose up -d
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
for production. Open Jaeger at <http://127.0.0.1:16686> and select
`rootlens-inventory` after generating traffic. The service exports OTLP/gRPC to
the Collector on `localhost:4317`; it never exports directly to Jaeger.
Open Grafana Explore, select **Loki**, and run
`{service="inventory"} | json` to inspect parsed application log fields.
Alloy's debugging UI is at <http://127.0.0.1:12345>, and Loki readiness is
available at <http://127.0.0.1:3100/ready>.

See [observability/README.md](observability/README.md) for configuration details,
sample-traffic commands, verification steps, and safe shutdown guidance. See
[services/inventory/README.md](services/inventory/README.md) for the Inventory
Service API and development workflow.
