# RootLens evaluation

RootLens evaluates the authoritative deterministic diagnosis engine against controlled scenario ground truth. The benchmark measures repeatability across the current supported catalog; it does not claim coverage of arbitrary production incidents.

## Supported scenarios and targets

| Scenario | Supported evaluation target | Controlled behavior |
| --- | --- | --- |
| `baseline` | `none` | Orders and Inventory reservations succeed without an injected fault. |
| `inventory-latency` | `inventory_reservation_latency` | Inventory reservation latency is injected while requests remain successful. |
| `inventory-unavailable` | `inventory_service_unavailable` | Inventory reservation returns 503 and Order persists failed outcomes. |

`unknown` is the safe diagnosis fallback for weak, missing, conflicting, or out-of-catalog evidence. It is not a generated scenario or expected target in the current benchmark.

## Evaluation ordering

For every configured scenario repetition, `rootlens-benchmark`:

1. Verifies Inventory, Order, Prometheus, Loki, and Jaeger without starting or restarting them.
2. Runs the controlled scenario with the configured request count, concurrency, and latency delay.
3. Waits the configured telemetry-settle interval.
4. Projects the incident onto the diagnosis engine's strict safe context.
5. Queries and normalizes metrics, logs, and traces.
6. Runs deterministic rules and atomically writes the diagnosis report.
7. Loads ground truth afterward and writes a separate evaluation.
8. Records timing and safe failure information, then continues only when fault reset is known to be safe.
9. Resets Inventory faults after each run and again during final cleanup.

The default configuration uses all three scenarios, three repetitions, 10 requests, concurrency 5, a 1500 ms latency fault, and a 15-second telemetry-settle interval. Scenario repetitions expose nondeterminism from concurrency, scrape timing, or local scheduling instead of relying on one favorable run.

## Ground-truth isolation

`expected_root_cause` is not available to the analyzer. Before validation, the incident loader copies only `started_at`, `ended_at`, `request_ids`, `trace_ids`, `total_requests`, `inventory_sku`, and `concurrency` into an immutable model that forbids extra fields.

The analyzer never receives scenario name or ID, expected symptoms, target service, a revealing filename, or the incident path. Diagnosis is completed and written first. The separate evaluator then validates that diagnosis and reads only `expected_root_cause` from the incident. Tests assert the operation order and exact analyzer keys. Scenario labels may be used for post-evaluation aggregation but must not leak into analysis.

## Metrics and reports

An **exact match** means `suspected_root_cause` is identical to `expected_root_cause`. Overall accuracy is:

```text
exact completed matches / completed evaluated diagnoses
```

Per-scenario accuracy applies the same calculation. The confusion matrix counts each expected-to-predicted pair so systematic misclassification remains visible.

**Confidence** is a deterministic quality indicator, not a calibrated probability. It combines the winning candidate score, margin over the next candidate, independent supporting source types, and telemetry completeness. Reports aggregate average confidence overall and by scenario, plus confidence-level counts:

- `low`: below 0.5
- `medium`: 0.5 through 0.799
- `high`: 0.8 and above

**Telemetry coverage** records metrics, logs, and traces independently as `available`, `partial`, or `unavailable`. Partial coverage can reduce confidence. With all sources unavailable the engine returns `unknown` at zero confidence and the benchmark does not pass. `--require-all-sources` additionally makes any unavailable source non-passing.

**Diagnosis duration** measures the deterministic telemetry collection and analysis portion of each completed run. Scenario duration is tracked separately. Benchmark JSON and Markdown reports include configuration, run summaries, overall and per-scenario results, confidence aggregates, telemetry-coverage counts, scenario and diagnosis duration statistics, warnings, and the confusion matrix.

A passing benchmark requires at least one completed evaluation for every configured scenario, a valid evaluation for every completed diagnosis, usable telemetry, and 100% exact-match accuracy. This threshold is intentionally strict for the small controlled catalog and should not be generalized.

LLM prose quality is not used to calculate root-cause accuracy. Explanation providers cannot select the root cause, the benchmark does not call them, and deterministic explanation validation measures schema and evidence constraints rather than narrative style.

## Run and inspect

After starting the application and observability stack described in [DEMO.md](DEMO.md):

```bash
rootlens-benchmark run
```

An explicit equivalent configuration is:

```bash
rootlens-benchmark run \
  --scenarios baseline,inventory-latency,inventory-unavailable \
  --repetitions 3 \
  --requests 10 \
  --concurrency 5 \
  --latency-delay-ms 1500 \
  --telemetry-settle-seconds 15
```

Inspect generated JSON and Markdown under `runtime/benchmarks`, or summarize an existing JSON report without running scenarios or querying telemetry:

```bash
rootlens-benchmark summarize runtime/benchmarks/BENCHMARK_ID.json
```

Generated runtime benchmark reports are ignored. The tracked [benchmark summary](examples/benchmark-summary.example.json) and other files under [examples](examples/README.md) are synthetic, schema-preserving documentation examples; they are not results from a live developer run. No benchmark number is claimed here.

## Limitations

- The catalog contains three synthetic, controlled scenarios in one application topology.
- Faults are deliberately injected in a local development environment.
- Aggregate metrics can include nearby traffic within the padded analysis window.
- Results can be affected by host scheduling and telemetry scrape or ingestion timing.
- The rules do not cover novel services, database incidents, overlapping causes, noisy production environments, or arbitrary real-world failures.
- Exact-match accuracy across this catalog is not evidence of general production incident-diagnosis accuracy.
- Explanation validation does not measure prose quality, and dependency checks do not constitute a formal security audit.
