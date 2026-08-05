# RootLens web interface

RootLens Web is a local-development React and TypeScript investigation console for incidents, deterministic diagnoses, evidence-grounded explanations, and offline explanation validation. The browser calls only the Diagnosis Service API. It never invokes RootLens CLIs, reads report files, accesses PostgreSQL, queries Prometheus, Loki, or Jaeger, or calls OpenAI directly.

## Install and run

Use Node.js 20 or newer. From the repository root, install the locked frontend dependencies:

```bash
cd apps/web
npm ci
```

Copy only the public frontend example if local overrides are needed:

```bash
cp apps/web/.env.example apps/web/.env.local
```

Do not copy the repository's private backend `.env` into `apps/web`. Vite exposes variables prefixed with `VITE_` to browser code, so frontend configuration contains only the Diagnosis Service proxy path and public local tool URLs.

Start the existing infrastructure and backend services from the repository root. The private root `.env` must enable Inventory fault injection for scenario generation; OpenAI remains disabled unless it is explicitly configured there.

```bash
docker compose up -d
set -a
source .env
set +a
alembic -c services/inventory/alembic.ini upgrade head
alembic -c services/order/alembic.ini upgrade head
```

Run each host service in a separate terminal:

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

Start the frontend in a fourth terminal:

```bash
cd apps/web
npm run dev
```

Open <http://localhost:5173>. Vite proxies browser requests under `/api/*` to `http://localhost:8002/*`. This same-origin development proxy avoids exposing the backend directly to browser code and avoids adding development-only CORS behavior to the Diagnosis Service.

## Browser workflow

Generate an incident from the repository root:

```bash
rootlens-scenario run baseline
rootlens-scenario run inventory-latency --delay-ms 1500
rootlens-scenario run inventory-unavailable
```

Then:

1. Open **Incidents**, select the new safe incident summary, and choose **Run diagnosis**. Requiring every telemetry source turns unavailable telemetry into a safe failure; otherwise partial sources may produce a lower-confidence report.
2. Review the deterministic root cause, confidence, candidate scores, coverage, warnings, normalized evidence, alternatives, and recommended checks.
3. Generate a template explanation, or explicitly select OpenAI. OpenAI mode works only when the Diagnosis Service backend has `ROOTLENS_LLM_ENABLED=true` and a private `OPENAI_API_KEY`. The browser never receives, requests, stores, or displays that key. A successful response is the only indication that the backend accepted the OpenAI request.
4. Review claims and their evidence references, then validate the explanation. Validation is deterministic and offline: it does not change the explanation and does not call OpenAI again.

The deterministic diagnosis is the authoritative, reproducible analysis of normalized telemetry. An LLM explanation is constrained operator-facing prose over that completed diagnosis; it cannot select or alter the root cause, affected service, confidence, evidence, or outcome.

Use the sidebar links to open Grafana at <http://localhost:3000>, Jaeger at <http://localhost:16686>, and Prometheus at <http://localhost:9090>. These links open the tools directly for a human operator; the frontend does not query them.

## Quality checks

Frontend tests mock `fetch` and require no live Diagnosis Service, telemetry backend, database, Docker service, or OpenAI request:

```bash
cd apps/web
npm run test:run
npm run lint
npm run format:check
npm run typecheck
npm run build
```

For watch mode and a local production preview:

```bash
npm test
npm run preview
```

The current interface is for trusted local development. Authentication, deployment, automated remediation, and production hardening remain future work.
