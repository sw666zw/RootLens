import type { Evidence, SafeEvidence } from "../../api/types";
import { StatusBadge } from "../status/status-badge";

const severityTone = {
  supporting: "success",
  contradicting: "danger",
  informational: "info",
} as const;

export function EvidenceCard({
  evidence,
}: {
  evidence: Evidence | SafeEvidence;
}) {
  const id = "evidence_id" in evidence ? evidence.evidence_id : null;
  const reference = "reference" in evidence ? evidence.reference : null;
  return (
    <article
      className={`evidence-card evidence-${evidence.severity}`}
      id={id ?? undefined}
    >
      <header>
        <div>
          <span className="evidence-source">{evidence.source}</span>
          <h4>{evidence.signal}</h4>
        </div>
        <StatusBadge tone={severityTone[evidence.severity]}>
          {evidence.severity}
        </StatusBadge>
      </header>
      <div className="evidence-observation">
        <span>Observation</span>
        <p>{evidence.observation}</p>
      </div>
      <dl className="compact-details">
        <div>
          <dt>Service</dt>
          <dd>{evidence.service ?? "Not specified"}</dd>
        </div>
        <div>
          <dt>Recorded value</dt>
          <dd>
            {evidence.value ?? "—"} {evidence.unit ?? ""}
          </dd>
        </div>
        {(reference || id) && (
          <div>
            <dt>Reference</dt>
            <dd className="evidence-id">{reference ?? id}</dd>
          </div>
        )}
      </dl>
    </article>
  );
}
