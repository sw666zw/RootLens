import {
  ApiConnectionError,
  ApiHttpError,
  ApiInvalidJsonError,
} from "./errors";
import {
  parseDiagnosisDetail,
  parseDiagnosisResponse,
  parseDiagnosisSummaries,
  parseExplanationDetail,
  parseExplanationResponse,
  parseExplanationSummaries,
  parseHealth,
  parseIncidentDetail,
  parseIncidentSummaries,
  parseValidationResponse,
} from "./parsers";
import type { DiagnoseRequest, ExplainRequest } from "./types";

const configuredBase = import.meta.env.VITE_DIAGNOSIS_API_BASE_URL;
const API_BASE =
  typeof configuredBase === "string" && configuredBase.trim()
    ? configuredBase.replace(/\/$/, "")
    : "/api";

async function readJson(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    throw new ApiInvalidJsonError();
  }
}

function safeHttpMessage(payload: unknown, status: number): string {
  if (
    payload !== null &&
    typeof payload === "object" &&
    "detail" in payload &&
    typeof payload.detail === "string"
  ) {
    return payload.detail;
  }
  return `The Diagnosis Service returned HTTP ${status}.`;
}

async function request(
  path: string,
  init: RequestInit,
  acceptedStatuses: number[] = [],
): Promise<unknown> {
  let response: Response;
  try {
    const headers = new Headers(init.headers);
    headers.set("Accept", "application/json");
    if (init.body) headers.set("Content-Type", "application/json");
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError")
      throw error;
    throw new ApiConnectionError();
  }
  const payload = await readJson(response);
  if (!response.ok && !acceptedStatuses.includes(response.status)) {
    throw new ApiHttpError(
      response.status,
      safeHttpMessage(payload, response.status),
    );
  }
  return payload;
}

function query(
  parameters: Record<string, string | number | undefined>,
): string {
  const search = new URLSearchParams();
  Object.entries(parameters).forEach(([key, value]) => {
    if (value !== undefined && value !== "") search.set(key, String(value));
  });
  const result = search.toString();
  return result ? `?${result}` : "";
}

export const api = {
  health: async (signal?: AbortSignal) =>
    parseHealth(await request("/health", { method: "GET", signal })),

  incidents: async (
    options: {
      limit?: number;
      scenarioName?: string;
      signal?: AbortSignal;
    } = {},
  ) =>
    parseIncidentSummaries(
      await request(
        `/incidents${query({ limit: options.limit, scenario_name: options.scenarioName })}`,
        { method: "GET", signal: options.signal },
      ),
    ),

  incident: async (scenarioId: string, signal?: AbortSignal) =>
    parseIncidentDetail(
      await request(`/incidents/${encodeURIComponent(scenarioId)}`, {
        method: "GET",
        signal,
      }),
    ),

  diagnose: async (
    scenarioId: string,
    payload: DiagnoseRequest,
    signal?: AbortSignal,
  ) =>
    parseDiagnosisResponse(
      await request(`/incidents/${encodeURIComponent(scenarioId)}/diagnose`, {
        method: "POST",
        body: JSON.stringify(payload),
        signal,
      }),
    ),

  diagnoses: async (
    options: {
      limit?: number;
      rootCause?: string;
      confidenceLevel?: string;
      signal?: AbortSignal;
    } = {},
  ) =>
    parseDiagnosisSummaries(
      await request(
        `/diagnoses${query({
          limit: options.limit,
          root_cause: options.rootCause,
          confidence_level: options.confidenceLevel,
        })}`,
        { method: "GET", signal: options.signal },
      ),
    ),

  diagnosis: async (diagnosisId: string, signal?: AbortSignal) =>
    parseDiagnosisDetail(
      await request(`/diagnoses/${encodeURIComponent(diagnosisId)}`, {
        method: "GET",
        signal,
      }),
    ),

  explain: async (
    diagnosisId: string,
    payload: ExplainRequest,
    signal?: AbortSignal,
  ) =>
    parseExplanationResponse(
      await request(`/diagnoses/${encodeURIComponent(diagnosisId)}/explain`, {
        method: "POST",
        body: JSON.stringify(payload),
        signal,
      }),
    ),

  explanations: async (
    options: {
      limit?: number;
      provider?: string;
      providerStatus?: string;
      signal?: AbortSignal;
    } = {},
  ) =>
    parseExplanationSummaries(
      await request(
        `/explanations${query({
          limit: options.limit,
          provider: options.provider,
          provider_status: options.providerStatus,
        })}`,
        { method: "GET", signal: options.signal },
      ),
    ),

  explanation: async (explanationId: string, signal?: AbortSignal) =>
    parseExplanationDetail(
      await request(`/explanations/${encodeURIComponent(explanationId)}`, {
        method: "GET",
        signal,
      }),
    ),

  validateExplanation: async (
    explanationId: string,
    diagnosisId: string,
    signal?: AbortSignal,
  ) =>
    parseValidationResponse(
      await request(
        `/explanations/${encodeURIComponent(explanationId)}/validate`,
        {
          method: "POST",
          body: JSON.stringify({ diagnosis_id: diagnosisId }),
          signal,
        },
        [422],
      ),
    ),
};
