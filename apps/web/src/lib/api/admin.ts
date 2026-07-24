import {
  API_BASE_URL,
  ApiError,
  errorMessage,
  parseResponse,
  request,
  withQuery,
} from "./http";

import type {
  AdminAuditLogListResponse,
  AdminCaseGroupAccess,
  AdminCaseGroupAccessListResponse,
  AdminPolicyGroup,
  AdminPolicyGroupListResponse,
  AdminPolicyGroupMember,
  AdminPolicyGroupMemberListResponse,
  AdminSettingsResponse,
  AdminUser,
  AdminUserListResponse,
  RetentionRunResponse,
} from "../api";

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
