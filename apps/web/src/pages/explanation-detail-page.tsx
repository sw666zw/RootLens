import { FormEvent, useCallback, useState } from "react";
import { useLocation, useParams } from "react-router-dom";
import { api } from "../api/client";
import { safeErrorMessage } from "../api/errors";
import type { ValidationResponse, ValidationSummary } from "../api/types";
import { ConfirmedActionButton } from "../components/confirmed-action-button";
import { EvidenceCard } from "../components/evidence/evidence-card";
import { Identifier, LocalDate } from "../components/identifiers";
import { PageHeader } from "../components/layout/page-header";
import { ConfidenceMeter } from "../components/status/confidence-meter";
import { RootCauseBadge } from "../components/status/root-cause-badge";
import {
  ErrorState,
  LoadingState,
  Notification,
} from "../components/status/states";
import { StatusBadge } from "../components/status/status-badge";
import { TelemetryCoverage } from "../components/status/telemetry-coverage";
import { useApi } from "../hooks/use-api";

const checks: Array<[keyof ValidationSummary, string]> = [
  ["protected_fields_match", "Protected deterministic fields match"],
  ["evidence_references_valid", "Evidence references are valid"],
  ["required_fields_present", "Required narrative fields are present"],
  ["no_ground_truth_fields", "No ground-truth fields are present"],
];

function ValidationResults({
  result,
  title,
}: {
  result: ValidationSummary;
  title: string;
}) {
  return (
    <div className="validation-results">
      <div className="validation-heading">
        <h3>{title}</h3>
        <StatusBadge tone={result.overall_valid ? "success" : "danger"}>
          {result.overall_valid ? "PASS" : "FAIL"}
        </StatusBadge>
      </div>
      <ul>
        {checks.map(([field, label]) => (
          <li key={field}>
            <span aria-hidden="true">{result[field] ? "✓" : "×"}</span>
            <span>{label}</span>
            <strong>{result[field] ? "Pass" : "Fail"}</strong>
          </li>
        ))}
      </ul>
    </div>
  );
}

function TextList({ items, empty }: { items: string[]; empty: string }) {
  return items.length ? (
    <ul>
      {items.map((item) => (
        <li key={item}>{item}</li>
      ))}
    </ul>
  ) : (
    <p className="muted">{empty}</p>
  );
}

export function ExplanationDetailPage() {
  const { explanationId = "" } = useParams();
  const location = useLocation();
  const state = useApi(
    useCallback(
      (signal) => api.explanation(explanationId, signal),
      [explanationId],
    ),
  );
  const [submitting, setSubmitting] = useState(false);
  const [validationResult, setValidationResult] =
    useState<ValidationResponse | null>(null);
  const [validationError, setValidationError] = useState<string | null>(null);

  async function validate(event: FormEvent) {
    event.preventDefault();
    if (submitting || !state.data) return;
    setSubmitting(true);
    setValidationError(null);
    try {
      setValidationResult(
        await api.validateExplanation(explanationId, state.data.diagnosis_id),
      );
    } catch (error) {
      setValidationError(safeErrorMessage(error));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="page">
      <PageHeader
        eyebrow="Operator narrative"
        title="Explanation detail"
        description="Untrusted narrative text is displayed as plain text and remains subordinate to the deterministic diagnosis."
      />
      {(location.state as { notice?: string } | null)?.notice && (
        <Notification tone="success">
          {(location.state as { notice: string }).notice}
        </Notification>
      )}
      {state.loading && !state.data ? (
        <LoadingState label="Loading explanation" />
      ) : null}
      {state.error ? (
        <ErrorState error={state.error} onRetry={state.refresh} />
      ) : null}
      {state.data ? (
        <>
          <section className="panel explanation-hero">
            <div>
              <div className="badge-row">
                <StatusBadge
                  tone={
                    state.data.provider_status === "completed"
                      ? "success"
                      : "warning"
                  }
                >
                  {state.data.provider} · {state.data.provider_status}
                </StatusBadge>
                {state.data.model && (
                  <StatusBadge>{state.data.model}</StatusBadge>
                )}
              </div>
              <h2>{state.data.headline}</h2>
              <p>{state.data.executive_summary}</p>
            </div>
            <div>
              <Identifier
                value={state.data.explanation_id}
                label="explanation ID"
              />
              <LocalDate value={state.data.generated_at} />
            </div>
          </section>
          <div className="two-column">
            <section className="panel">
              <h2>Deterministic basis</h2>
              <dl className="detail-list">
                <div>
                  <dt>Root cause</dt>
                  <dd>
                    <RootCauseBadge cause={state.data.suspected_root_cause} />
                  </dd>
                </div>
                <div>
                  <dt>Affected service</dt>
                  <dd>{state.data.affected_service ?? "Not identified"}</dd>
                </div>
                <div>
                  <dt>Diagnosis ID</dt>
                  <dd>
                    <Identifier
                      value={state.data.diagnosis_id}
                      label="diagnosis ID"
                    />
                  </dd>
                </div>
              </dl>
              <ConfidenceMeter
                value={state.data.confidence}
                level={state.data.confidence_level}
              />
              <TelemetryCoverage coverage={state.data.telemetry_coverage} />
            </section>
            <section className="panel">
              <h2>Impact</h2>
              <p>{state.data.impact}</p>
              <h3>Uncertainties</h3>
              <TextList
                items={state.data.uncertainties}
                empty="No uncertainties were recorded."
              />
            </section>
          </div>
          <section className="panel">
            <h2>Causal chain</h2>
            <ol className="causal-chain">
              {state.data.causal_chain.map((step) => (
                <li key={step}>{step}</li>
              ))}
            </ol>
          </section>
          <section className="panel">
            <h2>Evidence-based claims</h2>
            <div className="claim-list">
              {state.data.evidence_based_claims.length ? (
                state.data.evidence_based_claims.map((claim, index) => (
                  <article key={`${claim.claim}-${index}`}>
                    <p>{claim.claim}</p>
                    <div className="evidence-refs">
                      <span>Evidence:</span>
                      {claim.evidence_refs.map((reference) => (
                        <a key={reference} href={`#${reference}`}>
                          {reference}
                        </a>
                      ))}
                    </div>
                  </article>
                ))
              ) : (
                <p className="muted">No evidence-based claims were supplied.</p>
              )}
            </div>
          </section>
          <section className="panel">
            <h2>Evidence index</h2>
            <div className="evidence-grid">
              {state.data.evidence_index.map((item) => (
                <EvidenceCard key={item.evidence_id} evidence={item} />
              ))}
            </div>
          </section>
          <div className="two-column">
            <section className="panel">
              <h2>Immediate actions</h2>
              <TextList
                items={state.data.immediate_actions}
                empty="No immediate actions."
              />
              <h3>Follow-up actions</h3>
              <TextList
                items={state.data.follow_up_actions}
                empty="No follow-up actions."
              />
            </section>
            <section className="panel">
              <h2>Operator notes</h2>
              <p>
                {state.data.operator_notes ??
                  "No operator notes were supplied."}
              </p>
              <h3>Preserved warnings</h3>
              <TextList
                items={state.data.warnings}
                empty="No explanation warnings."
              />
            </section>
          </div>
          <section className="panel">
            <h2>Existing validation state</h2>
            <ValidationResults
              result={state.data.validation}
              title="Generation-time checks"
            />
          </section>
          <section className="panel action-panel">
            <div>
              <p className="eyebrow">Offline deterministic checks</p>
              <h2>Validate explanation</h2>
              <p>
                Validation compares this explanation with diagnosis{" "}
                <Identifier
                  value={state.data.diagnosis_id}
                  label="diagnosis ID"
                />
                . It does not modify the explanation or call OpenAI.
              </p>
            </div>
            <form onSubmit={validate} className="action-form">
              <label>
                Diagnosis ID
                <input
                  value={state.data.diagnosis_id}
                  readOnly
                  aria-readonly="true"
                />
              </label>
              {validationError && (
                <Notification tone="error">{validationError}</Notification>
              )}
              <ConfirmedActionButton
                busy={submitting}
                idleLabel="Validate explanation"
                busyLabel="Validating…"
              />
              <div aria-live="polite">
                {validationResult && (
                  <ValidationResults
                    result={validationResult}
                    title="Latest validation"
                  />
                )}
              </div>
            </form>
          </section>
        </>
      ) : null}
    </div>
  );
}
