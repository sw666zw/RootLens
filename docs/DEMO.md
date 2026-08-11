# RootLens demo workflow

This workflow demonstrates the supported local-development path without
deploying RootLens or enabling automated remediation.

## 1. Prepare and start infrastructure

Use Python 3.12 and Node.js 22. Copy the example once, keep the resulting `.env`
private, and enable the documented local fault controls:

```bash
cp .env.example .env
docker compose up -d
docker compose ps
```

Load the environment and apply the existing service-owned migrations:

```bash
set -a
source .env
set +a
alembic -c services/inventory/alembic.ini upgrade head
alembic -c services/order/alembic.ini upgrade head
```

## 2. Start the three services

Run each command in its own terminal from the repository root:

```bash
uvicorn --app-dir services/inventory/src inventory_service.main:app \
  --reload --host 0.0.0.0 --port 8000 --env-file .env
```

```bash
uvicorn --app-dir services/order/src order_service.main:app \
  --reload --host 0.0.0.0 --port 8001 --env-file .env
```

```bash
uvicorn --app-dir services/diagnosis/src diagnosis_service.main:app \
  --reload --host 0.0.0.0 --port 8002 --env-file .env
```

Confirm liveness at ports 8000, 8001, and 8002 and confirm all three Prometheus
targets are up at <http://127.0.0.1:9090/targets>.

## 3. Start the browser

```bash
cd apps/web
npm ci
npm run dev
```

Open <http://localhost:5173>. The browser uses the Diagnosis Service only; it
does not receive backend credentials.

## 4. Generate and diagnose an unavailable incident

From the repository root:

```bash
rootlens-scenario run inventory-unavailable --requests 10 --concurrency 5
```

In the browser, open **Incidents**, choose the newest incident, and select
**Run diagnosis**. Review the authoritative root cause, confidence, candidate
scores, source coverage, warnings, and evidence grouped by metrics, logs, and
traces. Follow a trace ID or request ID into the observability tools as needed.

## 5. Explain and validate

On the diagnosis page, leave the provider set to **template**, create an
explanation, inspect its evidence citations, and validate it. Template mode is
offline and is the default.

An OpenAI explanation is optional. Enable it only in the private backend
environment by setting `ROOTLENS_LLM_ENABLED=true`, keeping the key only in the
ignored `OPENAI_API_KEY` entry, and optionally selecting `OPENAI_MODEL`. Restart
only the Diagnosis host process, select OpenAI explicitly in the browser, create
one explanation, and validate it. Disable LLM use again after the demo. Never
place the API key in frontend configuration, a command transcript, tracked file,
screenshot, or report. OpenAI prose cannot alter the deterministic root cause or
evidence.

## 6. Inspect observability

- Open Grafana at <http://127.0.0.1:3000> and view **RootLens Distributed
  Services Overview**, **RootLens Distributed Service Logs**, and **RootLens
  Diagnosis Service Overview**.
- Open Jaeger at <http://127.0.0.1:16686>, select `rootlens-order`, and inspect a
  trace ID captured by the incident.
- In Grafana Explore, query `{service=~"inventory|order"} | json` and filter by
  a captured request ID.

## 7. Run the benchmark

The live benchmark expects the same services and telemetry stack to remain up:

```bash
rootlens-benchmark run
```

Review the reported accuracy and then inspect or summarize the generated JSON:

```bash
rootlens-benchmark summarize runtime/benchmarks/BENCHMARK_ID.json
```

## 8. Stop safely

Stop the Vite and Uvicorn host processes with `Ctrl-C`, explicitly clear any
fault, then stop Compose without deleting volumes:

```bash
rootlens-scenario reset
docker compose down
```

Do not use volume-deleting flags unless you intentionally want to discard local
development data.
