import { FormEvent, useCallback, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import { safeErrorMessage } from "../api/errors";
import type { EvidenceSource } from "../api/types";
import { ConfirmedActionButton } from "../components/confirmed-action-button";
import { EvidenceCard } from "../components/evidence/evidence-card";
import { Identifier, LocalDate } from "../components/identifiers";
import { PageHeader } from "../components/layout/page-header";
import { ConfidenceMeter } from "../components/status/confidence-meter";
import { RootCauseBadge } from "../components/status/root-cause-badge";
import { formatRootCause } from "../components/status/root-cause-format";
import {
  ErrorState,
  LoadingState,
  Notification,
} from "../components/status/states";
import { TelemetryCoverage } from "../components/status/telemetry-coverage";
import { useApi } from "../hooks/use-api";

export function DiagnosisDetailPage() {
  const { diagnosisId = "" } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const state = useApi(
    useCallback((signal) => api.diagnosis(diagnosisId, signal), [diagnosisId]),
  );
  const [provider, setProvider] = useState<"template" | "openai">("template");
  const [allowFallback, setAllowFallback] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (submitting) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      const explanation = await api.explain(diagnosisId, {
        provider,
        allow_template_fallback: allowFallback,
      });
      navigate(
        `/explanations/${encodeURIComponent(explanation.explanation_id)}`,
        {
          state: { notice: "Explanation generated successfully." },
        },
      );
    } catch (error) {
      setSubmitError(safeErrorMessage(error));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="page">
      <PageHeader
        eyebrow="Deterministic report"
        title="Diagnosis detail"
        description="The diagnosis is authoritative; explanations cannot change these results."
      />
      {(location.state as { notice?: string } | null)?.notice && (
        <Notification tone="success">
          {(location.state as { notice: string }).notice}
        </Notification>
      )}
      {state.loading && !state.data ? (
        <LoadingState label="Loading diagnosis" />
      ) : null}
      {state.error ? (
        <ErrorState error={state.error} onRetry={state.refresh} />
      ) : null}
      {state.data ? (
        <>
          <section className="panel diagnosis-hero">
            <div>
              <p className="eyebrow">Suspected root cause</p>
              <h2>
                <RootCauseBadge cause={state.data.suspected_root_cause} />
              </h2>
              <p>{state.data.summary}</p>
            </div>
            <div>
              <Identifier
                value={state.data.diagnosis_id}
                label="diagnosis ID"
              />
              <LocalDate value={state.data.generated_at} />
              <ConfidenceMeter
                value={state.data.confidence}
                level={state.data.confidence_level}
              />
            </div>
          </section>
          <div className="two-column">
            <section className="panel">
              <h2>Analysis context</h2>
              <dl className="detail-list">
                <div>
                  <dt>Affected service</dt>
                  <dd>{state.data.affected_service ?? "Not identified"}</dd>
                </div>
                <div>
                  <dt>Window start</dt>
                  <dd>
                    <LocalDate value={state.data.analyzed_window.start} />
                  </dd>
                </div>
                <div>
                  <dt>Window end</dt>
                  <dd>
                    <LocalDate value={state.data.analyzed_window.end} />
                  </dd>
                </div>
                <div>
                  <dt>Requests analyzed</dt>
                  <dd>{state.data.input_context.total_requests}</dd>
                </div>
                <div>
                  <dt>Request IDs</dt>
                  <dd>{state.data.input_context.request_id_count}</dd>
                </div>
                <div>
                  <dt>Trace IDs</dt>
                  <dd>{state.data.input_context.trace_id_count}</dd>
                </div>
              </dl>
            </section>
            <section className="panel">
              <h2>Telemetry coverage</h2>
              <TelemetryCoverage coverage={state.data.telemetry_coverage} />
              {state.data.warnings.length ? (
                <>
                  <h3>Warnings</h3>
                  <ul className="warning-list">
                    {state.data.warnings.map((warning) => (
                      <li key={warning}>{warning}</li>
                    ))}
                  </ul>
                </>
              ) : (
                <p className="muted">No diagnosis warnings.</p>
              )}
            </section>
          </div>
          <section className="panel">
            <h2>Candidate scores</h2>
            <div className="candidate-grid">
              {Object.entries(state.data.candidate_scores).map(
                ([cause, candidate]) => (
                  <article key={cause}>
                    <header>
                      <strong>{formatRootCause(cause)}</strong>
                      <span>{Math.round(candidate.score * 100)}%</span>
                    </header>
                    <div
                      className="score-track"
                      aria-label={`${formatRootCause(cause)} score ${Math.round(candidate.score * 100)} percent`}
                    >
                      <span style={{ width: `${candidate.score * 100}%` }} />
                    </div>
                    <small>
                      {candidate.supporting_evidence.length} supporting ·{" "}
                      {candidate.contradicting_evidence.length} contradicting
                    </small>
                  </article>
                ),
              )}
            </div>
          </section>
          <section className="panel">
            <h2>Normalized evidence</h2>
            {(["metrics", "logs", "traces"] as EvidenceSource[]).map(
              (source) => {
                const items = state.data!.evidence.filter(
                  (item) => item.source === source,
                );
                return (
                  <section className="evidence-group" key={source}>
                    <h3>{source}</h3>
                    {items.length ? (
                      <div className="evidence-grid">
                        {items.map((item, index) => (
                          <EvidenceCard
                            key={`${item.reference}-${index}`}
                            evidence={item}
                          />
                        ))}
                      </div>
                    ) : (
                      <p className="muted">No normalized {source} evidence.</p>
                    )}
                  </section>
                );
              },
            )}
          </section>
          <div className="two-column">
            <section className="panel">
              <h2>Alternative causes</h2>
              {state.data.alternative_causes.length ? (
                <ul className="clean-list">
                  {state.data.alternative_causes.map((cause) => (
                    <li key={cause}>
                      <RootCauseBadge cause={cause} />
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="muted">
                  No alternative cause passed the reporting threshold.
                </p>
              )}
            </section>
            <section className="panel">
              <h2>Recommended checks</h2>
              <ol>
                {state.data.recommended_checks.map((check) => (
                  <li key={check}>{check}</li>
                ))}
              </ol>
            </section>
          </div>
          <section className="panel action-panel">
            <div>
              <p className="eyebrow">Operator narrative</p>
              <h2>Generate explanation</h2>
              <p>
                Template mode is offline and deterministic. OpenAI must be
                explicitly enabled by the backend; this browser never receives
                or requests an API key.
              </p>
            </div>
            <form onSubmit={submit} className="action-form">
              <label>
                Provider
                <select
                  value={provider}
                  onChange={(event) =>
                    setProvider(event.target.value as "template" | "openai")
                  }
                >
                  <option value="template">Template</option>
                  <option value="openai">OpenAI</option>
                </select>
              </label>
              <label className="checkbox-label">
                <input
                  type="checkbox"
                  checked={allowFallback}
                  onChange={(event) => setAllowFallback(event.target.checked)}
                />
                Allow template fallback
              </label>
              {submitError && (
                <Notification tone="error">{submitError}</Notification>
              )}
              <ConfirmedActionButton
                busy={submitting}
                idleLabel="Generate explanation"
                busyLabel="Generating explanation…"
              />
            </form>
          </section>
        </>
      ) : null}
    </div>
  );
}
