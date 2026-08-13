import type { TelemetryCoverageValue } from "../../api/types";

export function TelemetryCoverage({
  coverage,
}: {
  coverage: TelemetryCoverageValue;
}) {
  return (
    <div className="coverage-list" aria-label="Telemetry coverage">
      {Object.entries(coverage).map(([source, status]) => (
        <div className="coverage-item" data-status={status} key={source}>
          <span className="coverage-source">{source}</span>
          <span className="coverage-state">
            <span className="coverage-dot" aria-hidden="true" />
            {status}
          </span>
        </div>
      ))}
    </div>
  );
}
