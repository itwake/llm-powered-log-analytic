"use client";

import { useEffect, useState } from "react";
import {
  AdminAuditLog,
  AdminPolicyGroup,
  AdminSettingsResponse,
  AdminUser,
  RetentionRunResponse,
  adminApi,
} from "@/lib/api";
import { apiErrorMessage, formatDateTime, valueLabel } from "@/lib/format";
import { Metric, Shell } from "@/components/Shell";

function retentionValue(result: RetentionRunResponse | null, key: keyof RetentionRunResponse): string {
  return result ? String(result[key]) : "n/a";
}

function metadataPreview(log: AdminAuditLog): string {
  const value = JSON.stringify(log.metadata || {});
  return value.length > 180 ? `${value.slice(0, 177)}...` : value;
}

export default function AdminPage() {
  const [settings, setSettings] = useState<AdminSettingsResponse | null>(null);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [policyGroups, setPolicyGroups] = useState<AdminPolicyGroup[]>([]);
  const [auditLogs, setAuditLogs] = useState<AdminAuditLog[]>([]);
  const [retention, setRetention] = useState<RetentionRunResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [savingUserId, setSavingUserId] = useState<string | null>(null);
  const [runningRetention, setRunningRetention] = useState(false);
  const [creatingGroup, setCreatingGroup] = useState(false);
  const [newGroupName, setNewGroupName] = useState("");
  const [auditExportFormat, setAuditExportFormat] = useState<"json" | "ndjson" | "csv">("json");
  const [exportingAudit, setExportingAudit] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [settingsResponse, usersResponse, auditResponse, groupsResponse] = await Promise.all([
        adminApi.settings(),
        adminApi.users({limit: 100}),
        adminApi.auditLogs({limit: 50}),
        adminApi.policyGroups(),
      ]);
      setSettings(settingsResponse);
      setUsers(usersResponse.items);
      setAuditLogs(auditResponse.items);
      setPolicyGroups(groupsResponse.items);
    } catch (caught) {
      setError(apiErrorMessage(caught));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function updateRole(user: AdminUser, role: string) {
    setSavingUserId(user.id);
    setError(null);
    setNotice(null);
    try {
      const updated = await adminApi.updateUser(user.id, {role});
      setUsers((current) => current.map((item) => (item.id === updated.id ? updated : item)));
      setNotice("User updated");
      void refreshAuditLogs();
    } catch (caught) {
      setError(apiErrorMessage(caught));
    } finally {
      setSavingUserId(null);
    }
  }

  async function updateActive(user: AdminUser, isActive: boolean) {
    setSavingUserId(user.id);
    setError(null);
    setNotice(null);
    try {
      const updated = await adminApi.updateUser(user.id, {is_active: isActive});
      setUsers((current) => current.map((item) => (item.id === updated.id ? updated : item)));
      setNotice("User updated");
      void refreshAuditLogs();
    } catch (caught) {
      setError(apiErrorMessage(caught));
    } finally {
      setSavingUserId(null);
    }
  }

  async function refreshAuditLogs() {
    const auditResponse = await adminApi.auditLogs({limit: 50});
    setAuditLogs(auditResponse.items);
  }

  async function runRetention() {
    setRunningRetention(true);
    setError(null);
    setNotice(null);
    try {
      const result = await adminApi.runRetention();
      setRetention(result);
      setNotice("Retention run completed");
      void refreshAuditLogs();
    } catch (caught) {
      setError(apiErrorMessage(caught));
    } finally {
      setRunningRetention(false);
    }
  }

  async function createPolicyGroup() {
    const name = newGroupName.trim();
    if (!name) {
      return;
    }
    setCreatingGroup(true);
    setError(null);
    setNotice(null);
    try {
      const group = await adminApi.createPolicyGroup({name});
      setPolicyGroups((current) => [...current, group].sort((left, right) => left.name.localeCompare(right.name)));
      setNewGroupName("");
      setNotice("Policy group created");
      void refreshAuditLogs();
    } catch (caught) {
      setError(apiErrorMessage(caught));
    } finally {
      setCreatingGroup(false);
    }
  }

  async function exportAuditLogs() {
    setExportingAudit(true);
    setError(null);
    setNotice(null);
    try {
      const content = await adminApi.exportAuditLogs({format: auditExportFormat, limit: 1000});
      const blob = new Blob([content], {
        type: auditExportFormat === "csv" ? "text/csv" : "application/octet-stream",
      });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `logan-audit.${auditExportFormat}`;
      link.click();
      URL.revokeObjectURL(url);
      setNotice("Audit export ready");
      void refreshAuditLogs();
    } catch (caught) {
      setError(apiErrorMessage(caught));
    } finally {
      setExportingAudit(false);
    }
  }

  return (
    <Shell caseTitle="Admin">
      <div className="toolbar">
        <h1>Admin</h1>
        <button className="button secondary" disabled={loading} type="button" onClick={() => void load()}>
          Refresh
        </button>
      </div>

      {error && <div className="alert error">{error}</div>}
      {notice && <div className="alert success">{notice}</div>}
      {loading && <section className="panel"><div className="empty">Loading admin data</div></section>}

      {!loading && settings && (
        <>
          <section className="grid three">
            <Metric label="Environment" value={settings.env} />
            <Metric label="Store" value={settings.store_backend} />
            <Metric label="Object backend" value={settings.object_backend} />
          </section>

          <section className="panel" style={{marginTop: 14}}>
            <h2>Settings</h2>
            <div className="table-wrap">
              <table>
                <tbody>
                  <tr><td>Configured store</td><td>{settings.configured_store_backend}</td></tr>
                  <tr><td>Orchestrator</td><td>{settings.orchestrator}</td></tr>
                  <tr><td>Rate limit</td><td>{settings.rate_limit.enabled ? `${settings.rate_limit.requests_per_minute}/min` : "disabled"}</td></tr>
                  <tr><td>Analytics</td><td>{JSON.stringify(settings.analytics)}</td></tr>
                </tbody>
              </table>
            </div>
          </section>

          <section className="panel" style={{marginTop: 14}}>
            <div className="toolbar">
              <h2>Retention</h2>
              <button
                className="button"
                disabled={runningRetention}
                type="button"
                onClick={() => void runRetention()}
              >
                {runningRetention ? "Running" : "Run retention"}
              </button>
            </div>
            <section className="grid two">
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Policy</th>
                      <th>Days</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr><td>Audit</td><td>{settings.retention_days.audit}</td></tr>
                    <tr><td>Raw logs</td><td>{settings.retention_days.raw_log}</td></tr>
                    <tr><td>Reports</td><td>{settings.retention_days.report}</td></tr>
                  </tbody>
                </table>
              </div>
              <section className="grid three">
                <Metric label="Audits deleted" value={retentionValue(retention, "audit_logs_deleted")} />
                <Metric label="Raw lines scrubbed" value={retentionValue(retention, "raw_log_lines_scrubbed")} />
                <Metric label="Exports deleted" value={retentionValue(retention, "exports_deleted")} />
                <Metric label="Results cleared" value={retentionValue(retention, "analysis_results_cleared")} />
                <Metric label="Step artifacts deleted" value={retentionValue(retention, "step_artifacts_deleted")} />
              </section>
            </section>
          </section>

          <section className="panel" style={{marginTop: 14}}>
            <div className="toolbar">
              <h2>Policy Groups</h2>
              <input
                aria-label="Policy group name"
                disabled={creatingGroup}
                placeholder="Group name"
                value={newGroupName}
                onChange={(event) => setNewGroupName(event.target.value)}
              />
              <button
                className="button"
                disabled={creatingGroup || !newGroupName.trim()}
                type="button"
                onClick={() => void createPolicyGroup()}
              >
                {creatingGroup ? "Creating" : "Create group"}
              </button>
            </div>
            {policyGroups.length === 0 && <div className="empty">No policy groups</div>}
            {policyGroups.length > 0 && (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Name</th>
                      <th>Slug</th>
                      <th>Members</th>
                      <th>Updated</th>
                    </tr>
                  </thead>
                  <tbody>
                    {policyGroups.map((group) => (
                      <tr key={group.id}>
                        <td>
                          <strong>{group.name}</strong><br />
                          <span className="muted">{group.id}</span>
                        </td>
                        <td>{group.slug}</td>
                        <td>{group.member_count}</td>
                        <td>{formatDateTime(group.updated_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <section className="panel" style={{marginTop: 14}}>
            <h2>Users</h2>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>User</th>
                    <th>Role</th>
                    <th>Active</th>
                    <th>Created</th>
                  </tr>
                </thead>
                <tbody>
                  {users.map((user) => (
                    <tr key={user.id}>
                      <td>
                        <strong>{user.username}</strong><br />
                        <span className="muted">{user.email}</span>
                      </td>
                      <td>
                        <select
                          disabled={savingUserId === user.id}
                          value={user.role}
                          onChange={(event) => void updateRole(user, event.target.value)}
                        >
                          <option value="engineer">engineer</option>
                          <option value="admin">admin</option>
                        </select>
                      </td>
                      <td>
                        <label className="inline-field">
                          <input
                            checked={user.is_active}
                            disabled={savingUserId === user.id}
                            type="checkbox"
                            onChange={(event) => void updateActive(user, event.target.checked)}
                          />
                          {user.is_active ? "active" : "inactive"}
                        </label>
                      </td>
                      <td>{formatDateTime(user.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section className="panel" style={{marginTop: 14}}>
            <div className="toolbar">
              <h2>Audit Logs</h2>
              <select
                aria-label="Audit export format"
                disabled={exportingAudit}
                value={auditExportFormat}
                onChange={(event) => setAuditExportFormat(event.target.value as "json" | "ndjson" | "csv")}
              >
                <option value="json">json</option>
                <option value="ndjson">ndjson</option>
                <option value="csv">csv</option>
              </select>
              <button
                className="button secondary"
                disabled={exportingAudit}
                type="button"
                onClick={() => void exportAuditLogs()}
              >
                {exportingAudit ? "Exporting" : "Export"}
              </button>
            </div>
            {auditLogs.length === 0 && <div className="empty">No audit logs</div>}
            {auditLogs.length > 0 && (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Time</th>
                      <th>Action</th>
                      <th>User</th>
                      <th>Case</th>
                      <th>Target</th>
                      <th>Metadata</th>
                    </tr>
                  </thead>
                  <tbody>
                    {auditLogs.map((log) => (
                      <tr key={log.id}>
                        <td>{formatDateTime(log.created_at)}</td>
                        <td>{log.action}</td>
                        <td>{valueLabel(log.user_id)}</td>
                        <td>{valueLabel(log.case_id)}</td>
                        <td>{valueLabel(log.target_type)} {valueLabel(log.target_id)}</td>
                        <td><code>{metadataPreview(log)}</code></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      )}
    </Shell>
  );
}
