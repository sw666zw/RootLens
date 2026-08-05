import { useCallback, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { Identifier, LocalDate } from "../components/identifiers";
import { PageHeader } from "../components/layout/page-header";
import {
  EmptyState,
  ErrorState,
  LoadingState,
} from "../components/status/states";
import { StatusBadge } from "../components/status/status-badge";
import { useApi } from "../hooks/use-api";

export function ExplanationsPage() {
  const [provider, setProvider] = useState("");
  const [providerStatus, setProviderStatus] = useState("");
  const state = useApi(
    useCallback((signal) => api.explanations({ limit: 200, signal }), []),
  );
  const filtered = useMemo(
    () =>
      (state.data ?? []).filter(
        (item) =>
          (!provider || item.provider === provider) &&
          (!providerStatus || item.provider_status === providerStatus),
      ),
    [provider, providerStatus, state.data],
  );

  return (
    <div className="page">
      <PageHeader
        eyebrow="Evidence-grounded narratives"
        title="Explanations"
        description="Operator-facing prose built above, and constrained by, deterministic diagnoses."
        actions={
          <button className="secondary-button" onClick={state.refresh}>
            Refresh
          </button>
        }
      />
      <section className="panel filter-bar" aria-label="Explanation filters">
        <label>
          Provider
          <select
            value={provider}
            onChange={(event) => setProvider(event.target.value)}
          >
            <option value="">All providers</option>
            <option value="template">Template</option>
            <option value="openai">OpenAI</option>
          </select>
        </label>
        <label>
          Provider status
          <select
            value={providerStatus}
            onChange={(event) => setProviderStatus(event.target.value)}
          >
            <option value="">All statuses</option>
            <option value="completed">Completed</option>
            <option value="fallback">Fallback</option>
          </select>
        </label>
      </section>
      {state.loading && !state.data ? (
        <LoadingState label="Loading explanations" />
      ) : null}
      {state.error ? (
        <ErrorState error={state.error} onRetry={state.refresh} />
      ) : null}
      {state.data && filtered.length === 0 ? (
        <EmptyState
          title="No explanations found"
          message="Generate an explanation or adjust the current filters."
        />
      ) : null}
      {filtered.length ? (
        <div className="card-list">
          {filtered.map((explanation) => (
            <article
              className="panel report-card"
              key={explanation.explanation_id}
            >
              <header>
                <div>
                  <StatusBadge
                    tone={
                      explanation.provider_status === "completed"
                        ? "success"
                        : "warning"
                    }
                  >
                    {explanation.provider} · {explanation.provider_status}
                  </StatusBadge>
                  {explanation.model && (
                    <span className="inline-meta">{explanation.model}</span>
                  )}
                </div>
                <LocalDate value={explanation.generated_at} />
              </header>
              <h2>{explanation.headline}</h2>
              <Identifier
                value={explanation.explanation_id}
                label="explanation ID"
              />
              <p className="muted">
                Diagnosis{" "}
                <Identifier
                  value={explanation.diagnosis_id}
                  label="diagnosis ID"
                />
              </p>
              <footer>
                <Link
                  className="text-link"
                  to={`/explanations/${encodeURIComponent(explanation.explanation_id)}`}
                >
                  Review explanation →
                </Link>
              </footer>
            </article>
          ))}
        </div>
      ) : null}
    </div>
  );
}
