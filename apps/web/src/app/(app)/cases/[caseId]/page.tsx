"use client";

import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Chip from "@mui/material/Chip";
import LinearProgress from "@mui/material/LinearProgress";
import List from "@mui/material/List";
import ListItemButton from "@mui/material/ListItemButton";
import ListItemText from "@mui/material/ListItemText";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import Link from "@/components/Link";
import { BACKGROUND_ANALYSIS_CONFIG } from "@/lib/analysisConfig";
import {
  AnalysisRunResponse,
  CaseResponse,
  EvidenceRef,
  JobEventResponse,
  UploadProgressEvent,
  casesApi,
  runsApi,
} from "@/lib/api";
import { apiErrorMessage, formatDateTime, valueLabel } from "@/lib/format";
import { CaseAnalysisNav } from "@/components/CaseAnalysisNav";
import { CaseRunInspector } from "@/components/CaseRunInspector";
import { ChatWorkspace } from "@/components/ChatWorkspace";
import { FileUploadDropzone } from "@/components/FileUploadDropzone";
import { Badge, Button, Card, EmptyState, SectionHeader, statusTone } from "@/components/ui";

type UploadItemStatus = "queued" | "preparing" | "hashing" | "uploading" | "verifying" | "completed" | "failed";

interface UploadItem {
  key: string;
  name: string;
  size: number;
  status: UploadItemStatus;
  bytesSent: number;
  fileId?: string;
  partNumber?: number;
  partCount?: number;
  message?: string;
}

function uploadKey(file: File, index: number): string {
  return `${index}:${file.name}:${file.size}:${file.lastModified}`;
}

function uploadItemsFromFiles(files: File[]): UploadItem[] {
  return files.map((file, index) => ({
    key: uploadKey(file, index),
    name: file.name || "upload.bin",
    size: file.size,
    status: "queued",
    bytesSent: 0,
  }));
}

function formatBytes(value: number): string {
  if (value < 1024) {
    return `${value} B`;
  }
  if (value < 1024 * 1024) {
    return `${(value / 1024).toFixed(1)} KB`;
  }
  if (value < 1024 * 1024 * 1024) {
    return `${(value / (1024 * 1024)).toFixed(1)} MB`;
  }
  return `${(value / (1024 * 1024 * 1024)).toFixed(1)} GB`;
}

function uploadPercent(item: UploadItem): number {
  if (item.status === "completed") {
    return 100;
  }
  if (item.size <= 0) {
    return item.bytesSent > 0 ? 100 : 0;
  }
  return Math.max(0, Math.min(100, Math.round((item.bytesSent / item.size) * 100)));
}

function terminalRunStatus(status: string): boolean {
  return status === "completed" || status === "failed" || status === "cancelled";
}

function emptyToNull(value: string): string | null {
  return value.trim() ? value.trim() : null;
}

function localDateTimeToIso(value: string): string | null {
  if (!value) {
    return null;
  }
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

function isoToLocalDateTime(value: string | null): string {
  if (!value) {
    return "";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  const offsetMs = date.getTimezoneOffset() * 60 * 1000;
  return new Date(date.getTime() - offsetMs).toISOString().slice(0, 16);
}

export default function CaseWorkspacePage() {
  const { caseId } = useParams<{ caseId: string }>();
  const router = useRouter();
  const [caseRecord, setCaseRecord] = useState<CaseResponse | null>(null);
  const [runs, setRuns] = useState<AnalysisRunResponse[]>([]);
  const [runEvents, setRunEvents] = useState<Record<string, JobEventResponse[]>>({});
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [uploadItems, setUploadItems] = useState<UploadItem[]>([]);
  const [selectedEvidence, setSelectedEvidence] = useState<EvidenceRef | null>(null);
  const [loading, setLoading] = useState(true);
  const [starting, setStarting] = useState<"files" | "sample" | null>(null);
  const [editingCase, setEditingCase] = useState(false);
  const [savingCase, setSavingCase] = useState(false);
  const [deletingCase, setDeletingCase] = useState(false);
  const [cancellingRunId, setCancellingRunId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [caseTitle, setCaseTitle] = useState("");
  const [caseIssueDescription, setCaseIssueDescription] = useState("");
  const [caseProduct, setCaseProduct] = useState("");
  const [caseService, setCaseService] = useState("");
  const [caseEnvironment, setCaseEnvironment] = useState("");
  const [caseIncidentStart, setCaseIncidentStart] = useState("");
  const [caseIncidentEnd, setCaseIncidentEnd] = useState("");

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [caseResponse, runResponse] = await Promise.all([
        casesApi.get(caseId),
        runsApi.list(caseId),
      ]);
      setCaseRecord(caseResponse);
      setRuns(runResponse.items);
      if (runResponse.items[0]) {
        setActiveRunId((current) => current || runResponse.items[0].analysis_run_id);
      }
    } catch (caught) {
      setError(apiErrorMessage(caught));
    } finally {
      setLoading(false);
    }
  }

  function upsertRun(run: AnalysisRunResponse) {
    setRuns((current) => {
      const existing = current.findIndex((item) => item.analysis_run_id === run.analysis_run_id);
      const next = existing >= 0 ? [...current] : [run, ...current];
      if (existing >= 0) {
        next[existing] = run;
      }
      return next.sort((left, right) => right.run_number - left.run_number);
    });
  }

  async function refreshRunProgress(runId: string) {
    const [run, events] = await Promise.all([
      runsApi.get(caseId, runId),
      runsApi.events(caseId, runId),
    ]);
    upsertRun(run);
    setRunEvents((current) => ({ ...current, [runId]: events.items }));
    return run;
  }

  function handleUploadProgress(event: UploadProgressEvent) {
    setUploadItems((current) => {
      const key = uploadKey(event.file, event.fileIndex);
      const existing = current.findIndex((item) => item.key === key);
      const nextItem: UploadItem = {
        key,
        name: event.file.name || "upload.bin",
        size: event.totalBytes,
        status: event.phase,
        bytesSent: Math.min(event.bytesSent, event.totalBytes),
        fileId: event.fileId,
        partNumber: event.partNumber,
        partCount: event.partCount,
        message: event.message,
      };
      if (existing < 0) {
        return [...current, nextItem];
      }
      const next = [...current];
      next[existing] = { ...next[existing], ...nextItem };
      return next;
    });
  }

  useEffect(() => {
    void load();
  }, [caseId]);

  useEffect(() => {
    if (!caseRecord) {
      return;
    }
    setCaseTitle(caseRecord.title || "");
    setCaseIssueDescription(caseRecord.issue_description || "");
    setCaseProduct(caseRecord.product || "");
    setCaseService(caseRecord.service || "");
    setCaseEnvironment(caseRecord.environment || "");
    setCaseIncidentStart(isoToLocalDateTime(caseRecord.incident_start));
    setCaseIncidentEnd(isoToLocalDateTime(caseRecord.incident_end));
  }, [caseRecord]);

  const latestRun = runs[0] || null;
  const trackedRun = runs.find((run) => run.analysis_run_id === activeRunId) || latestRun;

  useEffect(() => {
    if (!trackedRun) {
      return;
    }
    let cancelled = false;
    const runId = trackedRun.analysis_run_id;
    async function refresh() {
      try {
        await refreshRunProgress(runId);
      } catch {
        if (!cancelled) {
          setRunEvents((current) => ({ ...current, [runId]: current[runId] || [] }));
        }
      }
    }
    void refresh();
    if (terminalRunStatus(trackedRun.status)) {
      return () => {
        cancelled = true;
      };
    }
    const timer = window.setInterval(() => {
      void refresh();
    }, 2000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [caseId, trackedRun?.analysis_run_id, trackedRun?.status]);

  function handleFileSelection(files: File[]) {
    setSelectedFiles(files);
    setUploadItems(uploadItemsFromFiles(files));
  }

  async function startUploadedAnalysis() {
    if (selectedFiles.length === 0) {
      setError("Select at least one log or archive file to upload.");
      return;
    }
    setStarting("files");
    setError(null);
    setUploadItems(uploadItemsFromFiles(selectedFiles));
    try {
      const uploaded = await casesApi.uploadFiles(caseId, selectedFiles, {
        onProgress: handleUploadProgress,
      });
      const run = await runsApi.start(caseId, {
        input_file_ids: uploaded.map((file) => file.file_id),
        config: BACKGROUND_ANALYSIS_CONFIG,
      }, { background: true });
      setActiveRunId(run.analysis_run_id);
      await refreshRunProgress(run.analysis_run_id);
    } catch (caught) {
      setUploadItems((current) =>
        current.map((item) =>
          item.status === "completed" ? item : { ...item, status: "failed", message: apiErrorMessage(caught) },
        ),
      );
      setError(apiErrorMessage(caught));
    } finally {
      setStarting(null);
    }
  }

  async function startSampleAnalysis() {
    setStarting("sample");
    setError(null);
    try {
      const run = await runsApi.start(caseId, {
        input_paths: [],
        config: BACKGROUND_ANALYSIS_CONFIG,
      }, { background: true });
      setActiveRunId(run.analysis_run_id);
      await refreshRunProgress(run.analysis_run_id);
    } catch (caught) {
      setError(apiErrorMessage(caught));
    } finally {
      setStarting(null);
    }
  }

  async function saveCase() {
    setSavingCase(true);
    setError(null);
    try {
      const updated = await casesApi.update(caseId, {
        title: caseTitle,
        issue_description: emptyToNull(caseIssueDescription),
        product: emptyToNull(caseProduct),
        service: emptyToNull(caseService),
        environment: emptyToNull(caseEnvironment),
        incident_start: localDateTimeToIso(caseIncidentStart),
        incident_end: localDateTimeToIso(caseIncidentEnd),
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
      });
      setCaseRecord(updated);
      window.dispatchEvent(new CustomEvent("logan:case-saved", { detail: updated }));
      setEditingCase(false);
    } catch (caught) {
      setError(apiErrorMessage(caught));
    } finally {
      setSavingCase(false);
    }
  }

  async function deleteCase() {
    if (!window.confirm("Delete this case?")) {
      return;
    }
    setDeletingCase(true);
    setError(null);
    try {
      await casesApi.remove(caseId);
      window.dispatchEvent(new CustomEvent("logan:case-deleted", { detail: { caseId } }));
      router.push("/cases");
    } catch (caught) {
      setError(apiErrorMessage(caught));
      setDeletingCase(false);
    }
  }

  async function cancelRun(run: AnalysisRunResponse) {
    setCancellingRunId(run.analysis_run_id);
    setError(null);
    try {
      const cancelled = await runsApi.cancel(caseId, run.analysis_run_id);
      upsertRun(cancelled);
      await refreshRunProgress(run.analysis_run_id);
    } catch (caught) {
      setError(apiErrorMessage(caught));
    } finally {
      setCancellingRunId(null);
    }
  }

  const trackedEvents = trackedRun ? runEvents[trackedRun.analysis_run_id] || [] : [];

  return (
    <Stack spacing={2.5}>
      {error && <Alert severity="error">{error}</Alert>}
      {loading && <Card><EmptyState title="Loading case" /></Card>}

      {!loading && caseRecord && (
        <>
          {latestRun && (
            <CaseAnalysisNav
              caseId={caseId}
              runId={latestRun.analysis_run_id}
            />
          )}

          <Box sx={{ display: "grid", gap: 2.5, gridTemplateColumns: { xs: "1fr", xl: "minmax(0, 1.45fr) minmax(380px, 0.75fr)" } }}>
            <Stack spacing={2.5}>
            <Card
              sx={{
                background:
                  "linear-gradient(135deg, rgba(255,255,255,0.96), rgba(217,236,255,0.72))",
                overflow: "hidden",
              }}
            >
              <Stack direction={{ xs: "column", lg: "row" }} spacing={2.5} sx={{ alignItems: { xs: "flex-start", lg: "center" }, justifyContent: "space-between" }}>
                <Stack spacing={1.5} sx={{ minWidth: 0 }}>
                  <Typography color="primary" sx={{ fontWeight: 900, letterSpacing: 0.5, textTransform: "uppercase" }} variant="caption">
                    Incident Overview
                  </Typography>
                  <Stack direction="row" sx={{ flexWrap: "wrap", gap: 1 }}>
                    <Typography color="text.secondary" sx={{ fontWeight: 800 }} variant="caption">
                      {caseRecord.case_key}
                    </Typography>
                    <Badge tone={statusTone(caseRecord.status)}>{caseRecord.status}</Badge>
                    {latestRun && <Badge tone={statusTone(latestRun.status)}>{latestRun.status}</Badge>}
                  </Stack>
                  <Typography component="h1" sx={{ fontWeight: 850, overflowWrap: "anywhere" }} variant="h4">
                    {valueLabel(caseRecord.title)}
                  </Typography>
                  <Typography color="text.secondary" sx={{ overflowWrap: "anywhere" }}>
                    {valueLabel(caseRecord.issue_description)}
                  </Typography>
                  <Stack direction="row" sx={{ flexWrap: "wrap", gap: 1 }}>
                    {caseRecord.product && <Chip label={caseRecord.product} variant="outlined" />}
                    {caseRecord.service && <Chip label={caseRecord.service} variant="outlined" />}
                    {caseRecord.environment && <Chip label={caseRecord.environment} variant="outlined" />}
                    {caseRecord.incident_start && <Chip label={formatDateTime(caseRecord.incident_start)} variant="outlined" />}
                    {!caseRecord.product && !caseRecord.service && !caseRecord.environment && !caseRecord.incident_start && (
                      <Chip label="Metadata not set" variant="outlined" />
                    )}
                  </Stack>
                </Stack>
                <Stack direction={{ xs: "column", sm: "row" }} spacing={1} sx={{ alignItems: { sm: "center" }, flexShrink: 0, justifyContent: { lg: "flex-end" }, width: { xs: "100%", sm: "auto" } }}>
                  {latestRun?.status === "completed" && (
                    <Button component={Link} href={`/cases/${caseId}/runs/${latestRun.analysis_run_id}/summary`}>
                      Open latest report
                    </Button>
                  )}
                  <Button disabled={savingCase || deletingCase} variant="secondary" onClick={() => setEditingCase((current) => !current)}>
                    {editingCase ? "Close edit" : "Edit case"}
                  </Button>
                </Stack>
              </Stack>
            </Card>

            {editingCase && (
              <Card>
                <Stack spacing={2.5}>
                  <SectionHeader eyebrow="Case" title="Edit Case" />
                  <Box sx={{ display: "grid", gap: 2, gridTemplateColumns: { xs: "1fr", md: "repeat(2, minmax(0, 1fr))" } }}>
                    <TextField required label="Title" value={caseTitle} onChange={(event) => setCaseTitle(event.target.value)} />
                    <TextField label="Product" value={caseProduct} onChange={(event) => setCaseProduct(event.target.value)} />
                    <TextField label="Service" value={caseService} onChange={(event) => setCaseService(event.target.value)} />
                    <TextField label="Environment" value={caseEnvironment} onChange={(event) => setCaseEnvironment(event.target.value)} />
                    <TextField
                      label="Incident start"
                      slotProps={{ inputLabel: { shrink: true } }}
                      type="datetime-local"
                      value={caseIncidentStart}
                      onChange={(event) => setCaseIncidentStart(event.target.value)}
                    />
                    <TextField
                      label="Incident end"
                      slotProps={{ inputLabel: { shrink: true } }}
                      type="datetime-local"
                      value={caseIncidentEnd}
                      onChange={(event) => setCaseIncidentEnd(event.target.value)}
                    />
                  </Box>
                  <TextField
                    label="Issue description"
                    minRows={4}
                    multiline
                    value={caseIssueDescription}
                    onChange={(event) => setCaseIssueDescription(event.target.value)}
                  />
                  <Stack
                    direction={{ xs: "column", sm: "row" }}
                    spacing={1.5}
                    sx={{ alignItems: { sm: "center" }, justifyContent: "space-between" }}
                  >
                    <Stack direction="row" spacing={1.5}>
                      <Button disabled={savingCase || !caseTitle.trim()} onClick={() => void saveCase()}>
                        {savingCase ? "Saving" : "Save case"}
                      </Button>
                      <Button variant="secondary" onClick={() => setEditingCase(false)}>
                        Cancel
                      </Button>
                    </Stack>
                    <Button
                      disabled={deletingCase}
                      sx={{
                        bgcolor: "transparent",
                        color: "error.main",
                        "&:hover": { bgcolor: "rgba(211,47,47,0.08)" },
                      }}
                      variant="ghost"
                      onClick={() => void deleteCase()}
                    >
                      {deletingCase ? "Deleting" : "Delete case"}
                    </Button>
                  </Stack>
                </Stack>
              </Card>
            )}

            <ChatWorkspace
              caseId={caseId}
              run={latestRun}
              onEvidenceSelect={setSelectedEvidence}
            />

            <Card sx={{ background: "linear-gradient(180deg, #ffffff, rgba(217,236,255,0.32))" }}>
              <Stack spacing={2}>
                <SectionHeader eyebrow="Run" title="Analyze evidence" />
                <FileUploadDropzone
                  accept=".log,.txt,.json,.jsonl,.zip,.gz,.tar,.tgz"
                  description="Select logs or archives to upload into this incident run."
                  files={selectedFiles}
                  onFilesSelected={handleFileSelection}
                />
                {selectedFiles.length > 0 && (
                  <Stack direction="row" sx={{ flexWrap: "wrap", gap: 1 }}>
                    {selectedFiles.map((file, index) => (
                      <Chip key={uploadKey(file, index)} label={`${file.name || "upload.bin"} - ${formatBytes(file.size)}`} />
                    ))}
                  </Stack>
                )}
                {uploadItems.length > 0 && (
                  <Stack spacing={1.5}>
                    {uploadItems.map((item) => {
                      const percent = uploadPercent(item);
                      return (
                        <Box key={item.key} sx={{ bgcolor: "background.paper", border: 1, borderColor: "rgba(91,92,246,0.12)", borderRadius: "10px", p: 1.5 }}>
                          <Stack direction="row" spacing={1} sx={{ alignItems: "center", justifyContent: "space-between" }}>
                            <Typography sx={{ fontWeight: 800, overflowWrap: "anywhere" }}>{item.name}</Typography>
                            <Badge tone={statusTone(item.status)}>{item.status}</Badge>
                          </Stack>
                          <LinearProgress aria-label={`${item.name} upload progress`} sx={{ borderRadius: "999px", my: 1, height: 8 }} value={percent} variant="determinate" />
                          <Stack direction="row" sx={{ color: "text.secondary", flexWrap: "wrap", gap: 1.5 }}>
                            <Typography variant="caption">{percent}%</Typography>
                            <Typography variant="caption">{formatBytes(item.bytesSent)} / {formatBytes(item.size)}</Typography>
                            {item.partNumber && item.partCount && (
                              <Typography variant="caption">part {item.partNumber}/{item.partCount}</Typography>
                            )}
                            {item.message && <Typography variant="caption">{item.message}</Typography>}
                          </Stack>
                        </Box>
                      );
                    })}
                  </Stack>
                )}
                <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5}>
                  <Button disabled={starting !== null || selectedFiles.length === 0} onClick={startUploadedAnalysis}>
                    {starting === "files" ? "Uploading" : "Upload and analyze files"}
                  </Button>
                  <Button disabled={starting !== null} variant="secondary" onClick={startSampleAnalysis}>
                    {starting === "sample" ? "Starting" : "Start sample/local analysis"}
                  </Button>
                </Stack>
                <Typography color="text.secondary">
                  Uploaded files run through the local object store. The sample/local action uses the
                  deterministic fixture set.
                </Typography>
              </Stack>
            </Card>
          </Stack>

          <Box component="aside" sx={{ alignSelf: "start", position: { xl: "sticky" }, top: { xl: 88 } }}>
            <Stack spacing={2}>
              <CaseRunInspector
                cancelling={trackedRun?.analysis_run_id === cancellingRunId}
                caseId={caseId}
                caseRecord={caseRecord}
                events={trackedEvents}
                run={trackedRun}
                selectedEvidence={selectedEvidence}
                onCancel={(run) => void cancelRun(run)}
              />
              <Card>
                <Stack spacing={2}>
                  <SectionHeader eyebrow="History" title="Analysis Runs" />
                  {runs.length === 0 && <EmptyState title="No analysis runs" />}
                  {runs.length > 0 && (
                    <List disablePadding sx={{ display: "grid", gap: 1 }}>
                      {runs.map((run) => {
                        const active = run.analysis_run_id === trackedRun?.analysis_run_id;
                        return (
                          <Box
                            key={run.analysis_run_id}
                            sx={{
                              bgcolor: active ? "rgba(91,92,246,0.08)" : "background.paper",
                              border: 1,
                              borderColor: active ? "primary.main" : "rgba(91,92,246,0.12)",
                              borderRadius: "10px",
                              overflow: "hidden",
                            }}
                          >
                            <ListItemButton selected={active} onClick={() => setActiveRunId(run.analysis_run_id)}>
                              <ListItemText
                                primary={
                                  <Typography sx={{ fontWeight: 850 }}>
                                    Run #{run.run_number}
                                  </Typography>
                                }
                                secondary={`${run.current_step} - ${formatDateTime(run.started_at)}`}
                              />
                              <Badge tone={statusTone(run.status)}>{run.status}</Badge>
                            </ListItemButton>
                            <Stack direction="row" sx={{ flexWrap: "wrap", gap: 1, px: 2, pb: 1.5 }}>
                              {run.status === "completed" && (
                                <Button component={Link} href={`/cases/${caseId}/runs/${run.analysis_run_id}/summary`} size="sm" variant="secondary">
                                  Summary
                                </Button>
                              )}
                              {!terminalRunStatus(run.status) && (
                                <Button disabled={cancellingRunId === run.analysis_run_id} size="sm" variant="danger" onClick={() => void cancelRun(run)}>
                                  {cancellingRunId === run.analysis_run_id ? "Stopping" : "Terminate"}
                                </Button>
                              )}
                            </Stack>
                          </Box>
                        );
                      })}
                    </List>
                  )}
                </Stack>
              </Card>
            </Stack>
          </Box>
          </Box>
        </>
      )}
    </Stack>
  );
}
