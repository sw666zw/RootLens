# RootLens

RootLens is a planned observability and automated incident-diagnosis platform for distributed services. Modern systems emit logs, metrics, and distributed traces across many components, but investigating an incident still requires engineers to manually connect those signals. RootLens will collect and correlate telemetry, reconstruct the context around failures, and surface evidence-backed likely root causes so teams can diagnose incidents faster.

## Planned architecture

RootLens is expected to include telemetry ingestion for logs, metrics, and traces; a shared correlation and storage layer; an analysis engine for detecting incidents and ranking likely causes; and APIs or interfaces for investigating the supporting evidence. The architecture will evolve milestone by milestone as the project validates each capability.

## Initial milestone roadmap

1. Build a small inventory service that will later serve as a system under observation.
2. Instrument the inventory service and establish collection of logs, metrics, and distributed traces.
3. Correlate telemetry across requests, services, and time windows.
4. Detect representative incidents and generate evidence-backed root-cause hypotheses.
5. Provide an investigation experience for reviewing incidents, correlated signals, and likely causes.

Milestone 1 is underway with Inventory Service health endpoints, request IDs,
structured request logging, a local PostgreSQL foundation, and the first
persistent inventory-item create/read API. Concurrency-safe stock reservation is
also implemented with a PostgreSQL row lock to prevent overselling. Update,
delete, restocking, reservation history, and an Order Service remain planned.
Broader observability capabilities such as metrics and tracing are also not
implemented yet.
