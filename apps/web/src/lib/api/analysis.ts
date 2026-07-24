import {request} from "./http";

import type {
  AnalysisRunListResponse,
  AnalysisRunRequest,
  AnalysisRunResponse,
  CausalGraphResponse,
  CausalSummaryResponse,
  CausalSummaryUpdateRequest,
  ExportRequest,
  ExportResponse,
  FeedbackRequest,
  FeedbackResponse,
  JobEventListResponse,
  LogsResponse,
  StartAnalysisResponse,
  SummaryResponse,
  TemporalResponse,
} from "../api";

export const runsApi = {
  list: (caseId: string) =>
    request<AnalysisRunListResponse>(`/api/cases/${caseId}/analysis-runs`),
  start: (caseId: string, payload: AnalysisRunRequest, options?: {background?: boolean}) =>
    request<StartAnalysisResponse>(`/api/cases/${caseId}/analysis-runs`, {
      method: "POST",
      body: payload,
      query: {background: options?.background || undefined},
    }),
  get: (caseId: string, runId: string) =>
    request<AnalysisRunResponse>(`/api/cases/${caseId}/analysis-runs/${runId}`),
  cancel: (caseId: string, runId: string) =>
    request<AnalysisRunResponse>(`/api/cases/${caseId}/analysis-runs/${runId}/cancel`, {
      method: "POST",
    }),
  events: (caseId: string, runId: string) =>
    request<JobEventListResponse>(`/api/cases/${caseId}/analysis-runs/${runId}/events`),
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
    query?: {window_size_seconds?: number; group_by?: string},
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
  updateCausalSummary: (
    caseId: string,
    runId: string,
    payload: CausalSummaryUpdateRequest,
  ) =>
    request<CausalSummaryResponse>(
      `/api/cases/${caseId}/analysis-runs/${runId}/causal-summary`,
      {
        method: "PATCH",
        body: payload,
      },
    ),
  createExport: (caseId: string, runId: string, payload: ExportRequest) =>
    request<ExportResponse>(`/api/cases/${caseId}/analysis-runs/${runId}/exports`, {
      method: "POST",
      body: payload,
    }),
  submitFeedback: (caseId: string, payload: FeedbackRequest) =>
    request<FeedbackResponse>(`/api/cases/${caseId}/feedback`, {
      method: "POST",
      body: payload,
    }),
};
