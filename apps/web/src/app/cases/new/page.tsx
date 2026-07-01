"use client";

import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";
import { casesApi, runsApi } from "@/lib/api";
import { apiErrorMessage } from "@/lib/format";
import { Shell } from "@/components/Shell";

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
      if (mode === "start") {
        const uploaded = selectedFiles.length
          ? await casesApi.uploadFiles(created.case_id, selectedFiles)
          : [];
        await runsApi.start(created.case_id, {
          input_file_ids: uploaded.map((file) => file.file_id),
          input_paths: [],
          config: {default_window_size_seconds: 60},
        }, {background: true});
        router.push(`/cases/${created.case_id}`);
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
    <Shell>
      <h1>New Case</h1>
      {error && <div className="alert error">{error}</div>}
      <section className="grid two">
        <form className="panel" onSubmit={submit}>
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
          <label className="field">
            Log/archive files
            <input
              accept=".log,.txt,.json,.jsonl,.zip,.gz,.tar,.tgz"
              multiple
              type="file"
              onChange={(event) => setSelectedFiles(Array.from(event.target.files || []))}
            />
          </label>
          {selectedFiles.length > 0 && (
            <div className="file-list">
              {selectedFiles.map((file) => (
                <div key={`${file.name}-${file.size}`}>{file.name}</div>
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
        <div className="panel">
          <h2>Evidence</h2>
          <p className="muted">
            Selected log and archive files are uploaded to the local object store before analysis.
          </p>
          <p className="muted">
            With no files selected, the sample/local action runs the deterministic fixture set.
          </p>
        </div>
      </section>
    </Shell>
  );
}
