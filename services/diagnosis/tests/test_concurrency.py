"""Atomic writers remain safe under concurrent API-style report creation."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

from rootlens_diagnosis.engine import DiagnosisEngine
from rootlens_diagnosis.incident_context import AnalysisWindow, IncidentAnalysisContext
from rootlens_diagnosis.reports import write_diagnosis_report

from diagnosis_service.services.diagnosis import unavailable_telemetry


def make_report():
    now = datetime(2026, 8, 5, tzinfo=UTC)
    context = IncidentAnalysisContext(
        started_at=now.isoformat(),
        ended_at=(now + timedelta(seconds=1)).isoformat(),
        request_ids=(),
        trace_ids=(),
        total_requests=1,
        concurrency=1,
    )
    window = AnalysisWindow(start=now, end=now + timedelta(seconds=1))
    return DiagnosisEngine().analyze(context, window, unavailable_telemetry())


def test_concurrent_report_creation_is_unique_and_valid(settings):
    def create_one(_index: int):
        report = make_report()
        return report.diagnosis_id, write_diagnosis_report(
            report, settings.diagnosis.output_dir
        )

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(create_one, range(8)))
    assert len({diagnosis_id for diagnosis_id, _ in results}) == 8
    assert all(path.is_file() for _, path in results)
