import {
  apiUrl,
  parseXhrPayload,
  request,
  xhrUpload,
} from "./api/http";

export {API_BASE_URL, ApiError} from "./api/http";

export type UploadProgressPhase =
  | "queued"
  | "preparing"
  | "hashing"
  | "uploading"
  | "verifying"
  | "completed"
  | "failed";

export interface UploadProgressEvent {
  file: File;
  fileId?: string;
  fileIndex: number;
  totalFiles: number;
  phase: UploadProgressPhase;
  bytesSent: number;
  totalBytes: number;
  message?: string;
}

export type UploadProgressCallback = (event: UploadProgressEvent) => void;

interface UploadProgressContext {
  fileIndex: number;
  totalFiles: number;
  onProgress?: UploadProgressCallback;
}

interface UploadContentOptions {
  fileIndex?: number;
  totalFiles?: number;
  onProgress?: UploadProgressCallback;
}

function emitUploadProgress(
  context: UploadProgressContext,
  file: File,
  event: Omit<UploadProgressEvent, "file" | "fileIndex" | "totalFiles" | "totalBytes"> & {
    totalBytes?: number;
  },
) {
  context.onProgress?.({
    file,
    fileIndex: context.fileIndex,
    totalFiles: context.totalFiles,
    totalBytes: event.totalBytes ?? file.size,
    ...event,
  });
}

async function uploadRawFile(
  uploadUrl: string,
  file: File,
  context: UploadProgressContext,
  fileId?: string,
): Promise<UploadContentResponse> {
  const headers = new Headers();
  if (file.type) {
    headers.set("content-type", file.type);
  }
  const xhr = await xhrUpload(apiUrl(uploadUrl), file, {
    headers,
    withCredentials: true,
    onProgress: (loaded) => emitUploadProgress(context, file, {
      fileId,
      phase: "uploading",
      bytesSent: loaded,
    }),
  });
  return parseXhrPayload(xhr) as UploadContentResponse;
}

export interface UserOut {
  id: string;
  organization_id: string;
  email: string;
  username: string;
  full_name: string | null;
  role: string;
  is_active: boolean;
}

export interface AuthUserResponse {
  user: UserOut;
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

export interface CaseUpdateRequest {
  title?: string;
  issue_description?: string | null;
  product?: string | null;
  service?: string | null;
  environment?: string | null;
  incident_start?: string | null;
  incident_end?: string | null;
  timezone?: string | null;
}

export interface CaseResponse {
  case_id: string;
  case_key: string;
  title: string | null;
  issue_description: string | null;
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
}

export interface UploadStartResponse {
  file_id: string;
  upload_url: string;
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

export interface JobEventResponse {
  id: string;
  case_id: string;
  analysis_run_id: string;
  step_name: string;
  event_type: string;
  status: string;
  attempt: number;
  idempotency_key: string;
  metadata: Record<string, unknown>;
  error_message: string | null;
  created_at: string;
}

export interface JobEventListResponse {
  items: JobEventResponse[];
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
    visible_templates?: number;
    annotated_templates?: number;
    scope?: "attention" | "all" | string;
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

export interface AdminUser {
  id: string;
  organization_id: string;
  email: string;
  username: string;
  full_name: string | null;
  role: "admin" | "engineer" | string;
  is_active: boolean;
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

export interface CapabilitiesResponse {
  models: {
    enabled: boolean;
    provider: string;
    default_model: string | null;
    supported_models: string[];
  };
  views: string[];
  upload: {
    max_file_size_bytes: number;
    supported_extensions: string[];
  };
}

export interface AdminSettingsResponse {
  env: string;
  retention_days: Record<string, number>;
  metrics_enabled: boolean;
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
  logout: () => request<{status: string}>("/api/auth/logout", {method: "POST"}),
};

export const casesApi = {
  list: (query?: {status?: string; product?: string; page?: number; page_size?: number}) =>
    request<CaseListResponse>("/api/cases", {query}),
  create: (payload: CaseCreateRequest) =>
    request<CaseResponse>("/api/cases", {method: "POST", body: payload}),
  get: (caseId: string) => request<CaseResponse>(`/api/cases/${caseId}`),
  update: (caseId: string, payload: CaseUpdateRequest) =>
    request<CaseResponse>(`/api/cases/${caseId}`, {method: "PATCH", body: payload}),
  remove: (caseId: string) =>
    request<{status: string; deleted: boolean}>(`/api/cases/${caseId}`, {method: "DELETE"}),
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
  uploadContent: async (
    caseId: string,
    upload: UploadStartResponse,
    file: File,
    options?: UploadContentOptions,
  ) => {
    const context: UploadProgressContext = {
      fileIndex: options?.fileIndex ?? 0,
      totalFiles: options?.totalFiles ?? 1,
      onProgress: options?.onProgress,
    };
    return uploadRawFile(upload.upload_url, file, context, upload.file_id);
  },
  uploadFiles: async (
    caseId: string,
    files: File[],
    options?: {
      onProgress?: UploadProgressCallback;
    },
  ) => {
    const uploaded: UploadContentResponse[] = [];
    for (const [index, file] of files.entries()) {
      const context: UploadProgressContext = {
        fileIndex: index,
        totalFiles: files.length,
        onProgress: options?.onProgress,
      };
      emitUploadProgress(context, file, {
        phase: "preparing",
        bytesSent: 0,
        message: "Preparing upload",
      });
      const upload = await casesApi.requestUpload(caseId, {
        filename: file.name || "upload.bin",
        content_type: file.type || null,
        size_bytes: file.size,
      });
      emitUploadProgress(context, file, {
        fileId: upload.file_id,
        phase: "uploading",
        bytesSent: 0,
      });
      const completed = await casesApi.uploadContent(caseId, upload, file, {
        ...context,
      });
      emitUploadProgress(context, file, {
        fileId: upload.file_id,
        phase: "completed",
        bytesSent: completed.size_bytes || file.size,
        message: "Upload complete",
      });
      uploaded.push(completed);
    }
    return uploaded;
  },
};

export {reportsApi, runsApi} from "./api/analysis";

export {chatApi} from "./api/chat";

export const capabilitiesApi = {
  get: () => request<CapabilitiesResponse>("/api/capabilities"),
};

export {adminApi} from "./api/admin";
