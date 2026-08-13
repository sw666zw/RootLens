import { useCallback, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { Identifier, LocalDate } from "../components/identifiers";
import { PageHeader } from "../components/layout/page-header";
import { ConfidenceMeter } from "../components/status/confidence-meter";
import {
  EmptyState,
  ErrorState,
  LoadingState,
} from "../components/status/states";
import { RootCauseBadge } from "../components/status/root-cause-badge";
import { TelemetryCoverage } from "../components/status/telemetry-coverage";
import { useApi } from "../hooks/use-api";

export function DiagnosesPage() {
  const [rootCause, setRootCause] = useState("");
  const [confidenceLevel, setConfidenceLevel] = useState("");
  const state = useApi(
    useCallback((signal) => api.diagnoses({ limit: 200, signal }), []),
  );
  const filtered = useMemo(
    () =>
      (state.data ?? []).filter(
        (item) =>
          (!rootCause || item.suspected_root_cause === rootCause) &&
          (!confidenceLevel || item.confidence_level === confidenceLevel),
      ),
    [confidenceLevel, rootCause, state.data],
  );
  const rootCauses = [
    ...new Set((state.data ?? []).map((item) => item.suspected_root_cause)),
  ];
  const levels = [
    ...new Set((state.data ?? []).map((item) => item.confidence_level)),
  ];

  return (
    <div className="page">
      <PageHeader
        eyebrow="Deterministic analysis"
        title="Diagnoses"
        description="Reproducible hypotheses grounded in normalized metrics, logs, and traces."
        actions={
          <button className="secondary-button" onClick={state.refresh}>
            Refresh
          </button>
        }
      />
      <section className="panel filter-bar" aria-label="Diagnosis filters">
        <label>
          Root cause
          <select
            value={rootCause}
            onChange={(event) => setRootCause(event.target.value)}
          >
            <option value="">All root causes</option>
            {rootCauses.map((cause) => (
              <option key={cause} value={cause}>
                {cause.replaceAll("_", " ")}
              </option>
            ))}
          </select>
        </label>
        <label>
          Confidence level
          <select
            value={confidenceLevel}
            onChange={(event) => setConfidenceLevel(event.target.value)}
          >
            <option value="">All levels</option>
            {levels.map((level) => (
              <option key={level}>{level}</option>
            ))}
          </select>
        </label>
      </section>
      {state.loading && !state.data ? (
        <LoadingState label="Loading diagnoses" />
      ) : null}
      {state.error ? (
        <ErrorState error={state.error} onRetry={state.refresh} />
      ) : null}
      {state.data && filtered.length === 0 ? (
        <EmptyState
          title="No diagnoses found"
          message="Run a diagnosis or adjust the current filters."
        />
      ) : null}
      {filtered.length ? (
        <div className="card-list">
          {filtered.map((diagnosis) => (
            <article className="panel report-card" key={diagnosis.diagnosis_id}>
              <header>
                <div className="report-title diagnosis-conclusion">
                  <span className="report-label">Suspected root cause</span>
                  <RootCauseBadge cause={diagnosis.suspected_root_cause} />
                </div>
                <LocalDate value={diagnosis.generated_at} />
              </header>
              <Identifier value={diagnosis.diagnosis_id} label="diagnosis ID" />
              <div className="report-grid diagnosis-report-grid">
                <div className="affected-service-fact">
                  <span>Affected service</span>
                  <strong>
                    {diagnosis.affected_service ?? "Not identified"}
                  </strong>
                </div>
                <ConfidenceMeter
                  value={diagnosis.confidence}
                  level={diagnosis.confidence_level}
                />
                <TelemetryCoverage coverage={diagnosis.telemetry_coverage} />
              </div>
              <footer>
                <Link
                  className="text-link"
                  to={`/diagnoses/${encodeURIComponent(diagnosis.diagnosis_id)}`}
                >
                  Review diagnosis →
                </Link>
              </footer>
            </article>
          ))}
        </div>
      ) : null}
    </div>
  );
}
