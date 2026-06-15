export const API_BASE_URL = (
  process.env.NEXT_PUBLIC_API_BASE_URL || ""
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

async function sha256File(file: File): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function uploadPresignedFile(upload: UploadStartResponse, file: File): Promise<void> {
  if (!upload.upload_url) {
    throw new Error("upload response did not include an upload URL");
  }
  const headers = new Headers(upload.upload_headers || {});
  const response = await fetch(upload.upload_url, {
    method: "PUT",
    body: file,
    credentials: "omit",
    headers,
  });
  if (!response.ok) {
    const payload = await parseResponse(response);
    throw new ApiError(response.status, errorMessage(response.status, payload), payload);
  }
}

async function uploadMultipartFile(
  upload: UploadStartResponse,
  file: File,
): Promise<{sha256: string; parts: MultipartCompletePart[]}> {
  if (!upload.multipart_upload_id || !upload.part_size_bytes || !upload.parts?.length) {
    throw new Error("multipart upload response is incomplete");
  }
  const completedParts: MultipartCompletePart[] = [];
  const sortedParts = [...upload.parts].sort((left, right) => left.part_number - right.part_number);
  for (const part of sortedParts) {
    const start = (part.part_number - 1) * upload.part_size_bytes;
    const end = Math.min(start + upload.part_size_bytes, file.size);
    const response = await fetch(part.upload_url, {
      method: "PUT",
      body: file.slice(start, end),
      credentials: "omit",
      headers: new Headers(part.upload_headers || {}),
    });
    if (!response.ok) {
      const payload = await parseResponse(response);
      throw new ApiError(response.status, errorMessage(response.status, payload), payload);
    }
    const etag = response.headers.get("etag");
    if (!etag) {
      throw new Error(`multipart part ${part.part_number} did not return an ETag`);
    }
    completedParts.push({part_number: part.part_number, etag});
  }
  return {sha256: await sha256File(file), parts: completedParts};
}

export interface UserOut {
  id: string;
  organization_id: string;
  email: string;
  username: string;
  role: string;
  is_active: boolean;
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

export interface CaseCollaborator {
  id: string;
  case_id: string;
  user_id: string;
  role: "owner" | "editor" | "viewer" | string;
  added_by: string | null;
  email: string | null;
  username: string | null;
  full_name: string | null;
  created_at: string;
  updated_at: string;
}

export interface CaseCollaboratorListResponse {
  items: CaseCollaborator[];
  total: number;
}

export interface UploadRequest {
  filename: string;
  content_type?: string | null;
  size_bytes: number;
  multipart?: boolean | null;
  part_size_bytes?: number | null;
}

export interface MultipartUploadPartUrl {
  part_number: number;
  upload_url: string;
  upload_headers: Record<string, string>;
}

export interface MultipartUploadedPart {
  part_number: number;
  etag: string;
  size_bytes: number;
}

export interface MultipartCompletePart {
  part_number: number;
  etag: string;
}

export interface UploadStartResponse {
  file_id: string;
  upload_url?: string;
  object_uri?: string | null;
  upload_backend?: "local" | "s3" | "minio" | string;
  upload_mode?: "single" | "multipart" | string;
  upload_headers?: Record<string, string>;
  multipart_upload_id?: string;
  part_size_bytes?: number;
  part_count?: number;
  parts?: MultipartUploadPartUrl[];
  uploaded_parts?: MultipartUploadedPart[];
  expires_in: number;
}

export interface UploadCompleteResponse {
  file_id: string;
  status: string;
  sha256: string;
  size_bytes: number;
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
  evidence_claims?: Record<string, unknown>[];
  uncertainties?: string[];
  details?: Record<string, unknown>;
  confidence: number;
  edited: boolean;
}

export interface CausalSummaryUpdateRequest {
  summary_markdown: string;
  customer_update_markdown?: string | null;
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

export interface ChatRequest {
  message: string;
  session_id?: string | null;
  case_id?: string | null;
  analysis_run_id?: string | null;
  attachments?: Record<string, unknown>[];
}

export interface ChatStreamHandlers {
  delta?: (delta: string) => void;
  evidence?: (evidenceRefs: EvidenceRef[]) => void;
  done?: (message: string) => void;
  error?: (message: string) => void;
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

export interface AdminUser {
  id: string;
  organization_id: string;
  email: string;
  username: string;
  full_name: string | null;
  role: "admin" | "engineer" | string;
  is_active: boolean;
  has_copilot_credential: boolean;
  created_at: string;
}

export interface AdminUserListResponse {
  items: AdminUser[];
  total: number;
  offset: number;
  limit: number;
}

export interface AdminAuditLog {
  id: string;
  action: string;
  user_id: string | null;
  target_type: string | null;
  target_id: string | null;
  case_id: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface AdminAuditLogListResponse {
  items: AdminAuditLog[];
  total: number;
  offset: number;
  limit: number;
}

export interface AdminSettingsResponse {
  env: string;
  store_backend: string;
  configured_store_backend: string;
  object_backend: string;
  orchestrator: string;
  retention_days: Record<string, number>;
  rate_limit: {
    enabled: boolean;
    requests_per_minute: number;
  };
  analytics: Record<string, string | boolean>;
}

export interface RetentionRunResponse {
  audit_logs_deleted: number;
  raw_log_lines_scrubbed: number;
  exports_deleted: number;
  analysis_results_cleared: number;
  step_artifacts_deleted: number;
}

export interface AdminPolicyGroup {
  id: string;
  organization_id: string;
  name: string;
  slug: string;
  description: string | null;
  member_count: number;
  created_at: string;
  updated_at: string;
}

export interface AdminPolicyGroupListResponse {
  items: AdminPolicyGroup[];
  total: number;
}

export interface AdminPolicyGroupMember {
  id: string;
  group_id: string;
  user_id: string;
  role: "owner" | "editor" | "viewer" | string;
  added_by: string | null;
  email: string | null;
  username: string | null;
  full_name: string | null;
  created_at: string;
  updated_at: string;
}

export interface AdminPolicyGroupMemberListResponse {
  items: AdminPolicyGroupMember[];
  total: number;
}

export interface AdminCaseGroupAccess {
  id: string;
  case_id: string;
  group_id: string;
  role: "owner" | "editor" | "viewer" | string;
  granted_by: string | null;
  group_name: string | null;
  group_slug: string | null;
  created_at: string;
  updated_at: string;
}

export interface AdminCaseGroupAccessListResponse {
  items: AdminCaseGroupAccess[];
  total: number;
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
  listCollaborators: (caseId: string) =>
    request<CaseCollaboratorListResponse>(`/api/cases/${caseId}/collaborators`),
  upsertCollaborator: (caseId: string, payload: {user_id: string; role: string}) =>
    request<CaseCollaborator>(`/api/cases/${caseId}/collaborators`, {
      method: "POST",
      body: payload,
    }),
  removeCollaborator: (caseId: string, userId: string) =>
    request<{status: string; removed: boolean}>(
      `/api/cases/${caseId}/collaborators/${userId}`,
      {method: "DELETE"},
    ),
  requestUpload: (caseId: string, payload: UploadRequest) =>
    request<UploadStartResponse>(`/api/cases/${caseId}/uploads`, {
      method: "POST",
      body: payload,
    }),
  refreshMultipartUpload: (caseId: string, fileId: string) =>
    request<UploadStartResponse>(`/api/cases/${caseId}/uploads/${fileId}/multipart`),
  abortMultipartUpload: (caseId: string, fileId: string) =>
    request<{file_id: string; status: string; aborted_at: string}>(
      `/api/cases/${caseId}/uploads/${fileId}/multipart`,
      {method: "DELETE"},
    ),
  completeUpload: (
    caseId: string,
    fileId: string,
    sha256: string,
    multipart?: {multipart_upload_id: string; parts: MultipartCompletePart[]},
  ) =>
    request<UploadCompleteResponse>(`/api/cases/${caseId}/uploads/${fileId}/complete`, {
      method: "POST",
      body: multipart ? {sha256, ...multipart} : {sha256},
  }),
  uploadContent: async (caseId: string, upload: UploadStartResponse, file: File) => {
    if (upload.upload_mode === "multipart") {
      if (!upload.multipart_upload_id) {
        throw new Error("multipart upload response is missing an upload id");
      }
      const multipartUploadId = upload.multipart_upload_id;
      const completed = await uploadMultipartFile(upload, file);
      return casesApi.completeUpload(caseId, upload.file_id, completed.sha256, {
        multipart_upload_id: multipartUploadId,
        parts: completed.parts,
      });
    }
    if (upload.upload_backend === "s3" || upload.upload_backend === "minio") {
      const sha256 = await sha256File(file);
      await uploadPresignedFile(upload, file);
      return casesApi.completeUpload(caseId, upload.file_id, sha256);
    }
    if (!upload.upload_url) {
      throw new Error("upload response did not include an upload URL");
    }
    return uploadRawFile(upload.upload_url, file);
  },
  uploadFiles: async (caseId: string, files: File[]) => {
    const uploaded: UploadContentResponse[] = [];
    for (const file of files) {
      const upload = await casesApi.requestUpload(caseId, {
        filename: file.name || "upload.bin",
        content_type: file.type || null,
        size_bytes: file.size,
      });
      uploaded.push(await casesApi.uploadContent(caseId, upload, file));
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
  updateCausalSummary: (caseId: string, runId: string, payload: CausalSummaryUpdateRequest) =>
    request<CausalSummaryResponse>(`/api/cases/${caseId}/analysis-runs/${runId}/causal-summary`, {
      method: "PATCH",
      body: payload,
    }),
  createExport: (caseId: string, runId: string, payload: ExportRequest) =>
    request<ExportResponse>(`/api/cases/${caseId}/analysis-runs/${runId}/exports`, {
      method: "POST",
      body: payload,
    }),
  submitFeedback: (caseId: string, payload: FeedbackRequest) =>
    request<FeedbackResponse>(`/api/cases/${caseId}/feedback`, {method: "POST", body: payload}),
};

export const chatApi = {
  stream: async (
    payload: ChatRequest,
    handlers: ChatStreamHandlers,
    signal?: AbortSignal,
  ): Promise<void> => {
    const response = await fetch(`${API_BASE_URL}/api/chat/stream`, {
      method: "POST",
      body: JSON.stringify(payload),
      credentials: "include",
      headers: {"content-type": "application/json"},
      signal,
    });
    if (!response.ok) {
      const errorPayload = await parseResponse(response);
      throw new ApiError(response.status, errorMessage(response.status, errorPayload), errorPayload);
    }
    if (!response.body) {
      throw new Error("Streaming response body is unavailable");
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const {done, value} = await reader.read();
      if (done) {
        break;
      }
      buffer += decoder.decode(value, {stream: true});
      buffer = dispatchSseFrames(buffer, handlers);
    }
    buffer += decoder.decode();
    if (buffer.trim()) {
      dispatchSseFrame(buffer, handlers);
    }
  },
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

export const adminApi = {
  users: (query?: {q?: string; role?: string; active?: boolean; limit?: number; offset?: number}) =>
    request<AdminUserListResponse>("/api/admin/users", {query}),
  updateUser: (userId: string, payload: {role?: string; is_active?: boolean}) =>
    request<AdminUser>(`/api/admin/users/${userId}`, {
      method: "PATCH",
      body: payload,
    }),
  auditLogs: (query?: {
    case_id?: string;
    action?: string;
    user_id?: string;
    limit?: number;
    offset?: number;
  }) => request<AdminAuditLogListResponse>("/api/admin/audit-logs", {query}),
  exportAuditLogs: async (query?: {
    format?: "json" | "ndjson" | "csv";
    case_id?: string;
    action?: string;
    user_id?: string;
    limit?: number;
    offset?: number;
  }) => {
    const response = await fetch(
      `${API_BASE_URL}${withQuery("/api/admin/audit-logs/export", query)}`,
      {credentials: "include"},
    );
    if (!response.ok) {
      const payload = await parseResponse(response);
      throw new ApiError(response.status, errorMessage(response.status, payload), payload);
    }
    return response.text();
  },
  settings: () => request<AdminSettingsResponse>("/api/admin/settings"),
  runRetention: () =>
    request<RetentionRunResponse>("/api/admin/retention/run", {method: "POST"}),
  policyGroups: () =>
    request<AdminPolicyGroupListResponse>("/api/admin/policy-groups"),
  createPolicyGroup: (payload: {name: string; slug?: string | null; description?: string | null}) =>
    request<AdminPolicyGroup>("/api/admin/policy-groups", {method: "POST", body: payload}),
  updatePolicyGroup: (
    groupId: string,
    payload: {name?: string; slug?: string | null; description?: string | null},
  ) =>
    request<AdminPolicyGroup>(`/api/admin/policy-groups/${groupId}`, {
      method: "PATCH",
      body: payload,
    }),
  policyGroupMembers: (groupId: string) =>
    request<AdminPolicyGroupMemberListResponse>(`/api/admin/policy-groups/${groupId}/members`),
  upsertPolicyGroupMember: (
    groupId: string,
    payload: {user_id: string; role: "owner" | "editor" | "viewer" | string},
  ) =>
    request<AdminPolicyGroupMember>(`/api/admin/policy-groups/${groupId}/members`, {
      method: "POST",
      body: payload,
    }),
  removePolicyGroupMember: (groupId: string, userId: string) =>
    request<{status: string; removed: boolean}>(
      `/api/admin/policy-groups/${groupId}/members/${userId}`,
      {method: "DELETE"},
    ),
  casePolicyGroups: (caseId: string) =>
    request<AdminCaseGroupAccessListResponse>(`/api/admin/cases/${caseId}/policy-groups`),
  upsertCasePolicyGroup: (
    caseId: string,
    payload: {group_id: string; role: "owner" | "editor" | "viewer" | string},
  ) =>
    request<AdminCaseGroupAccess>(`/api/admin/cases/${caseId}/policy-groups`, {
      method: "POST",
      body: payload,
    }),
  removeCasePolicyGroup: (caseId: string, groupId: string) =>
    request<{status: string; removed: boolean}>(
      `/api/admin/cases/${caseId}/policy-groups/${groupId}`,
      {method: "DELETE"},
    ),
};

function dispatchSseFrames(buffer: string, handlers: ChatStreamHandlers): string {
  const normalized = buffer.replace(/\r\n/g, "\n");
  const frames = normalized.split("\n\n");
  const remainder = frames.pop() || "";
  for (const frame of frames) {
    dispatchSseFrame(frame, handlers);
  }
  return remainder;
}

function dispatchSseFrame(frame: string, handlers: ChatStreamHandlers): void {
  let event = "message";
  const dataLines: string[] = [];
  for (const line of frame.split(/\r?\n/)) {
    if (line.startsWith("event:")) {
      event = line.slice(6).trim();
    } else if (line.startsWith("data:")) {
      const data = line.slice(5);
      dataLines.push(data.startsWith(" ") ? data.slice(1) : data);
    }
  }
  if (dataLines.length === 0) {
    return;
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(dataLines.join("\n"));
  } catch {
    parsed = {};
  }
  if (!parsed || typeof parsed !== "object") {
    return;
  }
  const payload = parsed as Record<string, unknown>;

  if (event === "delta" && typeof payload.delta === "string") {
    handlers.delta?.(payload.delta);
  } else if (event === "evidence" && Array.isArray(payload.evidence_refs)) {
    handlers.evidence?.(payload.evidence_refs as EvidenceRef[]);
  } else if (event === "done" && typeof payload.message === "string") {
    handlers.done?.(payload.message);
  } else if (event === "error" && typeof payload.message === "string") {
    handlers.error?.(payload.message);
  }
}
