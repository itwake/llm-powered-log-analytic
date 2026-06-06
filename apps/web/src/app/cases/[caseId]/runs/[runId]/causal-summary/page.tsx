"use client";

import { useParams } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";
import { CausalSummaryResponse, ExportRequest, reportsApi } from "@/lib/api";
import { apiErrorMessage, formatDateTime, formatPercent } from "@/lib/format";
import { Shell } from "@/components/Shell";

function textField(item: Record<string, unknown>, key: string): string {
  const value = item[key];
  return typeof value === "string" && value.trim() ? value : "n/a";
}

export default function CausalSummaryPage() {
  const {caseId, runId} = useParams<{caseId: string; runId: string}>();
  const [data, setData] = useState<CausalSummaryResponse | null>(null);
  const [feedbackType, setFeedbackType] = useState("useful");
  const [rating, setRating] = useState(5);
  const [comment, setComment] = useState("");
  const [loading, setLoading] = useState(true);
  const [exporting, setExporting] = useState<ExportRequest["export_type"] | null>(null);
  const [submittingFeedback, setSubmittingFeedback] = useState(false);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      setData(await reportsApi.causalSummary(caseId, runId));
    } catch (caught) {
      setError(apiErrorMessage(caught));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, [caseId, runId]);

  async function createExport(exportType: ExportRequest["export_type"]) {
    setExporting(exportType);
    setError(null);
    setStatusMessage(null);
    try {
      const response = await reportsApi.createExport(caseId, runId, {
        export_type: exportType,
        include_sections: ["causal_summary"],
        redaction_mode: "customer_safe",
      });
      setStatusMessage(`${exportType} export ready: ${response.download_url}`);
    } catch (caught) {
      setError(apiErrorMessage(caught));
    } finally {
      setExporting(null);
    }
  }

  async function submitFeedback(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmittingFeedback(true);
    setError(null);
    setStatusMessage(null);
    try {
      const response = await reportsApi.submitFeedback(caseId, {
        analysis_run_id: runId,
        target_type: "causal_summary",
        target_id: runId,
        feedback_type: feedbackType,
        rating,
        comment: comment || null,
      });
      setStatusMessage(`Feedback submitted: ${response.feedback_id}`);
      setComment("");
    } catch (caught) {
      setError(apiErrorMessage(caught));
    } finally {
      setSubmittingFeedback(false);
    }
  }

  return (
    <Shell caseId={caseId} runId={runId}>
      <div className="toolbar">
        <h1>Causal Summary</h1>
        <button
          className="button"
          disabled={exporting !== null}
          type="button"
          onClick={() => void createExport("markdown")}
        >
          {exporting === "markdown" ? "Exporting" : "Export Markdown"}
        </button>
        <button
          className="button secondary"
          disabled={exporting !== null}
          type="button"
          onClick={() => void createExport("html")}
        >
          {exporting === "html" ? "Exporting" : "Export HTML"}
        </button>
        <button
          className="button secondary"
          disabled={exporting !== null}
          type="button"
          onClick={() => void createExport("json")}
        >
          {exporting === "json" ? "Exporting" : "Export JSON"}
        </button>
      </div>

      {error && <div className="alert error">{error}</div>}
      {statusMessage && <div className="alert success">{statusMessage}</div>}
      {loading && <section className="panel"><div className="empty">Loading causal summary</div></section>}

      {!loading && data && (
        <>
          <section className="grid three">
            <div className="panel metric">
              <span className="muted">Confidence</span>
              <strong>{formatPercent(data.confidence)}</strong>
            </div>
            <div className="panel metric">
              <span className="muted">Evidence refs</span>
              <strong>{String(data.evidence_refs.length)}</strong>
            </div>
            <div className="panel metric">
              <span className="muted">Next actions</span>
              <strong>{String(data.next_actions.length)}</strong>
            </div>
          </section>

          <section className="report-grid" style={{marginTop: 14}}>
            <div className="markdown-view">{data.summary_markdown}</div>
            <div className="panel">
              <h2>Feedback</h2>
              <form onSubmit={submitFeedback}>
                <label className="field">
                  Type
                  <select value={feedbackType} onChange={(event) => setFeedbackType(event.target.value)}>
                    <option value="useful">Useful</option>
                    <option value="needs_correction">Needs correction</option>
                    <option value="wrong_causal_edge">Wrong causal edge</option>
                  </select>
                </label>
                <label className="field">
                  Rating
                  <select value={rating} onChange={(event) => setRating(Number(event.target.value))}>
                    <option value={5}>5</option>
                    <option value={3}>3</option>
                    <option value={1}>1</option>
                  </select>
                </label>
                <label className="field">
                  Comment
                  <textarea value={comment} onChange={(event) => setComment(event.target.value)} />
                </label>
                <button className="button" disabled={submittingFeedback} type="submit">
                  {submittingFeedback ? "Submitting" : "Submit feedback"}
                </button>
              </form>
            </div>
          </section>

          <section className="grid two" style={{marginTop: 14}}>
            <div className="panel">
              <h2>Next Actions</h2>
              {data.next_actions.length === 0 && <div className="empty">No next actions</div>}
              {data.next_actions.map((action, index) => (
                <p key={`${textField(action, "title")}-${index}`}>
                  <strong>{textField(action, "title")}</strong>
                  <br />
                  {textField(action, "description")}
                  <br />
                  <span className="muted">
                    {textField(action, "priority")} · {textField(action, "owner_role")}
                  </span>
                </p>
              ))}
            </div>
            <div className="panel">
              <h2>Evidence</h2>
              {data.evidence_refs.length === 0 && <div className="empty">No evidence refs</div>}
              {data.evidence_refs.length > 0 && (
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>File</th>
                        <th>Line</th>
                        <th>Time</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.evidence_refs.map((ref) => (
                        <tr key={`${ref.log_id}-${ref.line_number}`}>
                          <td>{ref.file_path}</td>
                          <td>{ref.line_number}</td>
                          <td>{formatDateTime(ref.timestamp)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </section>
        </>
      )}
    </Shell>
  );
}
