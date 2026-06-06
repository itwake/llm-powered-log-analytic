export const API_BASE_URL = (
  process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000"
).replace(/\/$/, "");

type QueryValue = string | number | boolean | null | undefined;
type QueryParams = Record<string, QueryValue>;

type ApiOptions = Omit<RequestInit, "body" | "credentials"> & {
  body?: unknown;
  query?: QueryParams;
};

export class ApiError extends Error {
  status: number;
  detail: unknown;

  constructor(status: number, message: string, detail: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

function withQuery(path: string, query?: QueryParams): string {
  if (!query) {
    return path;
  }
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== null && value !== "") {
      params.set(key, String(value));
    }
  }
  const search = params.toString();
  return search ? `${path}?${search}` : path;
}

function apiUrl(pathOrUrl: string): string {
  if (/^https?:\/\//i.test(pathOrUrl)) {
    return pathOrUrl;
  }
  if (pathOrUrl.startsWith("/")) {
    return `${API_BASE_URL}${pathOrUrl}`;
  }
  return `${API_BASE_URL}/${pathOrUrl}`;
}

async function parseResponse(response: Response): Promise<unknown> {
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    return response.json();
  }
  return response.text();
}

function errorMessage(status: number, payload: unknown): string {
  if (payload && typeof payload === "object" && "detail" in payload) {
    const detail = (payload as {detail: unknown}).detail;
    return typeof detail === "string" ? detail : JSON.stringify(detail);
  }
  if (typeof payload === "string" && payload.trim()) {
    return payload;
  }
  return `Request failed with HTTP ${status}`;
}

async function request<T>(path: string, options: ApiOptions = {}): Promise<T> {
  const {body: payload, query, ...init} = options;
  const headers = new Headers(init.headers);
  let body: BodyInit | undefined;
  if (payload !== undefined) {
    headers.set("content-type", "application/json");
    body = JSON.stringify(payload);
  }
  const response = await fetch(`${API_BASE_URL}${withQuery(path, query)}`, {
    ...init,
    body,
    credentials: "include",
    headers,
  });
  if (!response.ok) {
    const payload = await parseResponse(response);
    throw new ApiError(response.status, errorMessage(response.status, payload), payload);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await parseResponse(response)) as T;
}

async function uploadRawFile(uploadUrl: string, file: File): Promise<UploadContentResponse> {
  const headers = new Headers();
  if (file.type) {
    headers.set("content-type", file.type);
  }
  const response = await fetch(apiUrl(uploadUrl), {
    method: "PUT",
    body: file,
    credentials: "include",
    headers,
  });
  if (!response.ok) {
    const payload = await parseResponse(response);
    throw new ApiError(response.status, errorMessage(response.status, payload), payload);
  }
  return (await parseResponse(response)) as UploadContentResponse;
}

export interface UserOut {
  id: string;
  email: string;
  username: string;
  role: string;
  has_copilot_credential: boolean;
}

export interface AuthUserResponse {
  user: UserOut;
}

export interface LoginRequest {
  email_or_username: string;
  password: string;
}

export interface RegisterRequest {
  email: string;
  username: string;
  full_name?: string | null;
  password: string;
}

export interface CaseCreateRequest {
  title: string;
  issue_description?: string | null;
  product?: string | null;
  service?: string | null;
  environment?: string | null;
  incident_start?: string | null;
  incident_end?: string | null;
  timezone?: string;
}

export interface CaseResponse {
  case_id: string;
  case_key: string;
  title: string | null;
  status: string;
  product: string | null;
  service: string | null;
  environment: string | null;
  incident_start: string | null;
  incident_end: string | null;
  timezone: string;
}

export interface CaseListResponse {
  items: CaseResponse[];
  total: number;
  page: number;
  page_size: number;
}

export interface UploadRequest {
  filename: string;
  content_type?: string | null;
  size_bytes: number;
}

export interface UploadStartResponse {
  file_id: string;
  upload_url: string;
  object_uri?: string | null;
  expires_in: number;
}

export interface UploadCompleteResponse {
  file_id: string;
  status: string;
  sha256: string;
  size_bytes?: number;
}

export interface UploadContentResponse {
  file_id: string;
  status: string;
  sha256: string;
  size_bytes: number;
}

export interface AnalysisRunRequest {
  input_file_ids?: string[];
  input_paths?: string[];
  config?: Record<string, unknown>;
}

export interface StartAnalysisResponse {
  analysis_run_id: string;
  status: string;
}

export interface AnalysisRunResponse {
  analysis_run_id: string;
  run_number: number;
  status: string;
  current_step: string;
  progress: Record<string, unknown>;
  started_at: string | null;
  completed_at: string | null;
  error_message: string | null;
  model_provider: string;
  model_name: string;
}

export interface AnalysisRunListResponse {
  items: AnalysisRunResponse[];
  total: number;
}

export interface SummaryItem {
  template_id: string;
  representative_log_id: string | null;
  template_text: string;
  representative_message: string;
  golden_signal: string;
  fault_categories: string[];
  entities: Record<string, string[]>;
  occurrence_count: number;
  first_seen: string | null;
  last_seen: string | null;
  files: string[];
  services: string[];
  severity_score: number;
  confidence: number;
}

export interface SummaryResponse {
  items: SummaryItem[];
  total: number;
  reduction: {
    raw_log_lines: number;
    offending_templates: number;
    estimated_review_reduction: number;
  };
}

export interface TemporalPoint {
  window_start: string;
  count: number;
}

export interface TemporalSeries {
  name: string;
  points: TemporalPoint[];
}

export interface TemporalResponse {
  window_size_seconds: number;
  series: TemporalSeries[];
}

export interface LogFacetValue {
  value: string;
  count: number;
}

export interface LogItem {
  log_id: string;
  timestamp: string | null;
  level: string | null;
  service: string | null;
  file_path: string;
  line_number: number;
  line_numbers: number[];
  message: string;
  template_id: string | null;
  template_text: string | null;
  golden_signal: string;
  fault_categories: string[];
  entities: Record<string, string[]>;
}

export interface LogsResponse {
  items: LogItem[];
  total: number;
  facets: {
    service: LogFacetValue[];
    golden_signal: LogFacetValue[];
    fault_category: LogFacetValue[];
  };
}

export interface EvidenceRef {
  case_id: string;
  analysis_run_id: string;
  template_id: string | null;
  log_id: string;
  file_path: string;
  line_number: number;
  timestamp: string | null;
}

export interface CausalNode {
  id: string;
  label: string;
  template_id: string;
  golden_signal: string;
  fault_categories: string[];
  occurrence_count: number;
  first_seen: string | null;
  last_seen: string | null;
  rank_score: number;
  pagerank_score: number;
  confidence: number;
  evidence_refs: EvidenceRef[];
}

export interface CausalEdge {
  id: string;
  source: string;
  target: string;
  source_template_id: string;
  target_template_id: string;
  edge_type: string;
  method: string;
  lag_seconds: number | null;
  support_windows: number;
  confidence: number;
  p_value_adj: number | null;
  lift: number | null;
  temporal_precedence_score: number | null;
  correlation_score: number | null;
  evidence: Record<string, unknown>;
  needs_validation: boolean;
}

export interface RootCauseCandidate {
  template_id: string;
  rank: number;
  score: number;
  reason: string;
}

export interface CausalGraphResponse {
  nodes: CausalNode[];
  edges: CausalEdge[];
  root_cause_candidates: RootCauseCandidate[];
}

export interface CausalSummaryResponse {
  summary_markdown: string;
  customer_update_markdown: string;
  next_actions: Record<string, unknown>[];
  evidence_refs: EvidenceRef[];
  confidence: number;
  edited: boolean;
}

export interface ExportRequest {
  export_type: "markdown" | "html" | "json";
  include_sections?: string[];
  redaction_mode?: string;
}

export interface ExportResponse {
  export_id: string;
  download_url: string;
  expires_in: number;
}

export interface FeedbackRequest {
  analysis_run_id?: string | null;
  target_type: string;
  target_id?: string | null;
  feedback_type: string;
  rating?: number | null;
  comment?: string | null;
  corrected_value?: Record<string, unknown> | null;
}

export interface FeedbackResponse {
  feedback_id: string;
}

export interface CopilotStartResponse {
  auth_id: string;
  user_code: string;
  verification_uri: string;
  verification_uri_complete: string;
  expires_in: number;
  interval: number;
}

export interface CopilotCheckResponse {
  status: "pending" | "authorized" | "expired" | "declined" | "error" | "not_found" | string;
  message?: string;
  next_poll_after_seconds?: number;
  token_type?: string;
  runtime_type?: string;
  expires_at?: string | null;
}

export interface CopilotDisconnectResponse {
  status: string;
  revoked_count: number;
}

export const authApi = {
  me: () => request<AuthUserResponse>("/api/auth/me"),
  login: (payload: LoginRequest) =>
    request<AuthUserResponse>("/api/auth/login", {method: "POST", body: payload}),
  logout: () => request<{status: string}>("/api/auth/logout", {method: "POST"}),
  register: (payload: RegisterRequest) =>
    request<AuthUserResponse>("/api/auth/register", {method: "POST", body: payload}),
};

export const casesApi = {
  list: (query?: {status?: string; product?: string; page?: number; page_size?: number}) =>
    request<CaseListResponse>("/api/cases", {query}),
  create: (payload: CaseCreateRequest) =>
    request<CaseResponse>("/api/cases", {method: "POST", body: payload}),
  get: (caseId: string) => request<CaseResponse>(`/api/cases/${caseId}`),
  requestUpload: (caseId: string, payload: UploadRequest) =>
    request<UploadStartResponse>(`/api/cases/${caseId}/uploads`, {
      method: "POST",
      body: payload,
    }),
  completeUpload: (caseId: string, fileId: string, sha256: string) =>
    request<UploadCompleteResponse>(`/api/cases/${caseId}/uploads/${fileId}/complete`, {
      method: "POST",
      body: {sha256},
    }),
  uploadContent: (uploadUrl: string, file: File) => uploadRawFile(uploadUrl, file),
  uploadFiles: async (caseId: string, files: File[]) => {
    const uploaded: UploadContentResponse[] = [];
    for (const file of files) {
      const upload = await casesApi.requestUpload(caseId, {
        filename: file.name || "upload.bin",
        content_type: file.type || null,
        size_bytes: file.size,
      });
      uploaded.push(await casesApi.uploadContent(upload.upload_url, file));
    }
    return uploaded;
  },
};

export const runsApi = {
  list: (caseId: string) => request<AnalysisRunListResponse>(`/api/cases/${caseId}/analysis-runs`),
  start: (caseId: string, payload: AnalysisRunRequest) =>
    request<StartAnalysisResponse>(`/api/cases/${caseId}/analysis-runs`, {
      method: "POST",
      body: payload,
    }),
  get: (caseId: string, runId: string) =>
    request<AnalysisRunResponse>(`/api/cases/${caseId}/analysis-runs/${runId}`),
};

export const reportsApi = {
  summary: (caseId: string, runId: string, query?: {golden_signal?: string; limit?: number; offset?: number}) =>
    request<SummaryResponse>(`/api/cases/${caseId}/analysis-runs/${runId}/summary`, {query}),
  temporal: (
    caseId: string,
    runId: string,
    query?: {window_size_seconds?: number; group_by?: string},
  ) => request<TemporalResponse>(`/api/cases/${caseId}/analysis-runs/${runId}/temporal`, {query}),
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
  ) => request<LogsResponse>(`/api/cases/${caseId}/analysis-runs/${runId}/logs`, {query}),
  causalGraph: (caseId: string, runId: string, query?: {max_nodes?: number; min_confidence?: number}) =>
    request<CausalGraphResponse>(`/api/cases/${caseId}/analysis-runs/${runId}/causal-graph`, {query}),
  causalSummary: (caseId: string, runId: string) =>
    request<CausalSummaryResponse>(`/api/cases/${caseId}/analysis-runs/${runId}/causal-summary`),
  createExport: (caseId: string, runId: string, payload: ExportRequest) =>
    request<ExportResponse>(`/api/cases/${caseId}/analysis-runs/${runId}/exports`, {
      method: "POST",
      body: payload,
    }),
  submitFeedback: (caseId: string, payload: FeedbackRequest) =>
    request<FeedbackResponse>(`/api/cases/${caseId}/feedback`, {method: "POST", body: payload}),
};

export const copilotAuthApi = {
  start: (github_base_url = "https://github.com") =>
    request<CopilotStartResponse>("/api/copilot/auth/start", {
      method: "POST",
      body: {github_base_url},
    }),
  check: (auth_id: string) =>
    request<CopilotCheckResponse>("/api/copilot/auth/check", {
      method: "POST",
      body: {auth_id},
    }),
  disconnect: () =>
    request<CopilotDisconnectResponse>("/api/copilot/auth/credential", {
      method: "DELETE",
    }),
};
