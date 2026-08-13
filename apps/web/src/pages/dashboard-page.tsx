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
  kind = "metric",
  tone = "navy",
}: {
  label: string;
  value: string | number;
  detail: string;
  kind?: "status" | "metric";
  tone?: "navy" | "brass" | "forest" | "burgundy";
}) {
  return (
    <article className={`metric-card metric-${tone} ${kind}-card`}>
      <div>
        <div className="metric-heading">
          {kind === "status" && (
            <span className="service-status-dot" aria-hidden="true" />
          )}
          <p>{label}</p>
        </div>
        <strong>{value}</strong>
        <small>{detail}</small>
      </div>
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
          <div className="activity-aside">
            <StatusBadge tone={item.failed_requests ? "danger" : "success"}>
              {item.failed_requests
                ? `${item.failed_requests} failed`
                : `${item.successful_requests} succeeded`}
            </StatusBadge>
            <LocalDate value={item.started_at} />
          </div>
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
          <div className="activity-aside">
            <span className="inline-meta">
              {item.affected_service ?? "No affected service"} ·{" "}
              {Math.round(item.confidence * 100)}%
            </span>
            <LocalDate value={item.generated_at} />
          </div>
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
            <span className="inline-meta">
              {item.provider} · {item.provider_status}
            </span>
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
      <div className="section-heading">
        <h2>{title}</h2>
      </div>
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
        eyebrow="RootLens observatory"
        title="Incident Intelligence"
        description="Trace an operational event from observed behavior to deterministic root cause and an evidence-grounded operator report."
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
              : health.data?.status === "ok"
                ? "Service operational"
                : health.data
                  ? "Service unavailable"
                  : "Checking service"
          }
          kind="status"
          tone={health.data?.status === "ok" ? "forest" : "burgundy"}
        />
        <MetricCard
          label="Visible incidents"
          value={incidents.data?.length ?? "…"}
          detail="Ground-truth-safe reports"
          tone="burgundy"
        />
        <MetricCard
          label="Diagnoses"
          value={diagnoses.data?.length ?? "…"}
          detail="Deterministic reports"
          tone="brass"
        />
        <MetricCard
          label="Explanations"
          value={explanations.data?.length ?? "…"}
          detail="Generated narratives"
          tone="navy"
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
              <strong>
                <span>{coverageAvailable}</span> / {coverage.length}
              </strong>
              <div>
                <p>Source observations available</p>
                <small>Across all visible deterministic diagnoses</small>
              </div>
            </div>
          )}
        </SectionState>
        <section className="panel dashboard-panel service-health-widget">
          <div className="section-heading">
            <h2>Service health</h2>
          </div>
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
            <div className="service-health-reading">
              <span aria-hidden="true" />
              <div>
                <strong>{health.data.service}</strong>
                <small>
                  Service status · {health.data.status.toUpperCase()}
                </small>
              </div>
            </div>
          ) : null}
        </section>
      </div>
    </div>
  );
}
