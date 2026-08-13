import { FormEvent, useCallback, useState } from "react";
import { useLocation, useParams } from "react-router-dom";
import { api } from "../api/client";
import { safeErrorMessage } from "../api/errors";
import type {
  EvidenceSeverity,
  ValidationResponse,
  ValidationSummary,
} from "../api/types";
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

const evidencePriority: Record<EvidenceSeverity, number> = {
  supporting: 0,
  contradicting: 1,
  informational: 2,
};

function orderEvidenceBySeverity<T extends { severity: EvidenceSeverity }>(
  items: readonly T[],
): T[] {
  return [...items].sort(
    (left, right) =>
      evidencePriority[left.severity] - evidencePriority[right.severity],
  );
}

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
        description="Evidence-grounded narrative constrained by the authoritative deterministic diagnosis."
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
          <article className="panel explanation-hero analysis-memo">
            <div className="report-introduction">
              <p className="eyebrow">Incident analysis report</p>
              <h2>{state.data.headline}</h2>
              <div className="executive-summary">
                <span>Executive summary</span>
                <p>{state.data.executive_summary}</p>
              </div>
            </div>
            <aside className="report-metadata" aria-label="Report metadata">
              <dl>
                <div>
                  <dt>Provider</dt>
                  <dd>
                    {state.data.provider}
                    {state.data.model ? ` · ${state.data.model}` : ""}
                  </dd>
                </div>
                <div>
                  <dt>Provider status</dt>
                  <dd>
                    <StatusBadge
                      tone={
                        state.data.provider_status === "completed"
                          ? "success"
                          : "warning"
                      }
                    >
                      {state.data.provider_status}
                    </StatusBadge>
                  </dd>
                </div>
                <div>
                  <dt>Generated</dt>
                  <dd>
                    <LocalDate value={state.data.generated_at} />
                  </dd>
                </div>
                <div>
                  <dt>Report ID</dt>
                  <dd>
                    <Identifier
                      value={state.data.explanation_id}
                      label="explanation ID"
                    />
                  </dd>
                </div>
              </dl>
            </aside>
          </article>
          <section className="panel diagnostic-basis">
            <div className="section-heading">
              <div>
                <p className="eyebrow">Authoritative findings</p>
                <h2>Deterministic basis</h2>
              </div>
              <Identifier
                value={state.data.diagnosis_id}
                label="diagnosis ID"
              />
            </div>
            <div className="basis-grid">
              <div className="basis-fact">
                <span>Root cause</span>
                <RootCauseBadge cause={state.data.suspected_root_cause} />
              </div>
              <div className="basis-fact">
                <span>Affected service</span>
                <strong>
                  {state.data.affected_service ?? "Not identified"}
                </strong>
              </div>
              <ConfidenceMeter
                value={state.data.confidence}
                level={state.data.confidence_level}
              />
            </div>
            <TelemetryCoverage coverage={state.data.telemetry_coverage} />
          </section>
          <div className="two-column report-narrative">
            <section className="panel report-section">
              <p className="eyebrow">Observed consequence</p>
              <h2>Impact</h2>
              <p>{state.data.impact}</p>
            </section>
            <section className="panel report-section">
              <p className="eyebrow">Limits of analysis</p>
              <h2>Uncertainties</h2>
              <TextList
                items={state.data.uncertainties}
                empty="No uncertainties were recorded."
              />
            </section>
          </div>
          <section className="panel causal-report">
            <p className="eyebrow">Cause to effect</p>
            <h2>Causal chain</h2>
            <ol className="causal-chain">
              {state.data.causal_chain.map((step) => (
                <li key={step}>{step}</li>
              ))}
            </ol>
          </section>
          <section className="panel claims-report">
            <p className="eyebrow">Traceable assertions</p>
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
          <section className="panel evidence-report">
            <p className="eyebrow">Source register</p>
            <h2>Evidence index</h2>
            <div className="evidence-grid">
              {orderEvidenceBySeverity(state.data.evidence_index).map(
                (item) => (
                  <EvidenceCard key={item.evidence_id} evidence={item} />
                ),
              )}
            </div>
          </section>
          <div className="two-column">
            <section className="panel action-report">
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
            <section className="panel operator-report">
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
          <section className="panel validation-report">
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
