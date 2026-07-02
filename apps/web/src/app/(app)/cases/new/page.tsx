"use client";

import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Chip from "@mui/material/Chip";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";
import { casesApi, runsApi } from "@/lib/api";
import { apiErrorMessage } from "@/lib/format";
import { Button, Card, FieldHint, SectionHeader } from "@/components/ui";

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
      window.dispatchEvent(new CustomEvent("logan:case-saved", { detail: created }));
      if (mode === "start") {
        const uploaded = selectedFiles.length
          ? await casesApi.uploadFiles(created.case_id, selectedFiles)
          : [];
        const run = await runsApi.start(created.case_id, {
          input_file_ids: uploaded.map((file) => file.file_id),
          input_paths: [],
          config: { default_window_size_seconds: 60 },
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
    <Stack spacing={2.5}>
      <Box>
        <Typography color="text.secondary" sx={{ fontWeight: 800, textTransform: "uppercase" }} variant="caption">
          Case intake
        </Typography>
        <Typography component="h1" sx={{ fontWeight: 850 }} variant="h4">
          New Case
        </Typography>
        <Typography color="text.secondary">
          Capture the incident context and choose whether to launch analysis immediately.
        </Typography>
      </Box>

      <Box sx={{ display: "grid", gap: 2, gridTemplateColumns: { xs: "1fr", lg: "320px minmax(0, 1fr)" } }}>
        <Stack spacing={2}>
          <Card>
            <SectionHeader eyebrow="Onboarding" title="Create an incident workspace" />
            <Typography color="text.secondary" sx={{ mt: 2 }}>
              Add the incident context, attach logs when available, then start analysis or save
              the workspace for later.
            </Typography>
          </Card>
          <Card>
            <SectionHeader eyebrow="Evidence" title="Upload plan" />
            <Stack spacing={1.5} sx={{ mt: 2 }}>
              <Typography color="text.secondary">
                Selected log and archive files are uploaded to the local object store before analysis.
              </Typography>
              <Typography color="text.secondary">
                With no files selected, the sample/local action runs the deterministic fixture set.
              </Typography>
            </Stack>
          </Card>
        </Stack>

        <Card>
          <Box component="form" onSubmit={submit}>
            <Stack spacing={2.5}>
              {error && <Alert severity="error">{error}</Alert>}
              <SectionHeader eyebrow="Incident" title="Case details" />
              <TextField
                label="Title"
                required
                value={title}
                onChange={(event) => setTitle(event.target.value)}
              />
              <TextField
                label="Issue description"
                minRows={4}
                multiline
                value={issueDescription}
                onChange={(event) => setIssueDescription(event.target.value)}
              />
              <Box sx={{ display: "grid", gap: 2, gridTemplateColumns: { xs: "1fr", md: "repeat(2, minmax(0, 1fr))" } }}>
                <TextField label="Product" value={product} onChange={(event) => setProduct(event.target.value)} />
                <TextField label="Service" value={service} onChange={(event) => setService(event.target.value)} />
                <TextField label="Environment" value={environment} onChange={(event) => setEnvironment(event.target.value)} />
                <TextField
                  label="Incident start"
                  slotProps={{ inputLabel: { shrink: true } }}
                  type="datetime-local"
                  value={incidentStart}
                  onChange={(event) => setIncidentStart(event.target.value)}
                />
                <TextField
                  label="Incident end"
                  slotProps={{ inputLabel: { shrink: true } }}
                  type="datetime-local"
                  value={incidentEnd}
                  onChange={(event) => setIncidentEnd(event.target.value)}
                />
              </Box>

              <Box
                component="label"
                sx={{
                  background: "linear-gradient(135deg, rgba(217,236,255,0.5), rgba(230,225,255,0.45))",
                  border: "1px dashed",
                  borderColor: "rgba(91,92,246,0.28)",
                  borderRadius: "14px",
                  cursor: "pointer",
                  display: "grid",
                  gap: 1,
                  p: 2.5,
                }}
              >
                <Typography sx={{ fontWeight: 800 }}>Log/archive files</Typography>
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
              </Box>
              {selectedFiles.length > 0 && (
                <Stack direction="row" sx={{ flexWrap: "wrap", gap: 1 }}>
                  {selectedFiles.map((file) => (
                    <Chip key={`${file.name}-${file.size}`} label={`${file.name} - ${formatBytes(file.size)}`} />
                  ))}
                </Stack>
              )}
              <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5}>
                <Button disabled={submitting} name="mode" type="submit" value="create">
                  {submitting && submitMode === "create" ? "Creating" : "Create case"}
                </Button>
                <Button disabled={submitting} name="mode" type="submit" value="start" variant="secondary">
                  {submitting && submitMode === "start" ? "Starting" : startButtonLabel}
                </Button>
              </Stack>
            </Stack>
          </Box>
        </Card>
      </Box>
    </Stack>
  );
}
