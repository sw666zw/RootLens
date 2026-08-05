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
    <article className="evidence-card" id={id ?? undefined}>
      <header>
        <div>
          {id && <span className="evidence-id">{id}</span>}
          <h4>{evidence.signal}</h4>
        </div>
        <StatusBadge tone={severityTone[evidence.severity]}>
          {evidence.severity}
        </StatusBadge>
      </header>
      <p>{evidence.observation}</p>
      <dl className="compact-details">
        <div>
          <dt>Service</dt>
          <dd>{evidence.service ?? "Not specified"}</dd>
        </div>
        <div>
          <dt>Value</dt>
          <dd>
            {evidence.value ?? "—"} {evidence.unit ?? ""}
          </dd>
        </div>
        {reference && (
          <div>
            <dt>Safe reference</dt>
            <dd>{reference}</dd>
          </div>
        )}
      </dl>
    </article>
  );
}
