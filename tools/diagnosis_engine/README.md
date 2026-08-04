# RootLens deterministic diagnosis engine

This Python 3.12 local-development tool correlates one scenario runner incident
with Prometheus metrics, Loki logs, and exact Jaeger traces. Correlation means
placing independently collected signals in the same bounded time and request
context, then testing transparent root-cause rules against the combined
evidence. It is a command-line tool, not a web server.

Metrics show aggregate rates, status distributions, availability, outcomes,
and latency. Logs show discrete domain outcomes and connect the same request ID
across Order and Inventory. Traces show where each request spent time, where it
failed, and whether normal PostgreSQL work occurred. No one source provides all
three views.

The first engine is deliberately deterministic. Its fixed rules and visible
candidate scores make regressions reproducible and create a trustworthy
baseline for evaluating future AI behavior. Confidence is a bounded indicator
derived from rule score, winning margin, independent source count, and source
completeness. It is not a mathematical probability. A single-source result
cannot be high confidence.

## Supported diagnoses

- `none`: healthy Order and Inventory behavior.
- `inventory_reservation_latency`: requests generally succeed but Inventory
  reservation work dominates elevated latency.
- `inventory_service_unavailable`: 503 outcomes and correlated failures center
  on Inventory, often before normal database work.
- `unknown`: evidence is weak, conflicting, unavailable, or outside this small
  catalog.

Supporting observations add bounded score and contradicting observations
subtract it. Missing telemetry never supports a candidate. A candidate must
clear both a minimum score and winning-margin threshold. The report exposes
every candidate score and its supporting and contradicting references.

## Ground-truth isolation

Scenario reports intentionally contain evaluation answers. Before analysis,
the loader constructs a frozen projection containing only `started_at`,
`ended_at`, `request_ids`, `trace_ids`, `total_requests`, `inventory_sku`, and
`concurrency`. The engine and rules never receive `scenario_name`,
`expected_root_cause`, `expected_symptoms`, `target_service`, the filename, or
the revealing scenario ID. SKU is used only as safe context and is never a
Prometheus label. The separate `evaluate` command reads
`expected_root_cause` only after loading an already-written diagnosis; it does
not query telemetry or alter the diagnosis.

## Install and configure

Install in the repository's Python 3.12 environment:

```bash
source .venv/bin/activate
python -m pip install -e "tools/diagnosis_engine[dev]"
```

Do not commit `.env`. Copy these safe local defaults from `.env.example` into
an existing private `.env` when they are missing:

```dotenv
PROMETHEUS_URL=http://localhost:9090
LOKI_URL=http://localhost:3100
JAEGER_QUERY_URL=http://localhost:16686
ROOTLENS_DIAGNOSIS_OUTPUT_DIR=runtime/diagnoses
ROOTLENS_DIAGNOSIS_WINDOW_PADDING_SECONDS=15
ROOTLENS_TELEMETRY_TIMEOUT_SECONDS=10
```

Start Docker and the two services exactly as documented in the root and
scenario-runner READMEs. Fault injection must be enabled only in the private
local-development `.env`. Then generate a fresh incident:

```bash
rootlens-scenario run baseline
rootlens-scenario run inventory-latency --delay-ms 1500
rootlens-scenario run inventory-unavailable
```

## Analyze and evaluate

Analyze one report using its actual path:

```bash
set -a
source .env
set +a
rootlens-diagnose analyze runtime/incidents/<scenario-id>.json
```

Options can override the environment:

```bash
rootlens-diagnose analyze runtime/incidents/<scenario-id>.json \
  --output-dir runtime/diagnoses \
  --prometheus-url http://localhost:9090 \
  --loki-url http://localhost:3100 \
  --jaeger-url http://localhost:16686 \
  --window-padding-seconds 15 \
  --require-all-sources
```

The window is always incident start minus padding through incident end plus
padding, normalized to UTC and capped at one hour. Source requests run
concurrently and fail independently. Without `--require-all-sources`, available
evidence can produce a lower-confidence partial diagnosis. If all sources are
unavailable, the tool still writes `unknown` with confidence zero and exits
nonzero. With `--require-all-sources`, any unavailable source causes a nonzero
exit after report writing.

Evaluate the completed diagnosis separately:

```bash
rootlens-diagnose evaluate \
  runtime/diagnoses/<diagnosis-id>.json \
  runtime/incidents/<scenario-id>.json
```

Diagnosis files are written atomically to
`runtime/diagnoses/<diagnosis-id>.json`. Evaluations use
`runtime/diagnoses/<evaluation-id>.evaluation.json`. Generated JSON is ignored
by Git because it is runtime evidence; `.gitkeep` preserves the directory.

## Inspect evidence references

Use the report's safe `reference` values as query names or categories. Inspect
the corresponding fixed metric family in Prometheus at
<http://127.0.0.1:9090/graph>. In Grafana Explore, select Loki and correlate a
request or trace:

```logql
{service=~"order|inventory"} | json | request_id="replace-with-request-id"
{service=~"order|inventory"} | json | trace_id="replace-with-trace-id"
```

Open <http://127.0.0.1:16686>, paste a report trace ID, and compare Order server,
Order-to-Inventory client, Inventory server, and PostgreSQL spans. The diagnosis
report stores only normalized safe attributes, counts, durations, categories,
and trace IDs—not full responses, SQL, parameters, request bodies, raw
exceptions, credentials, or idempotency keys.

## Verify

Normal tests use HTTPX `MockTransport`, fixtures, and temporary directories;
they require no Docker or live service:

```bash
python -m pytest tools/diagnosis_engine
python -m ruff check tools/diagnosis_engine
python -m ruff format --check tools/diagnosis_engine
```

For the entire repository and tracked stack configuration:

```bash
python -m pytest
python -m ruff check services/inventory services/order tools/scenario_runner \
  tools/diagnosis_engine
docker compose config
curl -fsS http://127.0.0.1:9090/-/ready
curl -fsS http://127.0.0.1:3100/ready
curl -fsS http://127.0.0.1:16686/
```

## Current limits

The engine recognizes only the three controlled Milestone 3 outcomes and uses
in-memory Jaeger retention. Aggregate Prometheus increases may include nearby
traffic within the padded window, while logs and traces are narrowed with
incident correlation IDs. There is no LLM explanation layer, diagnosis API,
UI, broader incident catalog, alerting, or remediation; those are future
milestones.
