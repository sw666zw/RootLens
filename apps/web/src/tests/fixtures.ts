export const incidentSummary = {
  scenario_id: "baseline-20260805-abc",
  scenario_name: "baseline",
  started_at: "2026-08-05T12:00:00Z",
  ended_at: "2026-08-05T12:00:10Z",
  total_requests: 2,
  successful_requests: 2,
  failed_requests: 0,
};

export const incidentDetail = {
  scenario_id: incidentSummary.scenario_id,
  started_at: incidentSummary.started_at,
  ended_at: incidentSummary.ended_at,
  total_requests: 2,
  concurrency: 1,
  response_status_counts: { "201": 2 },
  successful_requests: 2,
  failed_requests: 0,
  request_id_count: 2,
  trace_id_count: 1,
  inventory_sku: "SAFE-SKU",
};

export const coverage = {
  metrics: "available",
  logs: "partial",
  traces: "available",
};

export const evidence = {
  source: "metrics",
  signal: "order success rate",
  observation: "All observed orders succeeded.",
  value: 1,
  unit: "ratio",
  service: "order",
  severity: "supporting",
  reference: "order_success_ratio",
};

export const diagnosisSummary = {
  diagnosis_id: "diagnosis-safe-test",
  generated_at: "2026-08-05T12:01:00Z",
  suspected_root_cause: "none",
  affected_service: null,
  confidence: 0.86,
  confidence_level: "high",
  telemetry_coverage: coverage,
  warnings: ["Logs were partially available."],
};

export const diagnosisDetail = {
  ...diagnosisSummary,
  schema_version: "1.0",
  analyzed_window: {
    start: "2026-08-05T11:59:45Z",
    end: "2026-08-05T12:00:25Z",
  },
  input_context: { total_requests: 2, request_id_count: 2, trace_id_count: 1 },
  summary: "The normalized evidence supports healthy behavior.",
  candidate_scores: {
    none: {
      score: 0.86,
      supporting_evidence: ["order_success_ratio"],
      contradicting_evidence: [],
    },
  },
  evidence: [evidence],
  alternative_causes: ["unknown"],
  recommended_checks: ["Confirm the service remains healthy."],
};

export const safeEvidence = {
  evidence_id: "evidence-001",
  source: "metrics",
  signal: "order success rate",
  observation: "All observed orders succeeded.",
  value: 1,
  unit: "ratio",
  service: "order",
  severity: "supporting",
};

export const validation = {
  protected_fields_match: true,
  evidence_references_valid: true,
  required_fields_present: true,
  no_ground_truth_fields: true,
  overall_valid: true,
};

export const explanationSummary = {
  explanation_id: "explanation-safe-test",
  diagnosis_id: diagnosisSummary.diagnosis_id,
  generated_at: "2026-08-05T12:02:00Z",
  provider: "template",
  provider_status: "completed",
  model: null,
  headline: "Systems appear healthy",
  confidence: 0.86,
};

export const explanationDetail = {
  ...explanationSummary,
  schema_version: "1.0",
  suspected_root_cause: "none",
  affected_service: null,
  confidence_level: "high",
  telemetry_coverage: coverage,
  executive_summary: "The deterministic diagnosis found healthy behavior.",
  impact: "No customer impact was detected.",
  causal_chain: [
    "Requests reached the services.",
    "Reservations completed successfully.",
  ],
  evidence_based_claims: [
    { claim: "Orders succeeded.", evidence_refs: ["evidence-001"] },
  ],
  evidence_index: [safeEvidence],
  uncertainties: ["The observation window is bounded."],
  immediate_actions: ["Continue monitoring."],
  follow_up_actions: ["Review the next incident."],
  operator_notes: null,
  validation,
  warnings: [],
};

export function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
