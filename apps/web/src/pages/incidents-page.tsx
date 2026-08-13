import { useCallback, useState } from "react";
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

function duration(start: string, end: string): string {
  const milliseconds = new Date(end).getTime() - new Date(start).getTime();
  return Number.isFinite(milliseconds)
    ? `${(milliseconds / 1000).toFixed(1)}s`
    : "—";
}

export function IncidentsPage() {
  const [limit, setLimit] = useState(50);
  const [scenarioName, setScenarioName] = useState("");
  const loader = useCallback(
    (signal: AbortSignal) => api.incidents({ limit, scenarioName, signal }),
    [limit, scenarioName],
  );
  const state = useApi(loader);

  return (
    <div className="page">
      <PageHeader
        eyebrow="Safe incident projection"
        title="Incidents"
        description="Scenario traffic summaries from the Diagnosis Service. Evaluation ground truth is never shown."
        actions={
          <button className="secondary-button" onClick={state.refresh}>
            Refresh
          </button>
        }
      />
      <section className="panel filter-bar" aria-label="Incident filters">
        <label>
          Scenario
          <select
            value={scenarioName}
            onChange={(event) => setScenarioName(event.target.value)}
          >
            <option value="">All scenarios</option>
            <option value="baseline">Baseline</option>
            <option value="inventory-latency">Inventory latency</option>
            <option value="inventory-unavailable">Inventory unavailable</option>
          </select>
        </label>
        <label>
          Limit
          <select
            value={limit}
            onChange={(event) => setLimit(Number(event.target.value))}
          >
            {[10, 25, 50, 100, 200].map((value) => (
              <option key={value}>{value}</option>
            ))}
          </select>
        </label>
      </section>
      {state.loading && !state.data ? (
        <LoadingState label="Loading incidents" />
      ) : null}
      {state.error ? (
        <ErrorState error={state.error} onRetry={state.refresh} />
      ) : null}
      {state.data?.length === 0 ? (
        <EmptyState
          title="No incidents found"
          message="Generate a scenario or adjust the current filters."
        />
      ) : null}
      {state.data?.length ? (
        <div className="table-wrap panel">
          <table>
            <caption className="sr-only">Visible incidents</caption>
            <thead>
              <tr>
                <th>Incident</th>
                <th>Started</th>
                <th>Duration</th>
                <th>Requests</th>
                <th>Outcome</th>
                <th>
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {state.data.map((incident) => (
                <tr key={incident.scenario_id}>
                  <td data-label="Incident">
                    <div className="table-cell-value">
                      <strong>{incident.scenario_name}</strong>
                      <Identifier
                        value={incident.scenario_id}
                        label="scenario ID"
                      />
                    </div>
                  </td>
                  <td data-label="Started">
                    <div className="table-cell-value">
                      <LocalDate value={incident.started_at} />
                    </div>
                  </td>
                  <td data-label="Duration">
                    <div className="table-cell-value">
                      {duration(incident.started_at, incident.ended_at)}
                    </div>
                  </td>
                  <td data-label="Requests">
                    <div className="table-cell-value">
                      {incident.total_requests}
                      <small>
                        {incident.successful_requests} successful ·{" "}
                        {incident.failed_requests} failed
                      </small>
                    </div>
                  </td>
                  <td data-label="Outcome">
                    <div className="table-cell-value">
                      <StatusBadge
                        tone={incident.failed_requests ? "danger" : "success"}
                      >
                        {incident.failed_requests
                          ? "Failures observed"
                          : "Requests succeeded"}
                      </StatusBadge>
                    </div>
                  </td>
                  <td data-label="Action">
                    <div className="table-cell-value">
                      <Link
                        className="text-link"
                        to={`/incidents/${encodeURIComponent(incident.scenario_id)}`}
                      >
                        View details
                      </Link>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}
