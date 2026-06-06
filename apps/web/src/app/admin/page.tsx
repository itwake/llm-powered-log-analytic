"use client";

import { useEffect, useState } from "react";
import {
  AdminAuditLog,
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
  const [auditLogs, setAuditLogs] = useState<AdminAuditLog[]>([]);
  const [retention, setRetention] = useState<RetentionRunResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [savingUserId, setSavingUserId] = useState<string | null>(null);
  const [runningRetention, setRunningRetention] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [settingsResponse, usersResponse, auditResponse] = await Promise.all([
        adminApi.settings(),
        adminApi.users({limit: 100}),
        adminApi.auditLogs({limit: 50}),
      ]);
      setSettings(settingsResponse);
      setUsers(usersResponse.items);
      setAuditLogs(auditResponse.items);
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
                  <tr><td>Retention days</td><td>{JSON.stringify(settings.retention_days)}</td></tr>
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
            <section className="grid five">
              <Metric label="Audits deleted" value={retentionValue(retention, "audit_logs_deleted")} />
              <Metric label="Raw lines scrubbed" value={retentionValue(retention, "raw_log_lines_scrubbed")} />
              <Metric label="Exports deleted" value={retentionValue(retention, "exports_deleted")} />
              <Metric label="Results cleared" value={retentionValue(retention, "analysis_results_cleared")} />
              <Metric label="Step artifacts deleted" value={retentionValue(retention, "step_artifacts_deleted")} />
            </section>
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
                    <th>Copilot</th>
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
                      <td>{user.has_copilot_credential ? "connected" : "not connected"}</td>
                      <td>{formatDateTime(user.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section className="panel" style={{marginTop: 14}}>
            <h2>Audit Logs</h2>
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
