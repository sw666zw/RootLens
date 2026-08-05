import type { SourceStatus, TelemetryCoverageValue } from "../../api/types";
import { StatusBadge } from "./status-badge";

function tone(status: SourceStatus): "success" | "warning" | "danger" {
  if (status === "available") return "success";
  if (status === "partial") return "warning";
  return "danger";
}

export function TelemetryCoverage({
  coverage,
}: {
  coverage: TelemetryCoverageValue;
}) {
  return (
    <div className="coverage-list" aria-label="Telemetry coverage">
      {Object.entries(coverage).map(([source, status]) => (
        <div key={source}>
          <span className="coverage-source">{source}</span>
          <StatusBadge tone={tone(status)}>{status}</StatusBadge>
        </div>
      ))}
    </div>
  );
}
