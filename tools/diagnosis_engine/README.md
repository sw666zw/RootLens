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

The optional explanation layer sits strictly above that engine. It turns a
completed diagnosis into operator-facing prose; it never runs diagnosis or
telemetry collection and cannot choose or change the diagnosis. Application
code—not a provider—copies `diagnosis_id`, root cause, affected service,
confidence, confidence level, and telemetry coverage into the final report.
Candidate scores, available evidence, and the diagnosis outcome remain fixed.

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

Explanation uses another explicit typed projection from the stored diagnosis.
It contains deterministic fields, normalized observations, stable evidence IDs,
coverage, warnings, checks, time window, and input counts. It excludes scenario
names and IDs, expected answers and symptoms, incident filenames, raw logs,
raw trace and Prometheus payloads, SQL, bodies, idempotency keys, database URLs,
credentials, environment contents, and raw exceptions. Changing extra
ground-truth fields in an input JSON cannot change this projection.

Evidence is serialized separately from system instructions and is explicitly
treated as untrusted data. Prompt-like text inside evidence is not an
instruction and cannot request tools or more telemetry. The OpenAI request has
no web search, file search, code execution, functions, or other tools. Strict
Structured Outputs constrain the provider to narrative fields, and Pydantic
validates the result again. Each claim must cite a stable `evidence-NNN` ID;
unknown or empty references fail validation. This prevents a fluent explanation
from inventing supporting telemetry.

## Install and configure

Install in the repository's Python 3.12 environment:

```bash
source .venv/bin/activate
python -m pip install -e "tools/diagnosis_engine[dev]"
```

Template explanations need no additional package, network access, or API key.
To develop or use OpenAI explanations, preserve the development dependencies
and add the optional official SDK dependency:

```bash
python -m pip install -e "tools/diagnosis_engine[dev,llm]"
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

ROOTLENS_EXPLANATION_PROVIDER=template
ROOTLENS_LLM_ENABLED=false
ROOTLENS_EXPLANATION_OUTPUT_DIR=runtime/explanations
ROOTLENS_LLM_TIMEOUT_SECONDS=30
ROOTLENS_LLM_MAX_OUTPUT_TOKENS=1200
OPENAI_API_KEY=
OPENAI_MODEL=gpt-5-mini
```

Template is always the default and `ROOTLENS_LLM_ENABLED=false` disables LLM
use. RootLens never silently switches from template to OpenAI. For OpenAI mode,
create an API key in the OpenAI API platform, store it only in the private
Git-ignored `.env` or a secure secret manager, and never paste it into source,
commands committed to shell history, reports, or logs. A ChatGPT subscription
and OpenAI API access are separate products; a ChatGPT subscription does not
provide API credits or an API key.

Enable OpenAI only in the private environment:

```dotenv
ROOTLENS_EXPLANATION_PROVIDER=openai
ROOTLENS_LLM_ENABLED=true
OPENAI_API_KEY=replace-in-private-env-only
OPENAI_MODEL=gpt-5-mini
```

OpenAI configuration requires a non-empty key and model plus positive timeout
and token limits. The SDK client has automatic retries disabled, uses the
Responses API with `store=false`, sends no files or conversation history, and
makes exactly one bounded request per explanation attempt. GPT-5-family models
use minimal reasoning effort and low text verbosity for this focused structured
summary. Incomplete responses report only status, reason, and available token
counts. Errors are reduced to safe messages; keys, prompts, request payloads,
raw responses, headers, and raw exceptions are never written to reports.

Start Docker and the two services exactly as documented in the root and
scenario-runner READMEs. Fault injection must be enabled only in the private
local-development `.env`. Then generate a fresh incident:

```bash
rootlens-scenario run baseline
rootlens-scenario run inventory-latency --delay-ms 1500
rootlens-scenario run inventory-unavailable
```

## Analyze, evaluate, explain, and validate

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

Explain an existing deterministic diagnosis in default offline template mode:

```bash
rootlens-diagnose explain runtime/diagnoses/<diagnosis-id>.json
```

After loading the enabled OpenAI environment shown above, the same command uses
the OpenAI provider. It does not read an incident report, ground truth, or a
telemetry backend, and it does not modify the diagnosis. To opt in to a clearly
marked deterministic fallback only when that one OpenAI attempt fails:

```bash
rootlens-diagnose explain runtime/diagnoses/<diagnosis-id>.json \
  --allow-template-fallback
```

Without that flag, timeout, connection, refusal, incomplete, malformed, or
schema failures exit nonzero and write no explanation. Configuration failures
never fall back. With the flag, a template report is written with
`provider="template"`, `provider_status="fallback"`, and a safe warning.

Validate any explanation entirely offline against its source diagnosis:

```bash
rootlens-diagnose validate-explanation \
  runtime/explanations/<explanation-id>.json \
  runtime/diagnoses/<diagnosis-id>.json
```

Validation prints `PASS` or `FAIL`, never calls a provider or telemetry source,
does not modify either source file, and writes
`runtime/explanations/<validation-id>.validation.json`. It compares every
protected field, checks the complete compact evidence index, rejects missing,
empty, or invented citations, requires narrative fields, validates provider
status, and rejects ground-truth or obvious credential material.

Explanation reports use deterministic sorted JSON formatting and atomic rename.
They contain the protected diagnosis, provider status, narrative, evidence
index, warnings, and validation summary. OpenAI reports may also include safe
model, response ID, latency, and `provider_usage.input_tokens` and
`provider_usage.output_tokens`; inspect those fields to review token usage.
Generated explanation and validation files are ignored by Git because they are
runtime incident artifacts, while `runtime/explanations/.gitkeep` preserves the
directory.

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
incident correlation IDs. Explanations are limited to an already-generated
diagnosis and do not judge prose quality, query telemetry, execute remediation,
or prove causality beyond deterministic evidence. There is no diagnosis API,
web UI, RAG or vector database, broader incident catalog, alerting, autonomous
tool use, or remediation; a diagnosis API and investigation UI remain future
work.
