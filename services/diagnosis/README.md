# RootLens Diagnosis Service

This Python 3.12 FastAPI service wraps the existing deterministic
`rootlens-diagnosis-engine` library. It lists scenario artifacts, collects telemetry
and writes normal diagnosis reports, explains an existing diagnosis, and validates
an explanation. It imports the engine directly and never invokes the CLI or shell.

The CLI remains useful for scripts, offline inspection, and evaluation against
private scenario ground truth. API clients use report IDs instead of local paths.
Each configured report root is resolved at startup; strict IDs reject absolute
paths, dots, separators, and encoded traversal. Only direct `.json` files are read,
and temporary, evaluation, and validation files are excluded where appropriate.

Incident projections omit `expected_root_cause`, `expected_symptoms`,
`target_service`, raw request IDs, and raw trace IDs. Diagnosis receives only the
engine's safe `IncidentAnalysisContext`, so evaluation ground truth cannot influence
analysis or appear in diagnosis responses.

## Install and configure

Use the repository's private Python 3.12 environment and install the local engine
and service packages:

```bash
source .venv/bin/activate
python -m pip install -e "tools/diagnosis_engine[dev]"
python -m pip install -e "services/diagnosis[dev]"
```

Do not commit `.env`. Create it only if missing, or add missing values to the
existing private file:

```bash
cp .env.example .env
```

The example provides port `8002`, all three runtime report directories, telemetry
URLs and timeouts, `runtime/logs/diagnosis.jsonl`, and the Diagnosis OpenTelemetry
service name. Template explanation mode and `ROOTLENS_LLM_ENABLED=false` remain the
defaults and require no OpenAI package.

For explicit OpenAI use, separately install the optional engine dependency and set
these values only in the private environment. Never put a real key in source or a
command:

```bash
python -m pip install -e "tools/diagnosis_engine[llm]"
```

```dotenv
ROOTLENS_EXPLANATION_PROVIDER=openai
ROOTLENS_LLM_ENABLED=true
OPENAI_API_KEY=replace-in-private-env-only
OPENAI_MODEL=gpt-5-mini
```

## Run the local system

Start the existing infrastructure (Diagnosis remains a host process, not a new
container), load the private environment, and apply existing migrations:

```bash
docker compose up -d
set -a
source .env
set +a
alembic -c services/inventory/alembic.ini upgrade head
alembic -c services/order/alembic.ini upgrade head
```

Run each service in its own terminal:

```bash
uvicorn --app-dir services/inventory/src inventory_service.main:app \
  --reload --host 0.0.0.0 --port 8000 --env-file .env
uvicorn --app-dir services/order/src order_service.main:app \
  --reload --host 0.0.0.0 --port 8001 --env-file .env
uvicorn --app-dir services/diagnosis/src diagnosis_service.main:app \
  --reload --host 0.0.0.0 --port 8002 --env-file .env
```

Generate a scenario, then use only its ID with the API:

```bash
rootlens-scenario run baseline
curl -sS 'http://127.0.0.1:8002/incidents?limit=50'
curl -sS 'http://127.0.0.1:8002/incidents/<scenario-id>'
curl -sS -X POST \
  'http://127.0.0.1:8002/incidents/<scenario-id>/diagnose' \
  -H 'Content-Type: application/json' \
  -d '{"require_all_sources":false,"window_padding_seconds":null}'
curl -sS 'http://127.0.0.1:8002/diagnoses/<diagnosis-id>'
curl -sS -X POST \
  'http://127.0.0.1:8002/diagnoses/<diagnosis-id>/explain' \
  -H 'Content-Type: application/json' \
  -d '{"provider":"template","allow_template_fallback":false}'
curl -sS -X POST \
  'http://127.0.0.1:8002/explanations/<explanation-id>/validate' \
  -H 'Content-Type: application/json' \
  -d '{"diagnosis_id":"<diagnosis-id>"}'
```

OpenAI fallback happens only when the request explicitly sets
`allow_template_fallback=true`. Keys, prompts, provider responses, raw telemetry,
paths, and raw exceptions are neither returned nor logged.

## Observe and verify

```bash
curl -fsS http://127.0.0.1:8002/health
curl -sS http://127.0.0.1:8002/metrics
tail -f runtime/logs/diagnosis.jsonl
open http://127.0.0.1:9090/targets
open http://127.0.0.1:3000
open http://127.0.0.1:16686
```

Grafana provisions **RootLens Diagnosis Service Overview**. In Explore, select Loki:

```logql
{service="diagnosis"} | json | message="diagnosis_completed"
{service="diagnosis"} | json | message="diagnosis_failed"
{service="diagnosis"} | json | message="explanation_completed"
{service="diagnosis"} | json | diagnosis_id="<diagnosis-id>"
{service="diagnosis"} | json | incident_id="<scenario-id>"
{service="diagnosis"} | json | request_id="<request-id>"
{service="diagnosis"} | json | trace_id="<trace-id>"
```

IDs are JSON fields, never Loki labels. Normal verification needs no live telemetry,
Docker, databases, or OpenAI:

```bash
python -m pytest services/diagnosis
python -m ruff check services/diagnosis
python -m ruff format --check services/diagnosis
python -m pytest
python -m ruff check services/inventory services/order services/diagnosis \
  tools/scenario_runner tools/diagnosis_engine
docker compose config
```

The React/TypeScript investigation interface uses this service as its only
backend. Remediation, scheduling, alerting, authentication, a service database,
and workers are not implemented.
