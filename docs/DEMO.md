# RootLens 3–5 minute demo playbook

The demo follows one `inventory-unavailable` incident from controlled generation through authoritative diagnosis, supporting telemetry, optional explanation, and deterministic validation. OpenAI is optional; template mode completes the full workflow offline.

## Prepare before the demo

Use Python 3.12, Node.js 22, and Docker Compose. Install the packages once as described in the root [README](../README.md), then create the private environment if needed:

```bash
cp .env.example .env
```

Set `ROOTLENS_FAULT_INJECTION_ENABLED=true` in the ignored root `.env`. Do not put an API key in commands, screenshots, frontend configuration, or tracked files.

Start Docker infrastructure:

```bash
docker compose up -d
docker compose ps
```

Load the environment and apply the two existing service-owned migrations:

```bash
set -a
source .env
set +a
alembic -c services/inventory/alembic.ini upgrade head
alembic -c services/order/alembic.ini upgrade head
```

Start each backend in a separate terminal from the repository root.

Inventory Service:

```bash
uvicorn --app-dir services/inventory/src inventory_service.main:app \
  --reload --host 0.0.0.0 --port 8000 --env-file .env
```

Order Service:

```bash
uvicorn --app-dir services/order/src order_service.main:app \
  --reload --host 0.0.0.0 --port 8001 --env-file .env
```

Diagnosis Service:

```bash
uvicorn --app-dir services/diagnosis/src diagnosis_service.main:app \
  --reload --host 0.0.0.0 --port 8002 --env-file .env
```

Start the frontend in a fourth terminal:

```bash
cd apps/web
npm ci
npm run dev
```

Before presenting, confirm the three service health endpoints and Prometheus targets, then open:

- RootLens: <http://localhost:5173>
- Grafana: <http://127.0.0.1:3000>
- Jaeger: <http://127.0.0.1:16686>
- Prometheus targets: <http://127.0.0.1:9090/targets>

## Live walkthrough

1. **Overview — 20 seconds.** Open RootLens Overview. Point out Incident Intelligence, Diagnosis Service health, incident/diagnosis/explanation totals, recent activity, root-cause distribution, and telemetry coverage.

2. **Generate the incident — 20 seconds.** From the repository root run:

   ```bash
   rootlens-scenario run inventory-unavailable --requests 10 --concurrency 5
   ```

   Explain that this is controlled synthetic fault injection, not arbitrary incident discovery.

3. **Inspect the case file — 20 seconds.** Open **Incidents**, select the newest incident, and show request counts, failed and successful outcomes, captured identifiers, and the **Run diagnosis** control. The UI intentionally hides evaluation ground truth.

4. **Run deterministic diagnosis — 45 seconds.** Select **Run diagnosis**. On Diagnosis Detail show the authoritative root cause, affected service, confidence and level, telemetry coverage, and candidate scores. Emphasize that explicit rules—not an LLM—select the result.

5. **Inspect evidence — 35 seconds.** Scroll into normalized metrics, log, and trace evidence. Call out supporting and contradicting observations, stable references, warnings, alternatives, and recommended checks.

6. **Show Jaeger — 25 seconds.** Open Jaeger, select `rootlens-order`, and use a captured trace ID. Show the Order request, Order PostgreSQL work, Order-to-Inventory HTTP call, Inventory span, and Inventory PostgreSQL span where present.

7. **Show Grafana — 25 seconds.** Open **RootLens Distributed Services Overview** and **RootLens Distributed Service Logs**. In Explore, a useful correlated query is:

   ```logql
   {service=~"inventory|order"} | json | request_id="replace-with-request-id"
   ```

8. **Explain and validate — 35 seconds.** Back on Diagnosis Detail, generate a **template** explanation. Show its headline, executive summary, deterministic basis, provider, confidence, evidence-grounded claims, and validation summary. Run validation and show the deterministic pass/fail checks.

9. **Optional OpenAI explanation — 20 seconds.** If the backend was privately and explicitly configured with `ROOTLENS_LLM_ENABLED=true` and `OPENAI_API_KEY`, select OpenAI and generate one explanation. Do not reveal configuration or the key. Explain that the provider creates prose only and protected diagnosis fields still come from application code. Skip this step without apology when OpenAI is disabled.

10. **Evaluation and CI — 20 seconds.** Briefly open a synthetic benchmark example or a previously generated local benchmark report, explaining repetitions, exact match, confidence, coverage, durations, and the confusion matrix. Finish with the GitHub Actions page showing the Python, frontend, and configuration jobs green. Do not run a live benchmark during a short demo unless time was reserved for it.

## Optional live benchmark

With all services and telemetry backends already healthy:

```bash
rootlens-benchmark run
```

Summarize its generated JSON without rerunning scenarios:

```bash
rootlens-benchmark summarize runtime/benchmarks/BENCHMARK_ID.json
```

## Shutdown

Stop Vite and each Uvicorn process with `Ctrl-C`. Then, from the repository root, clear any controlled fault and stop Compose without deleting volumes:

```bash
rootlens-scenario reset
docker compose down
```

Do not use volume-deleting flags unless local development data is intentionally being discarded.
