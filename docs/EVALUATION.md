# RootLens evaluation

RootLens evaluates the deterministic diagnosis engine against controlled
scenario ground truth. The benchmark measures repeatability for the current
three-case catalog; it does not claim general incident-diagnosis performance.

## Supported catalog

| Scenario | Expected root cause | Broad expected behavior |
| --- | --- | --- |
| `baseline` | `none` | Orders and reservations succeed without injected delay. |
| `inventory-latency` | `inventory_reservation_latency` | Orders succeed while Inventory reservation latency is elevated. |
| `inventory-unavailable` | `inventory_service_unavailable` | Inventory reservation returns 503 and Order persists a failed outcome. |

`unknown` is a diagnosis fallback for weak, missing, or conflicting evidence;
it is not a generated scenario or an expected answer in the current catalog.

## Methodology

For every selected scenario and repetition, `rootlens-benchmark`:

1. verifies Inventory, Order, Prometheus, Loki, and Jaeger without starting or
   restarting containers;
2. calls the scenario-runner library with the configured request count,
   concurrency, and latency delay;
3. waits the configured telemetry-settle interval;
4. constructs the diagnosis engine's strict safe incident projection;
5. queries and normalizes telemetry, runs deterministic rules, and atomically
   writes a diagnosis report;
6. only then loads evaluation ground truth and writes a separate evaluation;
7. resets Inventory faults after the run and once more during final cleanup;
8. records safe failures and continues when fault state is known to be reset.

The runner never calls scenario or diagnosis CLIs through subprocesses and never
generates template or OpenAI explanations.

## Ground-truth isolation

The analyzer model forbids extra fields and receives only `started_at`,
`ended_at`, `request_ids`, `trace_ids`, `total_requests`, `inventory_sku`, and
`concurrency`. Projection occurs before model validation. The analyzer never
receives scenario name, scenario ID, expected root cause, expected symptoms,
target service, revealing filename, or incident path.

The evaluator accepts two paths only after diagnosis persistence: it validates
the diagnosis schema, then reads `expected_root_cause` from the incident. Tests
assert this operation order and inspect the exact analyzer keys. Reporting may
use a safe scenario label and the expected answer after evaluation; those values
do not flow backward into analysis.

## Metrics

An **exact match** means the diagnosis report's `suspected_root_cause` string is
identical to the scenario's `expected_root_cause`. Overall accuracy is:

```text
exact completed matches / completed evaluated diagnoses
```

Per-scenario accuracy uses the same calculation. A confusion matrix counts
expected-to-predicted pairs. A passing benchmark requires at least one completed
run per configured scenario, a valid evaluation for every completed diagnosis,
100% overall accuracy, and usable telemetry. Any mismatch is a nonzero exit even
if other runs pass.

Confidence is a deterministic quality indicator, not a calibrated probability.
It combines the winning score, margin over the next candidate, number of
supporting source types, and telemetry completeness. Levels are low below 0.5,
medium from 0.5 through 0.799, and high from 0.8. Reports include overall and
per-scenario average confidence plus level counts.

Telemetry coverage is recorded separately for metrics, logs, and traces as
`available`, `partial`, or `unavailable`. Partial coverage can lower confidence.
If all sources are unavailable, the engine returns `unknown` with zero confidence
and the benchmark exits nonzero. `--require-all-sources` additionally makes any
unavailable source non-passing.

## Run and inspect

Install the local tools:

```bash
python3.12 -m pip install -e 'tools/scenario_runner[dev]' \
  -e 'tools/diagnosis_engine[dev]' -e 'tools/benchmark_runner[dev]'
```

After starting the application and observability stack described in
[DEMO.md](DEMO.md), run:

```bash
rootlens-benchmark run
```

Tune only supported benchmark parameters when necessary:

```bash
rootlens-benchmark run --repetitions 3 --requests 10 --concurrency 5 \
  --latency-delay-ms 1500 --telemetry-settle-seconds 15 \
  --require-all-sources
```

Inspect the generated JSON and Markdown under `runtime/benchmarks`, or print an
existing JSON report without network or telemetry work:

```bash
rootlens-benchmark summarize runtime/benchmarks/BENCHMARK_ID.json
```

## Interpretation and limitations

The catalog has three synthetic, controlled cases in one application topology.
Repeated 100% accuracy shows that the current rules can distinguish those cases
under the tested local telemetry conditions. It does not establish accuracy for
novel failures, noisy production telemetry, different architectures, causal
interactions, database failures, or multi-incident windows. Scenario traffic may
also be affected by host scheduling and telemetry scrape timing.

LLM prose is excluded from accuracy because providers cannot choose the root
cause and prose quality is subjective. Explanation validation checks protected
fields and evidence references; it is not a substitute for evaluating factual
root-cause selection. Dependency audits and tests reduce known risk but do not
prove the project vulnerability-free.

## Dependency validation snapshot

The Milestone 4 review on 2026-08-11 upgraded React Router DOM to 7.18.2,
Vite to 6.4.3, Vitest to 3.2.7, ESLint and `@eslint/js` to 9.39.5, and refreshed
`package-lock.json`. These direct updates removed the audit's production React
Router advisories and development-tool findings without `npm audit fix --force`.
The post-update `npm audit --json` reported zero known advisories. That is a
time-specific registry result, not a claim that the project is completely
vulnerability-free; CI reruns the audit and fails for high or critical findings.

Python packages use bounded version ranges rather than a separate heavy security
scanner. CI installs every local package together and runs `python -m pip check`
before tests to catch inconsistent or missing requirements. Maintainers should
review upstream Python advisories and refresh dependencies regularly.
