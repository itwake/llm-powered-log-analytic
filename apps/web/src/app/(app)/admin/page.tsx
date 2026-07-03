"use client";

import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Checkbox from "@mui/material/Checkbox";
import FormControl from "@mui/material/FormControl";
import InputLabel from "@mui/material/InputLabel";
import MenuItem from "@mui/material/MenuItem";
import Select from "@mui/material/Select";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { DataGrid, GridColDef } from "@mui/x-data-grid";
import { useEffect, useMemo, useState } from "react";
import {
  AdminAuditLog,
  AdminPolicyGroup,
  AdminSettingsResponse,
  AdminUser,
  RetentionRunResponse,
  adminApi,
} from "@/lib/api";
import { apiErrorMessage, formatDateTime, valueLabel } from "@/lib/format";
import { Metric } from "@/components/Shell";
import { Badge, Button, Card, EmptyState, InfoGrid } from "@/components/ui";

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
        adminApi.users({ limit: 100 }),
        adminApi.auditLogs({ limit: 50 }),
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
      const updated = await adminApi.updateUser(user.id, { role });
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
      const updated = await adminApi.updateUser(user.id, { is_active: isActive });
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
    const auditResponse = await adminApi.auditLogs({ limit: 50 });
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
      const group = await adminApi.createPolicyGroup({ name });
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
      const content = await adminApi.exportAuditLogs({ format: auditExportFormat, limit: 1000 });
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

  const policyColumns = useMemo<GridColDef<AdminPolicyGroup>[]>(
    () => [
      {
        field: "name",
        headerName: "Name",
        flex: 1,
        minWidth: 220,
        renderCell: (params) => (
          <Box sx={{ py: 1, whiteSpace: "normal", overflowWrap: "anywhere" }}>
            <Typography sx={{ fontWeight: 800 }}>{params.row.name}</Typography>
            <Typography color="text.secondary" variant="caption">{params.row.id}</Typography>
          </Box>
        ),
      },
      { field: "slug", headerName: "Slug", minWidth: 160 },
      { field: "member_count", headerName: "Members", minWidth: 120, type: "number" },
      {
        field: "updated_at",
        headerName: "Updated",
        minWidth: 170,
        renderCell: (params) => formatDateTime(params.row.updated_at),
      },
    ],
    [],
  );

  const userColumns = useMemo<GridColDef<AdminUser>[]>(
    () => [
      {
        field: "username",
        headerName: "User",
        flex: 1,
        minWidth: 260,
        renderCell: (params) => (
          <Box sx={{ py: 1, whiteSpace: "normal", overflowWrap: "anywhere" }}>
            <Typography sx={{ fontWeight: 800 }}>{params.row.username}</Typography>
            <Typography color="text.secondary" variant="caption">{params.row.email}</Typography>
          </Box>
        ),
      },
      {
        field: "role",
        headerName: "Role",
        minWidth: 170,
        sortable: false,
        renderCell: (params) => (
          <Select
            disabled={savingUserId === params.row.id}
            size="small"
            value={params.row.role}
            onChange={(event) => void updateRole(params.row, event.target.value)}
            onClick={(event) => event.stopPropagation()}
          >
            <MenuItem value="engineer">engineer</MenuItem>
            <MenuItem value="admin">admin</MenuItem>
          </Select>
        ),
      },
      {
        field: "is_active",
        headerName: "Active",
        minWidth: 140,
        sortable: false,
        renderCell: (params) => (
          <Stack direction="row" spacing={0.5} sx={{ alignItems: "center" }}>
            <Checkbox
              checked={params.row.is_active}
              disabled={savingUserId === params.row.id}
              onChange={(event) => void updateActive(params.row, event.target.checked)}
              onClick={(event) => event.stopPropagation()}
            />
            <Typography variant="body2">{params.row.is_active ? "active" : "inactive"}</Typography>
          </Stack>
        ),
      },
      {
        field: "created_at",
        headerName: "Created",
        minWidth: 170,
        renderCell: (params) => formatDateTime(params.row.created_at),
      },
    ],
    [savingUserId],
  );

  const auditColumns = useMemo<GridColDef<AdminAuditLog>[]>(
    () => [
      {
        field: "created_at",
        headerName: "Time",
        minWidth: 170,
        renderCell: (params) => formatDateTime(params.row.created_at),
      },
      {
        field: "action",
        headerName: "Action",
        minWidth: 180,
        renderCell: (params) => <Badge tone="info">{params.row.action}</Badge>,
      },
      {
        field: "user_id",
        headerName: "User",
        minWidth: 180,
        renderCell: (params) => valueLabel(params.row.user_id),
      },
      {
        field: "case_id",
        headerName: "Case",
        minWidth: 180,
        renderCell: (params) => valueLabel(params.row.case_id),
      },
      {
        field: "target",
        headerName: "Target",
        minWidth: 220,
        renderCell: (params) => `${valueLabel(params.row.target_type)} ${valueLabel(params.row.target_id)}`,
      },
      {
        field: "metadata",
        headerName: "Metadata",
        flex: 1,
        minWidth: 300,
        renderCell: (params) => (
          <Box component="code" sx={{ overflowWrap: "anywhere", whiteSpace: "normal" }}>
            {metadataPreview(params.row)}
          </Box>
        ),
      },
    ],
    [],
  );

  return (
    <Stack spacing={2.5}>
      <Stack direction={{ xs: "column", sm: "row" }} spacing={2} sx={{ alignItems: { xs: "flex-start", sm: "center" }, justifyContent: "space-between" }}>
        <Typography component="h1" sx={{ fontWeight: 850 }} variant="h4">
          Admin
        </Typography>
        <Button disabled={loading} type="button" variant="secondary" onClick={() => void load()}>
          Refresh
        </Button>
      </Stack>

      {error && <Alert severity="error">{error}</Alert>}
      {notice && <Alert severity="success">{notice}</Alert>}
      {loading && <Card><EmptyState title="Loading admin data" /></Card>}

      {!loading && settings && (
        <>
          <Box sx={{ display: "grid", gap: 2, gridTemplateColumns: { xs: "1fr", md: "repeat(3, minmax(0, 1fr))" } }}>
            <Metric label="Environment" value={settings.env} />
            <Metric label="Store" value={settings.store_backend} />
            <Metric label="Object backend" value={settings.object_backend} />
          </Box>

          <Card>
            <Typography component="h2" gutterBottom sx={{ fontWeight: 800 }} variant="h6">
              Settings
            </Typography>
            <InfoGrid
              rows={[
                { label: "Configured store", value: settings.configured_store_backend },
                { label: "Orchestrator", value: settings.orchestrator },
                {
                  label: "Rate limit",
                  value: settings.rate_limit.enabled ? `${settings.rate_limit.requests_per_minute}/min` : "disabled",
                },
                { label: "Analytics", value: JSON.stringify(settings.analytics) },
              ]}
            />
          </Card>

          <Card>
            <Stack spacing={2}>
              <Stack direction="row" spacing={2} sx={{ alignItems: "center", justifyContent: "space-between" }}>
                <Typography component="h2" sx={{ fontWeight: 800 }} variant="h6">
                  Retention
                </Typography>
                <Button disabled={runningRetention} type="button" onClick={() => void runRetention()}>
                  {runningRetention ? "Running" : "Run retention"}
                </Button>
              </Stack>
              <Box sx={{ display: "grid", gap: 2, gridTemplateColumns: { xs: "1fr", lg: "minmax(280px, 0.6fr) minmax(0, 1fr)" } }}>
                <InfoGrid
                  minColumnWidth={130}
                  rows={[
                    { label: "Audit", value: `${settings.retention_days.audit} days` },
                    { label: "Raw logs", value: `${settings.retention_days.raw_log} days` },
                    { label: "Reports", value: `${settings.retention_days.report} days` },
                  ]}
                />
                <Box sx={{ display: "grid", gap: 2, gridTemplateColumns: { xs: "1fr", sm: "repeat(2, minmax(0, 1fr))", xl: "repeat(3, minmax(0, 1fr))" } }}>
                  <Metric label="Audits deleted" value={retentionValue(retention, "audit_logs_deleted")} />
                  <Metric label="Raw lines scrubbed" value={retentionValue(retention, "raw_log_lines_scrubbed")} />
                  <Metric label="Exports deleted" value={retentionValue(retention, "exports_deleted")} />
                  <Metric label="Results cleared" value={retentionValue(retention, "analysis_results_cleared")} />
                  <Metric label="Step artifacts deleted" value={retentionValue(retention, "step_artifacts_deleted")} />
                </Box>
              </Box>
            </Stack>
          </Card>

          <Card>
            <Stack spacing={2}>
              <Stack direction={{ xs: "column", md: "row" }} spacing={2} sx={{ alignItems: { xs: "flex-start", md: "center" }, justifyContent: "space-between" }}>
                <Typography component="h2" sx={{ fontWeight: 800 }} variant="h6">
                  Policy Groups
                </Typography>
                <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} sx={{ width: { xs: "100%", md: "auto" } }}>
                  <TextField
                    aria-label="Policy group name"
                    disabled={creatingGroup}
                    placeholder="Group name"
                    value={newGroupName}
                    onChange={(event) => setNewGroupName(event.target.value)}
                  />
                  <Button disabled={creatingGroup || !newGroupName.trim()} type="button" onClick={() => void createPolicyGroup()}>
                    {creatingGroup ? "Creating" : "Create group"}
                  </Button>
                </Stack>
              </Stack>
              {policyGroups.length === 0 ? (
                <EmptyState title="No Data Found" />
              ) : (
                <Box sx={{ minHeight: 360 }}>
                  <DataGrid
                    columns={policyColumns}
                    density="compact"
                    disableRowSelectionOnClick
                    getRowHeight={() => "auto"}
                    getRowId={(row) => row.id}
                    initialState={{ pagination: { paginationModel: { pageSize: 25 } } }}
                    pageSizeOptions={[25, 50, 100]}
                    rows={policyGroups}
                    sx={{ "& .MuiDataGrid-cell": { alignItems: "flex-start", py: 1 } }}
                  />
                </Box>
              )}
            </Stack>
          </Card>

          <Card>
            <Stack spacing={2}>
              <Typography component="h2" sx={{ fontWeight: 800 }} variant="h6">
                Users
              </Typography>
              <Box sx={{ minHeight: 420 }}>
                <DataGrid
                  columns={userColumns}
                  density="compact"
                  disableRowSelectionOnClick
                  getRowHeight={() => "auto"}
                  getRowId={(row) => row.id}
                  initialState={{ pagination: { paginationModel: { pageSize: 25 } } }}
                  pageSizeOptions={[25, 50, 100]}
                  rows={users}
                  sx={{ "& .MuiDataGrid-cell": { alignItems: "flex-start", py: 1 } }}
                />
              </Box>
            </Stack>
          </Card>

          <Card>
            <Stack spacing={2}>
              <Stack direction={{ xs: "column", md: "row" }} spacing={2} sx={{ alignItems: { xs: "flex-start", md: "center" }, justifyContent: "space-between" }}>
                <Typography component="h2" sx={{ fontWeight: 800 }} variant="h6">
                  Audit Logs
                </Typography>
                <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5}>
                  <FormControl sx={{ minWidth: 160 }}>
                    <InputLabel id="audit-export-format-label">Audit export format</InputLabel>
                    <Select
                      disabled={exportingAudit}
                      label="Audit export format"
                      labelId="audit-export-format-label"
                      value={auditExportFormat}
                      onChange={(event) => setAuditExportFormat(event.target.value as "json" | "ndjson" | "csv")}
                    >
                      <MenuItem value="json">json</MenuItem>
                      <MenuItem value="ndjson">ndjson</MenuItem>
                      <MenuItem value="csv">csv</MenuItem>
                    </Select>
                  </FormControl>
                  <Button disabled={exportingAudit} type="button" variant="secondary" onClick={() => void exportAuditLogs()}>
                    {exportingAudit ? "Exporting" : "Export"}
                  </Button>
                </Stack>
              </Stack>
              {auditLogs.length === 0 ? (
                <EmptyState title="No Data Found" />
              ) : (
                <Box sx={{ minHeight: 520 }}>
                  <DataGrid
                    columns={auditColumns}
                    density="compact"
                    disableRowSelectionOnClick
                    getRowHeight={() => "auto"}
                    getRowId={(row) => row.id}
                    initialState={{ pagination: { paginationModel: { pageSize: 25 } } }}
                    pageSizeOptions={[25, 50, 100]}
                    rows={auditLogs}
                    sx={{ "& .MuiDataGrid-cell": { alignItems: "flex-start", py: 1 } }}
                  />
                </Box>
              )}
            </Stack>
          </Card>
        </>
      )}
    </Stack>
  );
}
