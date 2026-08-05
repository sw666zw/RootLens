export type RootCause =
  | "none"
  | "inventory_reservation_latency"
  | "inventory_service_unavailable"
  | "unknown";

export type SourceStatus = "available" | "partial" | "unavailable";
export type EvidenceSource = "metrics" | "logs" | "traces";
export type EvidenceSeverity = "supporting" | "contradicting" | "informational";
export type ProviderStatus = "completed" | "fallback";

export interface HealthResponse {
  status: string;
  service: string;
}

export interface IncidentSummary {
  scenario_id: string;
  scenario_name: string;
  started_at: string;
  ended_at: string;
  total_requests: number;
  successful_requests: number;
  failed_requests: number;
}

export interface IncidentDetail {
  scenario_id: string;
  started_at: string;
  ended_at: string;
  total_requests: number;
  concurrency: number;
  response_status_counts: Record<string, number>;
  successful_requests: number;
  failed_requests: number;
  request_id_count: number;
  trace_id_count: number;
  inventory_sku: string | null;
}

export interface TelemetryCoverageValue {
  metrics: SourceStatus;
  logs: SourceStatus;
  traces: SourceStatus;
}

export interface DiagnosisSummary {
  diagnosis_id: string;
  generated_at: string;
  suspected_root_cause: RootCause;
  affected_service: string | null;
  confidence: number;
  confidence_level: string;
  telemetry_coverage: TelemetryCoverageValue;
  warnings: string[];
}

export interface AnalysisWindow {
  start: string;
  end: string;
}

export interface InputContext {
  total_requests: number;
  request_id_count: number;
  trace_id_count: number;
}

export interface CandidateScore {
  score: number;
  supporting_evidence: string[];
  contradicting_evidence: string[];
}

export interface Evidence {
  source: EvidenceSource;
  signal: string;
  observation: string;
  value: number | null;
  unit: string | null;
  service: string | null;
  severity: EvidenceSeverity;
  reference: string;
}

export interface DiagnosisDetail extends DiagnosisSummary {
  schema_version: string;
  analyzed_window: AnalysisWindow;
  input_context: InputContext;
  summary: string;
  candidate_scores: Record<string, CandidateScore>;
  evidence: Evidence[];
  alternative_causes: RootCause[];
  recommended_checks: string[];
}

export interface DiagnosisResponse extends DiagnosisSummary {
  summary: string;
  report_url: string;
}

export interface ValidationSummary {
  protected_fields_match: boolean;
  evidence_references_valid: boolean;
  required_fields_present: boolean;
  no_ground_truth_fields: boolean;
  overall_valid: boolean;
}

export interface SafeEvidence extends Omit<Evidence, "reference"> {
  evidence_id: string;
}

export interface EvidenceClaim {
  claim: string;
  evidence_refs: string[];
}

export interface ExplanationSummary {
  explanation_id: string;
  diagnosis_id: string;
  generated_at: string;
  provider: string;
  provider_status: ProviderStatus;
  model: string | null;
  headline: string;
  confidence: number;
}

export interface ExplanationDetail extends ExplanationSummary {
  schema_version: string;
  suspected_root_cause: RootCause;
  affected_service: string | null;
  confidence_level: string;
  telemetry_coverage: TelemetryCoverageValue;
  executive_summary: string;
  impact: string;
  causal_chain: string[];
  evidence_based_claims: EvidenceClaim[];
  evidence_index: SafeEvidence[];
  uncertainties: string[];
  immediate_actions: string[];
  follow_up_actions: string[];
  operator_notes: string | null;
  validation: ValidationSummary;
  warnings: string[];
}

export interface ExplanationResponse {
  explanation_id: string;
  diagnosis_id: string;
  provider: string;
  provider_status: ProviderStatus;
  model: string | null;
  headline: string;
  executive_summary: string;
  confidence: number;
  validation: ValidationSummary;
  warnings: string[];
  report_url: string;
}

export interface ValidationResponse extends ValidationSummary {
  validation_report_id: string;
}

export interface DiagnoseRequest {
  require_all_sources: boolean;
  window_padding_seconds: number | null;
}

export interface ExplainRequest {
  provider: "template" | "openai";
  allow_template_fallback: boolean;
}
