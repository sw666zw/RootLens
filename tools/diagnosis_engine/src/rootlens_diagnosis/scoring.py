"""Predictable bounded scoring and non-probabilistic confidence."""

from dataclasses import dataclass, field

from rootlens_diagnosis.models import (
    CandidateScore,
    EvidenceSource,
    SourceStatus,
    TelemetryCoverage,
)


@dataclass
class ScoreBuilder:
    raw_score: float = 0.0
    supporting: list[str] = field(default_factory=list)
    contradicting: list[str] = field(default_factory=list)
    sources: set[EvidenceSource] = field(default_factory=set)

    def support(self, weight: float, reference: str, source: EvidenceSource) -> None:
        self.raw_score += weight
        self.supporting.append(reference)
        self.sources.add(source)

    def contradict(self, weight: float, reference: str) -> None:
        self.raw_score -= weight
        self.contradicting.append(reference)

    def build(self) -> CandidateScore:
        return CandidateScore(
            score=round(max(0.0, min(1.0, self.raw_score)), 3),
            supporting_evidence=sorted(set(self.supporting)),
            contradicting_evidence=sorted(set(self.contradicting)),
        )


def confidence(
    score: float,
    margin: float,
    source_count: int,
    coverage: TelemetryCoverage,
) -> float:
    """Calculate a bounded quality indicator, not a probability."""
    if score <= 0 or source_count <= 0:
        return 0.0
    completeness_values = {
        SourceStatus.AVAILABLE: 1.0,
        SourceStatus.PARTIAL: 0.5,
        SourceStatus.UNAVAILABLE: 0.0,
    }
    completeness = (
        sum(
            completeness_values[item]
            for item in (coverage.metrics, coverage.logs, coverage.traces)
        )
        / 3
    )
    source_factor = 0.45 + 0.183 * min(3, source_count)
    completeness_factor = 0.7 + 0.3 * completeness
    margin_factor = 0.75 + 0.25 * min(1.0, max(0.0, margin))
    value = score * source_factor * completeness_factor * margin_factor
    if source_count == 1:
        value = min(value, 0.59)
    return round(max(0.0, min(1.0, value)), 3)


def confidence_level(value: float) -> str:
    if value >= 0.8:
        return "high"
    if value >= 0.5:
        return "medium"
    return "low"
