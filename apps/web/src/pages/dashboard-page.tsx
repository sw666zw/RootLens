import { useCallback } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type {
  DiagnosisSummary,
  ExplanationSummary,
  IncidentSummary,
} from "../api/types";
import { Identifier, LocalDate } from "../components/identifiers";
import { PageHeader } from "../components/layout/page-header";
import { ErrorState, LoadingState } from "../components/status/states";
import { RootCauseBadge } from "../components/status/root-cause-badge";
import { formatRootCause } from "../components/status/root-cause-format";
import { StatusBadge } from "../components/status/status-badge";
import { useApi, type ApiState } from "../hooks/use-api";

function MetricCard({
  label,
  value,
  detail,
}: {
  label: string;
  value: string | number;
  detail: string;
}) {
  return (
    <article className="metric-card">
      <p>{label}</p>
      <strong>{value}</strong>
      <small>{detail}</small>
    </article>
  );
}

function RecentIncidents({ items }: { items: IncidentSummary[] }) {
  return (
    <ul className="activity-list">
      {items.slice(0, 4).map((item) => (
        <li key={item.scenario_id}>
          <div>
            <Link to={`/incidents/${encodeURIComponent(item.scenario_id)}`}>
              {item.scenario_name}
            </Link>
            <Identifier value={item.scenario_id} label="scenario ID" />
          </div>
          <LocalDate value={item.started_at} />
        </li>
      ))}
    </ul>
  );
}

function RecentDiagnoses({ items }: { items: DiagnosisSummary[] }) {
  return (
    <ul className="activity-list">
      {items.slice(0, 4).map((item) => (
        <li key={item.diagnosis_id}>
          <div>
            <Link to={`/diagnoses/${encodeURIComponent(item.diagnosis_id)}`}>
              <RootCauseBadge cause={item.suspected_root_cause} />
            </Link>
            <Identifier value={item.diagnosis_id} label="diagnosis ID" />
          </div>
          <LocalDate value={item.generated_at} />
        </li>
      ))}
    </ul>
  );
}

function RecentExplanations({ items }: { items: ExplanationSummary[] }) {
  return (
    <ul className="activity-list">
      {items.slice(0, 4).map((item) => (
        <li key={item.explanation_id}>
          <div>
            <Link
              to={`/explanations/${encodeURIComponent(item.explanation_id)}`}
            >
              {item.headline}
            </Link>
            <span className="inline-meta">{item.provider}</span>
          </div>
          <LocalDate value={item.generated_at} />
        </li>
      ))}
    </ul>
  );
}

function SectionState<T>({
  title,
  state,
  children,
}: {
  title: string;
  state: ApiState<T>;
  children: (data: T) => React.ReactNode;
}) {
  return (
    <section className="panel dashboard-panel">
      <h2>{title}</h2>
      {state.loading && !state.data ? (
        <LoadingState label={`Loading ${title.toLowerCase()}`} />
      ) : null}
      {state.error ? (
        <ErrorState error={state.error} onRetry={state.refresh} />
      ) : null}
      {state.data ? children(state.data) : null}
    </section>
  );
}

export function DashboardPage() {
  const health = useApi(useCallback((signal) => api.health(signal), []));
  const incidents = useApi(
    useCallback((signal) => api.incidents({ limit: 50, signal }), []),
  );
  const diagnoses = useApi(
    useCallback((signal) => api.diagnoses({ limit: 50, signal }), []),
  );
  const explanations = useApi(
    useCallback((signal) => api.explanations({ limit: 50, signal }), []),
  );

  const causeCounts = (diagnoses.data ?? []).reduce<Record<string, number>>(
    (counts, item) => {
      counts[item.suspected_root_cause] =
        (counts[item.suspected_root_cause] ?? 0) + 1;
      return counts;
    },
    {},
  );
  const maxCause = Math.max(1, ...Object.values(causeCounts));
  const coverage = (diagnoses.data ?? []).flatMap((item) =>
    Object.values(item.telemetry_coverage),
  );
  const coverageAvailable = coverage.filter(
    (status) => status === "available",
  ).length;

  return (
    <div className="page">
      <PageHeader
        eyebrow="Local observability"
        title="System overview"
        description="Evidence-backed incidents, deterministic diagnoses, and operator explanations in one safe view."
      />
      <section className="metric-grid" aria-label="System totals">
        <MetricCard
          label="Diagnosis Service"
          value={
            health.loading
              ? "…"
              : health.data?.status === "ok"
                ? "Healthy"
                : "Unavailable"
          }
          detail={
            health.error
              ? "Connection failed"
              : (health.data?.service ?? "Checking service")
          }
        />
        <MetricCard
          label="Visible incidents"
          value={incidents.data?.length ?? "…"}
          detail="Ground-truth-safe reports"
        />
        <MetricCard
          label="Diagnoses"
          value={diagnoses.data?.length ?? "…"}
          detail="Deterministic reports"
        />
        <MetricCard
          label="Explanations"
          value={explanations.data?.length ?? "…"}
          detail="Generated narratives"
        />
      </section>

      <div className="dashboard-grid">
        <SectionState title="Recent incidents" state={incidents}>
          {(items) =>
            items.length ? (
              <RecentIncidents items={items} />
            ) : (
              <p className="muted">No incidents are visible yet.</p>
            )
          }
        </SectionState>
        <SectionState title="Recent diagnoses" state={diagnoses}>
          {(items) =>
            items.length ? (
              <RecentDiagnoses items={items} />
            ) : (
              <p className="muted">No diagnoses have been generated.</p>
            )
          }
        </SectionState>
        <SectionState title="Recent explanations" state={explanations}>
          {(items) =>
            items.length ? (
              <RecentExplanations items={items} />
            ) : (
              <p className="muted">No explanations have been generated.</p>
            )
          }
        </SectionState>
        <SectionState title="Root-cause distribution" state={diagnoses}>
          {() =>
            Object.keys(causeCounts).length ? (
              <div
                className="distribution"
                aria-label="Diagnosis root-cause distribution"
              >
                {Object.entries(causeCounts).map(([cause, count]) => (
                  <div key={cause}>
                    <span>{formatRootCause(cause)}</span>
                    <div className="distribution-bar" aria-hidden="true">
                      <span style={{ width: `${(count / maxCause) * 100}%` }} />
                    </div>
                    <strong>{count}</strong>
                  </div>
                ))}
              </div>
            ) : (
              <p className="muted">
                Distribution appears after the first diagnosis.
              </p>
            )
          }
        </SectionState>
        <SectionState title="Telemetry coverage" state={diagnoses}>
          {() => (
            <div className="coverage-summary">
              <StatusBadge
                tone={
                  coverage.length && coverageAvailable === coverage.length
                    ? "success"
                    : "warning"
                }
              >
                {coverageAvailable} of {coverage.length} source observations
                available
              </StatusBadge>
              <p className="muted">
                Across the currently visible deterministic diagnoses.
              </p>
            </div>
          )}
        </SectionState>
        <section className="panel dashboard-panel">
          <h2>Service health</h2>
          {health.loading && !health.data ? (
            <LoadingState label="Checking Diagnosis Service" />
          ) : null}
          {health.error ? (
            <ErrorState
              error={health.error}
              onRetry={health.refresh}
              title="Diagnosis Service unavailable"
            />
          ) : null}
          {health.data ? (
            <StatusBadge
              tone={health.data.status === "ok" ? "success" : "warning"}
            >
              {health.data.service}: {health.data.status}
            </StatusBadge>
          ) : null}
        </section>
      </div>
    </div>
  );
}
