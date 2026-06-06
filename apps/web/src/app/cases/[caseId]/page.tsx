"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { AnalysisRunResponse, CaseResponse, casesApi, runsApi } from "@/lib/api";
import { apiErrorMessage, formatDateTime, valueLabel } from "@/lib/format";
import { Metric, Shell } from "@/components/Shell";

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

export default function CaseWorkspacePage() {
  const {caseId} = useParams<{caseId: string}>();
  const router = useRouter();
  const [caseRecord, setCaseRecord] = useState<CaseResponse | null>(null);
  const [runs, setRuns] = useState<AnalysisRunResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
    } catch (caught) {
      setError(apiErrorMessage(caught));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, [caseId]);

  async function startAnalysis() {
    setStarting(true);
    setError(null);
    try {
      const run = await runsApi.start(caseId, {
        input_paths: [],
        config: {default_window_size_seconds: 60},
      });
      router.push(`/cases/${caseId}/runs/${run.analysis_run_id}/summary`);
    } catch (caught) {
      setError(apiErrorMessage(caught));
    } finally {
      setStarting(false);
    }
  }

  const latestRun = runs[0] || null;

  return (
    <Shell caseId={caseId} runId={latestRun?.analysis_run_id} caseTitle={caseRecord?.title}>
      <div className="toolbar">
        <h1>Case Workspace</h1>
        <button className="button" disabled={starting} type="button" onClick={startAnalysis}>
          {starting ? "Starting" : "Start sample/local analysis"}
        </button>
        {latestRun && (
          <Link className="button secondary" href={`/cases/${caseId}/runs/${latestRun.analysis_run_id}/summary`}>
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
            {runs.length === 0 && <div className="empty">Start a sample/local analysis to create a run</div>}
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
