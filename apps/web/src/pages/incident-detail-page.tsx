import { FormEvent, useCallback, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import { safeErrorMessage } from "../api/errors";
import { ConfirmedActionButton } from "../components/confirmed-action-button";
import { Identifier, LocalDate } from "../components/identifiers";
import { PageHeader } from "../components/layout/page-header";
import {
  ErrorState,
  LoadingState,
  Notification,
} from "../components/status/states";
import { StatusBadge } from "../components/status/status-badge";
import { useApi } from "../hooks/use-api";

export function IncidentDetailPage() {
  const { scenarioId = "" } = useParams();
  const navigate = useNavigate();
  const state = useApi(
    useCallback((signal) => api.incident(scenarioId, signal), [scenarioId]),
  );
  const [requireAll, setRequireAll] = useState(false);
  const [padding, setPadding] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (submitting) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      const report = await api.diagnose(scenarioId, {
        require_all_sources: requireAll,
        window_padding_seconds: padding === "" ? null : Number(padding),
      });
      navigate(`/diagnoses/${encodeURIComponent(report.diagnosis_id)}`, {
        state: { notice: "Diagnosis completed successfully." },
      });
    } catch (error) {
      setSubmitError(safeErrorMessage(error));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="page">
      <PageHeader
        eyebrow="Incident detail"
        title="Incident investigation"
        description="A ground-truth-safe projection supplied by the Diagnosis Service."
      />
      {state.loading && !state.data ? (
        <LoadingState label="Loading incident" />
      ) : null}
      {state.error ? (
        <ErrorState error={state.error} onRetry={state.refresh} />
      ) : null}
      {state.data ? (
        <>
          <section className="panel hero-panel">
            <div>
              <p className="eyebrow">Scenario ID</p>
              <Identifier value={state.data.scenario_id} label="scenario ID" />
            </div>
            <StatusBadge
              tone={state.data.failed_requests ? "warning" : "success"}
            >
              {state.data.failed_requests
                ? "Failures observed"
                : "Completed successfully"}
            </StatusBadge>
          </section>
          <section className="detail-grid panel">
            <dl className="detail-list">
              <div>
                <dt>Started</dt>
                <dd>
                  <LocalDate value={state.data.started_at} />
                </dd>
              </div>
              <div>
                <dt>Ended</dt>
                <dd>
                  <LocalDate value={state.data.ended_at} />
                </dd>
              </div>
              <div>
                <dt>Total requests</dt>
                <dd>{state.data.total_requests}</dd>
              </div>
              <div>
                <dt>Concurrency</dt>
                <dd>{state.data.concurrency}</dd>
              </div>
              <div>
                <dt>Successful</dt>
                <dd>{state.data.successful_requests}</dd>
              </div>
              <div>
                <dt>Failed</dt>
                <dd>{state.data.failed_requests}</dd>
              </div>
              <div>
                <dt>Request IDs captured</dt>
                <dd>{state.data.request_id_count}</dd>
              </div>
              <div>
                <dt>Trace IDs captured</dt>
                <dd>{state.data.trace_id_count}</dd>
              </div>
              <div>
                <dt>Inventory SKU</dt>
                <dd>{state.data.inventory_sku ?? "Not supplied"}</dd>
              </div>
            </dl>
            <div>
              <h2>HTTP status summary</h2>
              <ul className="status-counts">
                {Object.entries(state.data.response_status_counts).map(
                  ([status, count]) => (
                    <li key={status}>
                      <code>{status}</code>
                      <strong>{count}</strong>
                    </li>
                  ),
                )}
              </ul>
            </div>
          </section>
          <section className="panel action-panel">
            <div>
              <p className="eyebrow">Deterministic analysis</p>
              <h2>Run diagnosis</h2>
              <p>
                RootLens queries the backend telemetry sources for this incident
                window. Partial telemetry can still produce a lower-confidence
                report unless every source is required.
              </p>
            </div>
            <form onSubmit={submit} className="action-form">
              <label className="checkbox-label">
                <input
                  type="checkbox"
                  checked={requireAll}
                  onChange={(event) => setRequireAll(event.target.checked)}
                />
                Require all telemetry sources
              </label>
              <label>
                Window padding (seconds, optional)
                <input
                  type="number"
                  min="0"
                  step="1"
                  value={padding}
                  onChange={(event) => setPadding(event.target.value)}
                />
              </label>
              {submitError && (
                <Notification tone="error">{submitError}</Notification>
              )}
              <ConfirmedActionButton
                busy={submitting}
                idleLabel="Run diagnosis"
                busyLabel="Running diagnosis…"
              />
            </form>
          </section>
        </>
      ) : null}
    </div>
  );
}
