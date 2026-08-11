# RootLens benchmark runner

`rootlens-benchmark` evaluates the supported deterministic diagnosis catalog by
calling the scenario-runner and diagnosis-engine Python libraries directly. It
does not invoke their CLIs, generate explanations, or call OpenAI.

Install the three local tools with development dependencies from the repository
root:

```bash
python3.12 -m pip install -e 'tools/scenario_runner[dev]' \
  -e 'tools/diagnosis_engine[dev]' -e 'tools/benchmark_runner[dev]'
```

With the local services and observability stack already running, execute the
default three-scenario benchmark:

```bash
rootlens-benchmark run
```

Reports are written atomically to `runtime/benchmarks`. Override repetition,
traffic, settling, or selection when needed:

```bash
rootlens-benchmark run \
  --scenarios baseline,inventory-latency,inventory-unavailable \
  --repetitions 3 --requests 10 --concurrency 5 \
  --latency-delay-ms 1500 --telemetry-settle-seconds 15
```

Read an existing JSON report without running scenarios or querying services:

```bash
rootlens-benchmark summarize runtime/benchmarks/BENCHMARK_ID.json
```

Diagnosis receives only the diagnosis engine's allowlisted incident projection.
The evaluator reads `expected_root_cause` only after the diagnosis JSON has been
written. A run is non-passing for a mismatch, evaluation failure, unavailable
telemetry, missing per-scenario completion, unsafe reset failure, or report-write
failure. The runner never starts, stops, or restarts Docker containers.
