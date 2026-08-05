"""ID-only, root-confined JSON report access."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote

REPORT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


class ReportNotFoundError(LookupError):
    """A supported report ID was not found."""


class InvalidReportError(ValueError):
    """A stored report is unreadable, malformed, or invalid."""


class UnsupportedReportError(ValueError):
    """A caller supplied something other than a strict report ID."""


def validate_report_id(report_id: str) -> str:
    decoded = report_id
    for _ in range(3):
        next_value = unquote(decoded)
        if next_value == decoded:
            break
        decoded = next_value
    if (
        decoded != report_id
        or not REPORT_ID.fullmatch(report_id)
        or Path(report_id).is_absolute()
        or ".." in report_id
    ):
        raise UnsupportedReportError("unsupported report ID")
    return report_id


@dataclass(frozen=True)
class ReportFileRepository:
    """Read one report family without accepting filesystem paths."""

    root: Path
    id_field: str
    excluded_suffixes: tuple[str, ...] = ()

    def __init__(
        self,
        root: Path,
        id_field: str,
        excluded_suffixes: tuple[str, ...] = (),
    ) -> None:
        object.__setattr__(self, "root", root.expanduser().resolve())
        object.__setattr__(self, "id_field", id_field)
        object.__setattr__(self, "excluded_suffixes", excluded_suffixes)

    def list(self, limit: int) -> list[dict[str, Any]]:
        reports: list[dict[str, Any]] = []
        for path in self._candidates():
            try:
                reports.append(self._read(path))
            except InvalidReportError:
                continue
            if len(reports) >= min(limit, 200):
                break
        return reports

    def get(self, report_id: str) -> dict[str, Any]:
        report_id = validate_report_id(report_id)
        direct = self.root / f"{report_id}.json"
        if direct.is_file() and self._supported(direct):
            payload = self._read(direct)
            if payload.get(self.id_field) == report_id:
                return payload
        for path in self._candidates():
            if path == direct:
                continue
            try:
                payload = self._read(path)
            except InvalidReportError:
                continue
            if payload.get(self.id_field) == report_id:
                return payload
        raise ReportNotFoundError(report_id)

    def path_for(self, report_id: str) -> Path:
        """Resolve a stored report internally after validating its embedded ID."""
        report_id = validate_report_id(report_id)
        direct = self.root / f"{report_id}.json"
        if direct.is_file() and self._supported(direct):
            payload = self._read(direct)
            if payload.get(self.id_field) == report_id:
                return direct
        for path in self._candidates():
            try:
                if self._read(path).get(self.id_field) == report_id:
                    return path
            except InvalidReportError:
                continue
        raise ReportNotFoundError(report_id)

    def _candidates(self) -> list[Path]:
        if not self.root.is_dir():
            return []
        return sorted(
            (path for path in self.root.iterdir() if self._supported(path)),
            key=lambda path: path.stat().st_mtime_ns,
            reverse=True,
        )

    def _supported(self, path: Path) -> bool:
        name = path.name
        return (
            path.is_file()
            and path.parent.resolve() == self.root
            and path.suffix == ".json"
            and not name.startswith(".")
            and not any(name.endswith(suffix) for suffix in self.excluded_suffixes)
        )

    @staticmethod
    def _read(path: Path) -> dict[str, Any]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise InvalidReportError("invalid stored report") from error
        if not isinstance(payload, dict):
            raise InvalidReportError("invalid stored report")
        return payload


@dataclass(frozen=True)
class ReportRepositories:
    incidents: ReportFileRepository
    diagnoses: ReportFileRepository
    explanations: ReportFileRepository

    @classmethod
    def create(
        cls, incident_dir: Path, diagnosis_dir: Path, explanation_dir: Path
    ) -> ReportRepositories:
        return cls(
            incidents=ReportFileRepository(incident_dir, "scenario_id"),
            diagnoses=ReportFileRepository(
                diagnosis_dir, "diagnosis_id", (".evaluation.json",)
            ),
            explanations=ReportFileRepository(
                explanation_dir, "explanation_id", (".validation.json",)
            ),
        )
