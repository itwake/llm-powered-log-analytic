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
  partNumber?: number;
  partCount?: number;
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
  multipart?: boolean;
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

async function sha256File(file: File): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function uploadPresignedFile(
  upload: UploadStartResponse,
  file: File,
  context: UploadProgressContext,
): Promise<void> {
  if (!upload.upload_url) {
    throw new Error("upload response did not include an upload URL");
  }
  const headers = new Headers(upload.upload_headers || {});
  await xhrUpload(upload.upload_url, file, {
    headers,
    onProgress: (loaded) => emitUploadProgress(context, file, {
      fileId: upload.file_id,
      phase: "uploading",
      bytesSent: loaded,
    }),
  });
}

async function uploadMultipartFile(
  upload: UploadStartResponse,
  file: File,
  context: UploadProgressContext,
): Promise<{sha256: string; parts: MultipartCompletePart[]}> {
  if (!upload.multipart_upload_id || !upload.part_size_bytes || !upload.parts?.length) {
    throw new Error("multipart upload response is incomplete");
  }
  const completedParts: MultipartCompletePart[] = [];
  const sortedParts = [...upload.parts].sort((left, right) => left.part_number - right.part_number);
  let completedBytes = 0;
  for (const part of sortedParts) {
    const start = (part.part_number - 1) * upload.part_size_bytes;
    const end = Math.min(start + upload.part_size_bytes, file.size);
    const chunk = file.slice(start, end);
    const xhr = await xhrUpload(part.upload_url, chunk, {
      headers: new Headers(part.upload_headers || {}),
      onProgress: (loaded) => emitUploadProgress(context, file, {
        fileId: upload.file_id,
        phase: "uploading",
        bytesSent: completedBytes + loaded,
        partNumber: part.part_number,
        partCount: sortedParts.length,
      }),
    });
    const etag = xhr.getResponseHeader("etag");
    if (!etag) {
      throw new Error(`multipart part ${part.part_number} did not return an ETag`);
    }
    completedParts.push({part_number: part.part_number, etag});
    completedBytes += chunk.size;
  }
  emitUploadProgress(context, file, {
    fileId: upload.file_id,
    phase: "hashing",
    bytesSent: file.size,
  });
  return {sha256: await sha256File(file), parts: completedParts};
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
    provider: string;
    default_model: string;
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
    if (upload.upload_mode === "multipart") {
      if (!upload.multipart_upload_id) {
        throw new Error("multipart upload response is missing an upload id");
      }
      const multipartUploadId = upload.multipart_upload_id;
      const completed = await uploadMultipartFile(upload, file, context);
      emitUploadProgress(context, file, {
        fileId: upload.file_id,
        phase: "verifying",
        bytesSent: file.size,
        message: "Completing multipart upload",
      });
      return casesApi.completeUpload(caseId, upload.file_id, completed.sha256, {
        multipart_upload_id: multipartUploadId,
        parts: completed.parts,
      });
    }
    if (upload.upload_backend === "s3" || upload.upload_backend === "minio") {
      emitUploadProgress(context, file, {
        fileId: upload.file_id,
        phase: "hashing",
        bytesSent: 0,
      });
      const sha256 = await sha256File(file);
      await uploadPresignedFile(upload, file, context);
      emitUploadProgress(context, file, {
        fileId: upload.file_id,
        phase: "verifying",
        bytesSent: file.size,
        message: "Verifying object storage upload",
      });
      return casesApi.completeUpload(caseId, upload.file_id, sha256);
    }
    if (!upload.upload_url) {
      throw new Error("upload response did not include an upload URL");
    }
    return uploadRawFile(upload.upload_url, file, context, upload.file_id);
  },
  uploadFiles: async (
    caseId: string,
    files: File[],
    options?: {
      multipart?: boolean;
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
        multipart: options?.multipart || null,
      });
      emitUploadProgress(context, file, {
        fileId: upload.file_id,
        phase: "uploading",
        bytesSent: 0,
      });
      const completed = await casesApi.uploadContent(caseId, upload, file, {
        ...context,
        multipart: options?.multipart,
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
