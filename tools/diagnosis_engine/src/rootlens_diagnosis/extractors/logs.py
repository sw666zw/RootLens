"""Aggregate bounded Loki log categories and correlation coverage."""

from collections import Counter, defaultdict

from rootlens_diagnosis.models import Evidence, EvidenceSeverity, EvidenceSource
from rootlens_diagnosis.telemetry.models import LogEntry, LogFeatures


def extract_logs(entries: tuple[LogEntry, ...]) -> LogFeatures:
    categories = Counter(
        entry.category for entry in entries if entry.category != "other"
    )
    reasons = Counter(entry.reason for entry in entries if entry.reason is not None)
    order_statuses = Counter(
        entry.status_code
        for entry in entries
        if entry.service == "order"
        and entry.category == "request_completed"
        and entry.status_code is not None
    )
    request_services: dict[str, set[str]] = defaultdict(set)
    trace_services: dict[str, set[str]] = defaultdict(set)
    for entry in entries:
        if entry.request_id:
            request_services[entry.request_id].add(entry.service)
        if entry.trace_id:
            trace_services[entry.trace_id].add(entry.service)
    shared_requests = sum(len(services) > 1 for services in request_services.values())
    shared_traces = sum(len(services) > 1 for services in trace_services.values())
    warning_count = sum(
        (entry.level or "").lower() in {"warning", "warn"} for entry in entries
    )
    error_count = sum(
        (entry.level or "").lower() in {"error", "critical"} for entry in entries
    )
    evidence: list[Evidence] = []
    for category, count in sorted(categories.items()):
        evidence.append(
            Evidence(
                source=EvidenceSource.LOGS,
                signal=category,
                observation=f"Found {count} correlated {category} log events",
                value=float(count),
                unit="events",
                service=_category_service(category),
                severity=EvidenceSeverity.INFORMATIONAL,
                reference=category,
            )
        )
    for reason, count in sorted(reasons.items()):
        evidence.append(
            Evidence(
                source=EvidenceSource.LOGS,
                signal=f"reason_{reason}",
                observation=(
                    f"Found {count} correlated events with safe reason {reason}"
                ),
                value=float(count),
                unit="events",
                severity=EvidenceSeverity.INFORMATIONAL,
                reference=f"reason:{reason}",
            )
        )
    return LogFeatures(
        entries=entries,
        order_status_counts=dict(order_statuses),
        categories=dict(categories),
        reasons=dict(reasons),
        shared_request_ids=shared_requests,
        shared_trace_ids=shared_traces,
        warning_count=warning_count,
        error_count=error_count,
        evidence=tuple(evidence),
    )


def _category_service(category: str) -> str | None:
    if category.startswith("order_"):
        return "order"
    if category.startswith("inventory_"):
        return "inventory"
    return None
