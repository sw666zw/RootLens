import { ApiInvalidResponseError } from "./errors";
import type {
  CandidateScore,
  DiagnosisDetail,
  DiagnosisResponse,
  DiagnosisSummary,
  Evidence,
  EvidenceClaim,
  ExplanationDetail,
  ExplanationResponse,
  ExplanationSummary,
  HealthResponse,
  IncidentDetail,
  IncidentSummary,
  SafeEvidence,
  TelemetryCoverageValue,
  ValidationResponse,
  ValidationSummary,
} from "./types";

type JsonObject = Record<string, unknown>;

const fail = (): never => {
  throw new ApiInvalidResponseError();
};

function object(value: unknown): JsonObject {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as JsonObject)
    : fail();
}

function string(value: unknown): string {
  return typeof value === "string" ? value : fail();
}

function number(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fail();
}

function boolean(value: unknown): boolean {
  return typeof value === "boolean" ? value : fail();
}

function nullableString(value: unknown): string | null {
  return value === null ? null : string(value);
}

function strings(value: unknown): string[] {
  return Array.isArray(value) ? value.map(string) : fail();
}

function list<T>(value: unknown, parser: (item: unknown) => T): T[] {
  return Array.isArray(value) ? value.map(parser) : fail();
}

function record<T>(
  value: unknown,
  parser: (item: unknown) => T,
): Record<string, T> {
  const source = object(value);
  return Object.fromEntries(
    Object.entries(source).map(([key, item]) => [key, parser(item)]),
  );
}

function enumValue<T extends string>(value: unknown, allowed: readonly T[]): T {
  const candidate = string(value) as T;
  return allowed.includes(candidate) ? candidate : fail();
}

const rootCauses = [
  "none",
  "inventory_reservation_latency",
  "inventory_service_unavailable",
  "unknown",
] as const;
const sourceStatuses = ["available", "partial", "unavailable"] as const;
const evidenceSources = ["metrics", "logs", "traces"] as const;
const evidenceSeverities = [
  "supporting",
  "contradicting",
  "informational",
] as const;
const providerStatuses = ["completed", "fallback"] as const;

function coverage(value: unknown): TelemetryCoverageValue {
  const data = object(value);
  return {
    metrics: enumValue(data.metrics, sourceStatuses),
    logs: enumValue(data.logs, sourceStatuses),
    traces: enumValue(data.traces, sourceStatuses),
  };
}

function validation(value: unknown): ValidationSummary {
  const data = object(value);
  return {
    protected_fields_match: boolean(data.protected_fields_match),
    evidence_references_valid: boolean(data.evidence_references_valid),
    required_fields_present: boolean(data.required_fields_present),
    no_ground_truth_fields: boolean(data.no_ground_truth_fields),
    overall_valid: boolean(data.overall_valid),
  };
}

function diagnosisSummary(value: unknown): DiagnosisSummary {
  const data = object(value);
  return {
    diagnosis_id: string(data.diagnosis_id),
    generated_at: string(data.generated_at),
    suspected_root_cause: enumValue(data.suspected_root_cause, rootCauses),
    affected_service: nullableString(data.affected_service),
    confidence: number(data.confidence),
    confidence_level: string(data.confidence_level),
    telemetry_coverage: coverage(data.telemetry_coverage),
    warnings: strings(data.warnings),
  };
}

function evidence(value: unknown): Evidence {
  const data = object(value);
  return {
    source: enumValue(data.source, evidenceSources),
    signal: string(data.signal),
    observation: string(data.observation),
    value: data.value === null ? null : number(data.value),
    unit: nullableString(data.unit),
    service: nullableString(data.service),
    severity: enumValue(data.severity, evidenceSeverities),
    reference: string(data.reference),
  };
}

function safeEvidence(value: unknown): SafeEvidence {
  const data = object(value);
  return {
    evidence_id: string(data.evidence_id),
    source: enumValue(data.source, evidenceSources),
    signal: string(data.signal),
    observation: string(data.observation),
    value: data.value === null ? null : number(data.value),
    unit: nullableString(data.unit),
    service: nullableString(data.service),
    severity: enumValue(data.severity, evidenceSeverities),
  };
}

function candidate(value: unknown): CandidateScore {
  const data = object(value);
  return {
    score: number(data.score),
    supporting_evidence: strings(data.supporting_evidence),
    contradicting_evidence: strings(data.contradicting_evidence),
  };
}

function claim(value: unknown): EvidenceClaim {
  const data = object(value);
  return {
    claim: string(data.claim),
    evidence_refs: strings(data.evidence_refs),
  };
}

export function parseHealth(value: unknown): HealthResponse {
  const data = object(value);
  return { status: string(data.status), service: string(data.service) };
}

export function parseIncidentSummaries(value: unknown): IncidentSummary[] {
  return list(value, (item) => {
    const data = object(item);
    return {
      scenario_id: string(data.scenario_id),
      scenario_name: string(data.scenario_name),
      started_at: string(data.started_at),
      ended_at: string(data.ended_at),
      total_requests: number(data.total_requests),
      successful_requests: number(data.successful_requests),
      failed_requests: number(data.failed_requests),
    };
  });
}

export function parseIncidentDetail(value: unknown): IncidentDetail {
  const data = object(value);
  return {
    scenario_id: string(data.scenario_id),
    started_at: string(data.started_at),
    ended_at: string(data.ended_at),
    total_requests: number(data.total_requests),
    concurrency: number(data.concurrency),
    response_status_counts: record(data.response_status_counts, number),
    successful_requests: number(data.successful_requests),
    failed_requests: number(data.failed_requests),
    request_id_count: number(data.request_id_count),
    trace_id_count: number(data.trace_id_count),
    inventory_sku:
      data.inventory_sku === undefined
        ? null
        : nullableString(data.inventory_sku),
  };
}

export function parseDiagnosisSummaries(value: unknown): DiagnosisSummary[] {
  return list(value, diagnosisSummary);
}

export function parseDiagnosisDetail(value: unknown): DiagnosisDetail {
  const data = object(value);
  return {
    ...diagnosisSummary(data),
    schema_version: string(data.schema_version),
    analyzed_window: (() => {
      const window = object(data.analyzed_window);
      return { start: string(window.start), end: string(window.end) };
    })(),
    input_context: (() => {
      const context = object(data.input_context);
      return {
        total_requests: number(context.total_requests),
        request_id_count: number(context.request_id_count),
        trace_id_count: number(context.trace_id_count),
      };
    })(),
    summary: string(data.summary),
    candidate_scores: record(data.candidate_scores, candidate),
    evidence: list(data.evidence, evidence),
    alternative_causes: list(data.alternative_causes, (item) =>
      enumValue(item, rootCauses),
    ),
    recommended_checks: strings(data.recommended_checks),
  };
}

export function parseDiagnosisResponse(value: unknown): DiagnosisResponse {
  const data = object(value);
  return {
    ...diagnosisSummary(data),
    summary: string(data.summary),
    report_url: string(data.report_url),
  };
}

function explanationSummary(value: unknown): ExplanationSummary {
  const data = object(value);
  return {
    explanation_id: string(data.explanation_id),
    diagnosis_id: string(data.diagnosis_id),
    generated_at: string(data.generated_at),
    provider: string(data.provider),
    provider_status: enumValue(data.provider_status, providerStatuses),
    model: nullableString(data.model),
    headline: string(data.headline),
    confidence: number(data.confidence),
  };
}

export function parseExplanationSummaries(
  value: unknown,
): ExplanationSummary[] {
  return list(value, explanationSummary);
}

export function parseExplanationDetail(value: unknown): ExplanationDetail {
  const data = object(value);
  return {
    ...explanationSummary(data),
    schema_version: string(data.schema_version),
    suspected_root_cause: enumValue(data.suspected_root_cause, rootCauses),
    affected_service: nullableString(data.affected_service),
    confidence_level: string(data.confidence_level),
    telemetry_coverage: coverage(data.telemetry_coverage),
    executive_summary: string(data.executive_summary),
    impact: string(data.impact),
    causal_chain: strings(data.causal_chain),
    evidence_based_claims: list(data.evidence_based_claims, claim),
    evidence_index: list(data.evidence_index, safeEvidence),
    uncertainties: strings(data.uncertainties),
    immediate_actions: strings(data.immediate_actions),
    follow_up_actions: strings(data.follow_up_actions),
    operator_notes:
      data.operator_notes === undefined
        ? null
        : nullableString(data.operator_notes),
    validation: validation(data.validation),
    warnings: strings(data.warnings),
  };
}

export function parseExplanationResponse(value: unknown): ExplanationResponse {
  const data = object(value);
  return {
    explanation_id: string(data.explanation_id),
    diagnosis_id: string(data.diagnosis_id),
    provider: string(data.provider),
    provider_status: enumValue(data.provider_status, providerStatuses),
    model: nullableString(data.model),
    headline: string(data.headline),
    executive_summary: string(data.executive_summary),
    confidence: number(data.confidence),
    validation: validation(data.validation),
    warnings: strings(data.warnings),
    report_url: string(data.report_url),
  };
}

export function parseValidationResponse(value: unknown): ValidationResponse {
  const data = object(value);
  return {
    ...validation(data),
    validation_report_id: string(data.validation_report_id),
  };
}
