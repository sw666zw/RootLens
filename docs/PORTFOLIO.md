# RootLens portfolio material

## One-line description

RootLens is a local observability and deterministic incident-diagnosis platform that correlates metrics, logs, and traces across a distributed application.

## Project summary

RootLens instruments independent FastAPI Inventory and Order services, their service-owned PostgreSQL databases, and a Diagnosis Service with Prometheus, Loki, and OpenTelemetry. It converts normalized telemetry into an authoritative deterministic root-cause report, then can generate an optional evidence-grounded explanation that is checked by an offline validator. A React/TypeScript interface and repeatable benchmark make the complete investigation and evaluation workflow inspectable.

## Resume bullet candidates

- Built distributed Python 3.12/FastAPI Inventory and Order services with separate PostgreSQL ownership, explicit Alembic migrations, durable order state transitions, propagated request and trace context, and PostgreSQL-backed idempotent order creation.
- Instrumented Inventory, Order, and Diagnosis services with bounded-cardinality Prometheus metrics, structured JSON logging through Grafana Alloy to Loki, and OpenTelemetry traces through the Collector to Jaeger; provisioned Grafana dashboards for cross-service investigation.
- Designed and evaluated a deterministic diagnosis pipeline that normalizes metrics, logs, and traces, exposes candidate scores and confidence, isolates scenario ground truth, constrains optional LLM explanations to completed diagnoses, and benchmarks exact-match accuracy across the controlled supported incident catalog.

## GitHub repository description

Deterministic incident diagnosis from correlated metrics, logs, and traces in a distributed FastAPI system.

## Suggested GitHub topics

`observability` · `distributed-systems` · `fastapi` · `react` · `typescript` · `postgresql` · `opentelemetry` · `prometheus` · `grafana` · `loki` · `jaeger` · `root-cause-analysis` · `llm` · `python`

## LinkedIn project description

Built RootLens, a local observability and automated incident-diagnosis platform around distributed Inventory and Order services. The system correlates Prometheus metrics, Loki logs, and Jaeger traces into deterministic, evidence-backed root-cause reports, then optionally produces an LLM explanation without allowing the model to change the diagnosis. A FastAPI Diagnosis Service, React/TypeScript investigation interface, controlled incident runner, deterministic validator, repeatable benchmark, and GitHub Actions pipeline make the architecture and its limitations directly inspectable.

## 20–30 second explanation

RootLens is a small distributed commerce system that I instrumented end to end with metrics, centralized logs, and traces. It generates controlled incidents, correlates the resulting telemetry, and uses transparent deterministic rules to identify one of its supported root causes. An optional LLM can explain that completed result, but it cannot choose or change it, and the explanation is validated against the original evidence. The whole workflow is available through a FastAPI service, a React interface, and a repeatable benchmark.
