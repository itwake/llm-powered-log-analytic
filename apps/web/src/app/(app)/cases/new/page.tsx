"use client";

import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";
import { casesApi, runsApi } from "@/lib/api";
import { apiErrorMessage } from "@/lib/format";
import { Card, FieldHint, SectionHeader } from "@/components/ui";

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

function formatBytes(value: number): string {
  if (value < 1024) {
    return `${value} B`;
  }
  if (value < 1024 * 1024) {
    return `${(value / 1024).toFixed(1)} KB`;
  }
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

export default function NewCasePage() {
  const router = useRouter();
  const [title, setTitle] = useState("");
  const [issueDescription, setIssueDescription] = useState("");
  const [product, setProduct] = useState("");
  const [service, setService] = useState("");
  const [environment, setEnvironment] = useState("");
  const [incidentStart, setIncidentStart] = useState("");
  const [incidentEnd, setIncidentEnd] = useState("");
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [submitMode, setSubmitMode] = useState<"create" | "start">("create");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const submitter = (event.nativeEvent as SubmitEvent).submitter;
    const mode =
      submitter instanceof HTMLButtonElement && submitter.value === "start" ? "start" : "create";
    setSubmitMode(mode);
    setError(null);
    setSubmitting(true);
    try {
      const created = await casesApi.create({
        title,
        issue_description: emptyToNull(issueDescription),
        product: emptyToNull(product),
        service: emptyToNull(service),
        environment: emptyToNull(environment),
        incident_start: localDateTimeToIso(incidentStart),
        incident_end: localDateTimeToIso(incidentEnd),
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
      });
      window.dispatchEvent(new CustomEvent("logan:case-saved", {detail: created}));
      if (mode === "start") {
        const uploaded = selectedFiles.length
          ? await casesApi.uploadFiles(created.case_id, selectedFiles)
          : [];
        const run = await runsApi.start(created.case_id, {
          input_file_ids: uploaded.map((file) => file.file_id),
          input_paths: [],
          config: {default_window_size_seconds: 60},
        });
        router.push(`/cases/${created.case_id}/runs/${run.analysis_run_id}/summary`);
        return;
      }
      router.push(`/cases/${created.case_id}`);
    } catch (caught) {
      setError(apiErrorMessage(caught));
    } finally {
      setSubmitting(false);
    }
  }

  const startButtonLabel = selectedFiles.length
    ? "Create, upload, and analyze files"
    : "Create and start sample/local analysis";

  return (
    <div className="page-stack">
        <section className="page-hero compact">
          <div>
            <span className="eyebrow">Case intake</span>
            <h1>New Case</h1>
            <p>Capture the incident context and choose whether to launch analysis immediately.</p>
          </div>
        </section>

        <section className="case-create-layout">
          <div className="intake-side">
            <Card>
              <SectionHeader eyebrow="Onboarding" title="Create an incident workspace" />
              <p className="muted">
                Add the incident context, attach logs when available, then start analysis or save
                the workspace for later.
              </p>
            </Card>
            <Card>
              <SectionHeader eyebrow="Evidence" title="Upload plan" />
              <p className="muted">
                Selected log and archive files are uploaded to the local object store before analysis.
              </p>
              <p className="muted">
                With no files selected, the sample/local action runs the deterministic fixture set.
              </p>
            </Card>
          </div>

          <form className="panel intake-form" onSubmit={submit}>
            {error && <div className="alert error">{error}</div>}
            <SectionHeader eyebrow="Incident" title="Case details" />
            <label className="field">
              Title
              <input required value={title} onChange={(event) => setTitle(event.target.value)} />
            </label>
            <label className="field">
              Issue description
              <textarea
                value={issueDescription}
                onChange={(event) => setIssueDescription(event.target.value)}
              />
            </label>
            <div className="grid two">
              <label className="field">
                Product
                <input value={product} onChange={(event) => setProduct(event.target.value)} />
              </label>
              <label className="field">
                Service
                <input value={service} onChange={(event) => setService(event.target.value)} />
              </label>
              <label className="field">
                Environment
                <input value={environment} onChange={(event) => setEnvironment(event.target.value)} />
              </label>
              <label className="field">
                Incident start
                <input
                  type="datetime-local"
                  value={incidentStart}
                  onChange={(event) => setIncidentStart(event.target.value)}
                />
              </label>
              <label className="field">
                Incident end
                <input
                  type="datetime-local"
                  value={incidentEnd}
                  onChange={(event) => setIncidentEnd(event.target.value)}
                />
              </label>
            </div>

            <label className="field dropzone">
              Log/archive files
              <input
                accept=".log,.txt,.json,.jsonl,.zip,.gz,.tar,.tgz"
                multiple
                type="file"
                onChange={(event) => setSelectedFiles(Array.from(event.target.files || []))}
              />
              <FieldHint>
                {selectedFiles.length
                  ? `${selectedFiles.length} file(s) selected`
                  : "Upload logs or continue with the local sample data."}
              </FieldHint>
            </label>
            {selectedFiles.length > 0 && (
              <div className="file-list file-chip-list">
                {selectedFiles.map((file) => (
                  <div className="file-chip" key={`${file.name}-${file.size}`}>
                    <span>{file.name}</span>
                    <small>{formatBytes(file.size)}</small>
                  </div>
                ))}
              </div>
            )}
            <div className="form-actions">
              <button
                className="button"
                disabled={submitting}
                name="mode"
                type="submit"
                value="create"
              >
                {submitting && submitMode === "create" ? "Creating" : "Create case"}
              </button>
              <button
                className="button secondary"
                disabled={submitting}
                name="mode"
                type="submit"
                value="start"
              >
                {submitting && submitMode === "start" ? "Starting" : startButtonLabel}
              </button>
            </div>
          </form>
        </section>
    </div>
  );
}
