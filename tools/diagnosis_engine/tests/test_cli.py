import json
from argparse import Namespace
from pathlib import Path

import pytest

from rootlens_diagnosis.cli import build_parser, run_analyze
from rootlens_diagnosis.engine import empty_telemetry
from rootlens_diagnosis.models import SourceStatus


def _incident(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "scenario_name": "must-not-be-used",
                "expected_root_cause": "must-not-be-used",
                "expected_symptoms": ["must-not-be-used"],
                "started_at": "2026-08-03T20:00:00Z",
                "ended_at": "2026-08-03T20:00:20Z",
                "request_ids": ["request-1"],
                "trace_ids": ["0af7651916cd43dd8448eb211c80319c"],
                "total_requests": 1,
                "inventory_sku": "SAFE-SKU",
                "concurrency": 1,
            }
        ),
        encoding="utf-8",
    )


def _args(incident: Path, output: Path, require_all: bool = False) -> Namespace:
    return Namespace(
        incident_report=incident,
        output_dir=output,
        prometheus_url="http://prometheus.test",
        loki_url="http://loki.test",
        jaeger_url="http://jaeger.test",
        window_padding_seconds=15,
        require_all_sources=require_all,
    )


def test_invalid_cli_arguments_fail_clearly() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(
            ["analyze", "missing.json", "--window-padding-seconds", "-1"]
        )


@pytest.mark.asyncio
async def test_analyze_all_source_failure_writes_report_and_returns_nonzero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    incident = tmp_path / "incident.json"
    output = tmp_path / "diagnoses"
    _incident(incident)

    async def unavailable(*args: object) -> object:
        return empty_telemetry()

    monkeypatch.setattr("rootlens_diagnosis.cli.collect_telemetry", unavailable)
    result = await run_analyze(_args(incident, output))
    reports = list(output.glob("*.json"))
    assert result == 1
    assert len(reports) == 1
    assert json.loads(reports[0].read_text())["suspected_root_cause"] == "unknown"


@pytest.mark.asyncio
async def test_require_all_sources_returns_nonzero_after_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    incident = tmp_path / "incident.json"
    output = tmp_path / "diagnoses"
    _incident(incident)

    async def partial(*args: object) -> object:
        return empty_telemetry(SourceStatus.PARTIAL)

    monkeypatch.setattr("rootlens_diagnosis.cli.collect_telemetry", partial)
    assert await run_analyze(_args(incident, output, require_all=True)) == 0

    async def one_missing(*args: object) -> object:
        telemetry = empty_telemetry(SourceStatus.PARTIAL)
        return telemetry.__class__(
            telemetry.metrics,
            telemetry.logs,
            telemetry.traces.__class__(SourceStatus.UNAVAILABLE, telemetry.traces.data),
        )

    monkeypatch.setattr("rootlens_diagnosis.cli.collect_telemetry", one_missing)
    assert await run_analyze(_args(incident, output, require_all=True)) == 1
