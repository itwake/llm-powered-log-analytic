import {request} from "./http";

import type {
  AnalysisRunListResponse,
  AnalysisRunRequest,
  AnalysisRunResponse,
  CausalGraphResponse,
  CausalSummaryResponse,
  LogsResponse,
  SummaryResponse,
  TemporalResponse,
} from "../api";

export const runsApi = {
  list: (caseId: string) =>
    request<AnalysisRunListResponse>(`/api/cases/${caseId}/analysis-runs`),
  start: (caseId: string, payload: AnalysisRunRequest) =>
    request<AnalysisRunResponse>(`/api/cases/${caseId}/analysis-runs`, {
      method: "POST",
      body: payload,
    }),
  get: (caseId: string, runId: string) =>
    request<AnalysisRunResponse>(`/api/cases/${caseId}/analysis-runs/${runId}`),
  cancel: (caseId: string, runId: string) =>
    request<AnalysisRunResponse>(`/api/cases/${caseId}/analysis-runs/${runId}/cancel`, {
      method: "POST",
    }),
};

export const reportsApi = {
  summary: (
    caseId: string,
    runId: string,
    query?: {golden_signal?: string; scope?: "attention" | "all"; limit?: number; offset?: number},
  ) =>
    request<SummaryResponse>(`/api/cases/${caseId}/analysis-runs/${runId}/summary`, {query}),
  temporal: (
    caseId: string,
    runId: string,
    query?: {group_by?: string},
  ) =>
    request<TemporalResponse>(`/api/cases/${caseId}/analysis-runs/${runId}/temporal`, {query}),
  logs: (
    caseId: string,
    runId: string,
    query?: {
      window_start?: string;
      window_end?: string;
      q?: string;
      service?: string;
      limit?: number;
      offset?: number;
    },
  ) =>
    request<LogsResponse>(`/api/cases/${caseId}/analysis-runs/${runId}/logs`, {query}),
  causalGraph: (
    caseId: string,
    runId: string,
    query?: {max_nodes?: number; min_confidence?: number},
  ) =>
    request<CausalGraphResponse>(
      `/api/cases/${caseId}/analysis-runs/${runId}/causal-graph`,
      {query},
    ),
  causalSummary: (caseId: string, runId: string) =>
    request<CausalSummaryResponse>(
      `/api/cases/${caseId}/analysis-runs/${runId}/causal-summary`,
    ),
};
