"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import {
  AnalysisRunResponse,
  CaseResponse,
  EvidenceRef,
  JobEventResponse,
  UploadProgressEvent,
  casesApi,
  chatApi,
  runsApi,
} from "@/lib/api";
import { apiErrorMessage, formatDateTime, valueLabel } from "@/lib/format";
import { AnalysisProgressPanel } from "@/components/AnalysisProgressPanel";
import { Metric, Shell } from "@/components/Shell";

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

function statusClass(status: string): string {
  if (status === "ready" || status === "completed") {
    return "green";
  }
  if (status === "failed") {
    return "red";
  }
  if (status === "processing" || status === "uploading") {
    return "amber";
  }
  return "blue";
}

function progressValue(run: AnalysisRunResponse | null, key: string): string {
  const value = run?.progress[key];
  return typeof value === "number" ? String(value) : "n/a";
}

function isAbortError(error: unknown): boolean {
  return error instanceof Error && error.name === "AbortError";
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
  return status === "completed" || status === "failed";
}

export default function CaseWorkspacePage() {
  const {caseId} = useParams<{caseId: string}>();
  const [caseRecord, setCaseRecord] = useState<CaseResponse | null>(null);
  const [runs, setRuns] = useState<AnalysisRunResponse[]>([]);
  const [runEvents, setRunEvents] = useState<Record<string, JobEventResponse[]>>({});
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [uploadItems, setUploadItems] = useState<UploadItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [starting, setStarting] = useState<"files" | "sample" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [askQuestion, setAskQuestion] = useState("");
  const [askAnswer, setAskAnswer] = useState("");
  const [askEvidenceRefs, setAskEvidenceRefs] = useState<EvidenceRef[]>([]);
  const [askStreaming, setAskStreaming] = useState(false);
  const [askError, setAskError] = useState<string | null>(null);
  const askAbortRef = useRef<AbortController | null>(null);

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
    setRunEvents((current) => ({...current, [runId]: events.items}));
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
      next[existing] = {...next[existing], ...nextItem};
      return next;
    });
  }

  useEffect(() => {
    void load();
  }, [caseId]);

  useEffect(() => () => {
    askAbortRef.current?.abort();
  }, []);

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
          setRunEvents((current) => ({...current, [runId]: current[runId] || []}));
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
        config: {default_window_size_seconds: 60},
      });
      setActiveRunId(run.analysis_run_id);
      await refreshRunProgress(run.analysis_run_id);
    } catch (caught) {
      setUploadItems((current) =>
        current.map((item) =>
          item.status === "completed" ? item : {...item, status: "failed", message: apiErrorMessage(caught)}
        )
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
        config: {default_window_size_seconds: 60},
      });
      setActiveRunId(run.analysis_run_id);
      await refreshRunProgress(run.analysis_run_id);
    } catch (caught) {
      setError(apiErrorMessage(caught));
    } finally {
      setStarting(null);
    }
  }

  async function askCopilot(latestRun: AnalysisRunResponse) {
    const question = askQuestion.trim();
    if (!question || askStreaming) {
      return;
    }
    const controller = new AbortController();
    askAbortRef.current = controller;
    setAskStreaming(true);
    setAskAnswer("");
    setAskEvidenceRefs([]);
    setAskError(null);
    try {
      await chatApi.stream(
        {
          message: question,
          case_id: caseId,
          analysis_run_id: latestRun.analysis_run_id,
        },
        {
          delta: (delta) => setAskAnswer((current) => `${current}${delta}`),
          evidence: (evidenceRefs) => setAskEvidenceRefs(evidenceRefs),
          done: (message) => setAskAnswer((current) => current || message),
          error: (message) => setAskError(message),
        },
        controller.signal,
      );
    } catch (caught) {
      if (!isAbortError(caught)) {
        setAskError(apiErrorMessage(caught));
      }
    } finally {
      if (askAbortRef.current === controller) {
        askAbortRef.current = null;
      }
      setAskStreaming(false);
    }
  }

  function cancelAsk() {
    askAbortRef.current?.abort();
    askAbortRef.current = null;
    setAskStreaming(false);
  }

  const trackedEvents = trackedRun ? runEvents[trackedRun.analysis_run_id] || [] : [];

  return (
    <Shell caseId={caseId} runId={latestRun?.analysis_run_id} caseTitle={caseRecord?.title}>
      <div className="toolbar">
        <h1>Case Workspace</h1>
        {latestRun && (
          <Link
            className="button secondary"
            href={`/cases/${caseId}/runs/${latestRun.analysis_run_id}/summary`}
          >
            Open latest report
          </Link>
        )}
      </div>

      {error && <div className="alert error">{error}</div>}
      {loading && <section className="panel"><div className="empty">Loading case</div></section>}

      {!loading && caseRecord && (
        <>
          <section className="grid three">
            <Metric label="Case status" value={caseRecord.status} />
            <Metric label="Runs" value={String(runs.length)} />
            <Metric label="Latest templates" value={progressValue(latestRun, "templates")} />
          </section>

          <section className="panel" style={{marginTop: 14}}>
            <h2>Run Analysis</h2>
            <label className="field">
              Log/archive files
              <input
                accept=".log,.txt,.json,.jsonl,.zip,.gz,.tar,.tgz"
                multiple
                type="file"
                onChange={(event) => handleFileSelection(Array.from(event.target.files || []))}
              />
            </label>
            {uploadItems.length > 0 && (
              <div className="upload-progress-list">
                {uploadItems.map((item) => {
                  const percent = uploadPercent(item);
                  return (
                    <div className="upload-progress-row" key={item.key}>
                      <div className="upload-progress-header">
                        <strong>{item.name}</strong>
                        <span className={`pill ${statusClass(item.status)}`}>{item.status}</span>
                      </div>
                      <div className="progress-track compact" aria-label={`${item.name} upload progress`}>
                        <div className="progress-fill" style={{width: `${percent}%`}} />
                      </div>
                      <div className="upload-progress-meta">
                        <span>{percent}%</span>
                        <span>{formatBytes(item.bytesSent)} / {formatBytes(item.size)}</span>
                        {item.partNumber && item.partCount && (
                          <span>part {item.partNumber}/{item.partCount}</span>
                        )}
                        {item.message && <span>{item.message}</span>}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
            <div className="form-actions">
              <button
                className="button"
                disabled={starting !== null || selectedFiles.length === 0}
                type="button"
                onClick={startUploadedAnalysis}
              >
                {starting === "files" ? "Uploading" : "Upload and analyze files"}
              </button>
              <button
                className="button secondary"
                disabled={starting !== null}
                type="button"
                onClick={startSampleAnalysis}
              >
                {starting === "sample" ? "Starting" : "Start sample/local analysis"}
              </button>
            </div>
            <p className="muted">
              Uploaded files run through the local object store. The sample/local action uses the
              deterministic fixture set.
            </p>
          </section>

          <section style={{marginTop: 14}}>
            <AnalysisProgressPanel caseId={caseId} run={trackedRun} events={trackedEvents} />
          </section>

          {latestRun && (
            <section className="panel ask-panel" style={{marginTop: 14}}>
              <h2>Copilot Ask</h2>
              <label className="field">
                Question
                <textarea
                  disabled={askStreaming}
                  value={askQuestion}
                  onChange={(event) => setAskQuestion(event.target.value)}
                />
              </label>
              <div className="form-actions">
                {!askStreaming && (
                  <button
                    className="button"
                    disabled={!askQuestion.trim()}
                    type="button"
                    onClick={() => void askCopilot(latestRun)}
                  >
                    Ask
                  </button>
                )}
                {askStreaming && (
                  <button className="button secondary" type="button" onClick={cancelAsk}>
                    Cancel
                  </button>
                )}
              </div>
              {askError && <div className="alert error compact">{askError}</div>}
              {(askAnswer || askStreaming) && (
                <div className="ask-answer">
                  {askAnswer || <span className="muted">Waiting for response</span>}
                </div>
              )}
              {askEvidenceRefs.length > 0 && (
                <div className="evidence-list">
                  <strong>Evidence refs ({askEvidenceRefs.length})</strong>
                  {askEvidenceRefs.map((ref) => (
                    <div key={`${ref.log_id}-${ref.line_number}`}>
                      {ref.file_path}:{ref.line_number}
                      {ref.template_id ? ` - ${ref.template_id}` : ""}
                    </div>
                  ))}
                </div>
              )}
            </section>
          )}

          <section className="grid two" style={{marginTop: 14}}>
            <div className="panel">
              <h2>{caseRecord.case_key}</h2>
              <p>{valueLabel(caseRecord.title)}</p>
              <table>
                <tbody>
                  <tr><td>Product</td><td>{valueLabel(caseRecord.product)}</td></tr>
                  <tr><td>Service</td><td>{valueLabel(caseRecord.service)}</td></tr>
                  <tr><td>Environment</td><td>{valueLabel(caseRecord.environment)}</td></tr>
                  <tr><td>Incident start</td><td>{formatDateTime(caseRecord.incident_start)}</td></tr>
                  <tr><td>Incident end</td><td>{formatDateTime(caseRecord.incident_end)}</td></tr>
                </tbody>
              </table>
            </div>

            <div className="panel">
              <h2>Latest Run</h2>
              {!latestRun && <div className="empty">No analysis runs</div>}
              {latestRun && (
                <table>
                  <tbody>
                    <tr>
                      <td>Status</td>
                      <td><span className={`pill ${statusClass(latestRun.status)}`}>{latestRun.status}</span></td>
                    </tr>
                    <tr><td>Step</td><td>{latestRun.current_step}</td></tr>
                    <tr><td>Started</td><td>{formatDateTime(latestRun.started_at)}</td></tr>
                    <tr><td>Completed</td><td>{formatDateTime(latestRun.completed_at)}</td></tr>
                    <tr><td>Model</td><td>{latestRun.model_provider} / {latestRun.model_name}</td></tr>
                  </tbody>
                </table>
              )}
            </div>
          </section>

          <section className="panel" style={{marginTop: 14}}>
            <h2>Analysis Runs</h2>
            {runs.length === 0 && <div className="empty">No analysis runs</div>}
            {runs.length > 0 && (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Run</th>
                      <th>Status</th>
                      <th>Step</th>
                      <th>Started</th>
                      <th>Completed</th>
                      <th>Report</th>
                    </tr>
                  </thead>
                  <tbody>
                    {runs.map((run) => (
                      <tr key={run.analysis_run_id}>
                        <td>#{run.run_number}</td>
                        <td><span className={`pill ${statusClass(run.status)}`}>{run.status}</span></td>
                        <td>{run.current_step}</td>
                        <td>{formatDateTime(run.started_at)}</td>
                        <td>{formatDateTime(run.completed_at)}</td>
                        <td>
                          <Link href={`/cases/${caseId}/runs/${run.analysis_run_id}/summary`}>Summary</Link>
                        </td>
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
