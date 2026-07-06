"use client";

import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import FormControl from "@mui/material/FormControl";
import InputLabel from "@mui/material/InputLabel";
import MenuItem from "@mui/material/MenuItem";
import Select from "@mui/material/Select";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useParams } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";
import { reportsApi } from "@/lib/api";
import type { CausalSummaryResponse, EvidenceRef, ExportRequest } from "@/lib/api";
import { apiErrorMessage, formatDateTime, formatPercent } from "@/lib/format";
import { Metric } from "@/components/Shell";
import { EvidenceChip, EvidenceDetail } from "@/components/Evidence";
import { MarkdownMessage } from "@/components/MarkdownMessage";
import { Badge, Button, Card, EmptyState } from "@/components/ui";

function textField(item: Record<string, unknown>, key: string): string {
  const value = item[key];
  return typeof value === "string" && value.trim() ? value : "n/a";
}

export default function CausalSummaryPage() {
  const { caseId, runId } = useParams<{ caseId: string; runId: string }>();
  const [data, setData] = useState<CausalSummaryResponse | null>(null);
  const [editing, setEditing] = useState(false);
  const [summaryDraft, setSummaryDraft] = useState("");
  const [customerUpdateDraft, setCustomerUpdateDraft] = useState("");
  const [feedbackType, setFeedbackType] = useState("useful");
  const [rating, setRating] = useState(5);
  const [comment, setComment] = useState("");
  const [selectedEvidence, setSelectedEvidence] = useState<EvidenceRef | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [exporting, setExporting] = useState<ExportRequest["export_type"] | null>(null);
  const [submittingFeedback, setSubmittingFeedback] = useState(false);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const response = await reportsApi.causalSummary(caseId, runId);
      setData(response);
      setSummaryDraft(response.summary_markdown);
      setCustomerUpdateDraft(response.customer_update_markdown);
      setSelectedEvidence(response.evidence_refs[0] || null);
      setEditing(false);
    } catch (caught) {
      setError(apiErrorMessage(caught));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, [caseId, runId]);

  function startEditing() {
    if (!data) {
      return;
    }
    setSummaryDraft(data.summary_markdown);
    setCustomerUpdateDraft(data.customer_update_markdown);
    setStatusMessage(null);
    setEditing(true);
  }

  function cancelEditing() {
    if (data) {
      setSummaryDraft(data.summary_markdown);
      setCustomerUpdateDraft(data.customer_update_markdown);
    }
    setError(null);
    setEditing(false);
  }

  async function saveSummary(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    setStatusMessage(null);
    try {
      const response = await reportsApi.updateCausalSummary(caseId, runId, {
        summary_markdown: summaryDraft,
        customer_update_markdown: customerUpdateDraft,
      });
      setData(response);
      setSummaryDraft(response.summary_markdown);
      setCustomerUpdateDraft(response.customer_update_markdown);
      setEditing(false);
      setStatusMessage("Causal summary saved");
    } catch (caught) {
      setError(apiErrorMessage(caught));
    } finally {
      setSaving(false);
    }
  }

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
    <Stack spacing={2.5}>
      <Stack direction={{ xs: "column", lg: "row" }} spacing={2} sx={{ alignItems: { xs: "flex-start", lg: "center" }, justifyContent: "space-between" }}>
        <Box>
          <Typography component="h1" sx={{ fontWeight: 850 }} variant="h4">
            Causal Summary
          </Typography>
          <Typography color="text.secondary" variant="body2">
            An evidence-first narrative of the likely cause - every claim links back to raw log
            lines, and wording stays cautious until humans validate.
          </Typography>
        </Box>
        <Stack direction="row" sx={{ flexWrap: "wrap", gap: 1 }}>
          {!editing && data && (
            <Button type="button" onClick={startEditing}>
              Edit
            </Button>
          )}
          <Button disabled={exporting !== null || editing} type="button" onClick={() => void createExport("markdown")}>
            {exporting === "markdown" ? "Exporting" : "Export Markdown"}
          </Button>
          <Button disabled={exporting !== null || editing} type="button" variant="secondary" onClick={() => void createExport("html")}>
            {exporting === "html" ? "Exporting" : "Export HTML"}
          </Button>
          <Button disabled={exporting !== null || editing} type="button" variant="secondary" onClick={() => void createExport("json")}>
            {exporting === "json" ? "Exporting" : "Export JSON"}
          </Button>
        </Stack>
      </Stack>

      {error && <Alert severity="error">{error}</Alert>}
      {statusMessage && <Alert severity="success">{statusMessage}</Alert>}
      {loading && <Card><EmptyState title="Loading causal summary" /></Card>}

      {!loading && data && (
        <>
          <Box sx={{ display: "grid", gap: 2, gridTemplateColumns: { xs: "1fr", sm: "repeat(2, minmax(0, 1fr))", lg: "repeat(4, minmax(0, 1fr))" } }}>
            <Metric label="Confidence" value={formatPercent(data.confidence)} />
            <Metric label="Evidence refs" value={String(data.evidence_refs.length)} />
            <Metric label="Next actions" value={String(data.next_actions.length)} />
            <Card>
              <Stack spacing={0.75}>
                <Typography color="text.secondary" variant="body2">Status</Typography>
                <Box>
                  <Badge tone={data.edited ? "warning" : "success"}>
                    {data.edited ? "Edited" : "Generated"}
                  </Badge>
                </Box>
              </Stack>
            </Card>
          </Box>

          <Box sx={{ display: "grid", gap: 2, gridTemplateColumns: { xs: "1fr", xl: "minmax(0, 1.45fr) minmax(340px, 0.7fr)" } }}>
            {editing ? (
              <Card>
                <Box component="form" onSubmit={saveSummary}>
                <Stack spacing={2}>
                  <TextField
                    label="Summary markdown"
                    maxRows={24}
                    minRows={12}
                    multiline
                    required
                    value={summaryDraft}
                    slotProps={{ htmlInput: { maxLength: 12000 } }}
                    onChange={(event) => setSummaryDraft(event.target.value)}
                  />
                  <TextField
                    label="Customer update markdown"
                    maxRows={18}
                    minRows={8}
                    multiline
                    value={customerUpdateDraft}
                    slotProps={{ htmlInput: { maxLength: 12000 } }}
                    onChange={(event) => setCustomerUpdateDraft(event.target.value)}
                  />
                  <Stack direction="row" spacing={1.5}>
                    <Button disabled={saving} type="submit">
                      {saving ? "Saving" : "Save"}
                    </Button>
                    <Button disabled={saving} type="button" variant="secondary" onClick={cancelEditing}>
                      Cancel
                    </Button>
                  </Stack>
                </Stack>
                </Box>
              </Card>
            ) : (
              <Stack spacing={2}>
                <Card>
                  <MarkdownMessage content={data.summary_markdown} headingMode="presentation" />
                </Card>
                <Card>
                  <Typography component="h2" gutterBottom sx={{ fontWeight: 800 }} variant="h6">
                    Customer Update
                  </Typography>
                  {data.customer_update_markdown ? (
                    <MarkdownMessage content={data.customer_update_markdown} headingMode="presentation" />
                  ) : (
                    <Typography color="text.secondary" variant="body2">
                      No customer update
                    </Typography>
                  )}
                </Card>
              </Stack>
            )}
            <Card>
              <Stack component="form" spacing={2} onSubmit={submitFeedback}>
                <Typography component="h2" sx={{ fontWeight: 800 }} variant="h6">
                  Feedback
                </Typography>
                <FormControl>
                  <InputLabel id="feedback-type-label">Type</InputLabel>
                  <Select
                    label="Type"
                    labelId="feedback-type-label"
                    value={feedbackType}
                    onChange={(event) => setFeedbackType(event.target.value)}
                  >
                    <MenuItem value="useful">Useful</MenuItem>
                    <MenuItem value="needs_correction">Needs correction</MenuItem>
                    <MenuItem value="wrong_causal_edge">Wrong causal edge</MenuItem>
                  </Select>
                </FormControl>
                <FormControl>
                  <InputLabel id="feedback-rating-label">Rating</InputLabel>
                  <Select
                    label="Rating"
                    labelId="feedback-rating-label"
                    value={String(rating)}
                    onChange={(event) => setRating(Number(event.target.value))}
                  >
                    <MenuItem value="5">5</MenuItem>
                    <MenuItem value="3">3</MenuItem>
                    <MenuItem value="1">1</MenuItem>
                  </Select>
                </FormControl>
                <TextField label="Comment" minRows={4} multiline value={comment} onChange={(event) => setComment(event.target.value)} />
                <Button disabled={submittingFeedback} type="submit">
                  {submittingFeedback ? "Submitting" : "Submit feedback"}
                </Button>
              </Stack>
            </Card>
          </Box>

          <Box sx={{ display: "grid", gap: 2, gridTemplateColumns: { xs: "1fr", lg: "repeat(2, minmax(0, 1fr))" } }}>
            <Card>
              <Stack spacing={2}>
                <Typography component="h2" sx={{ fontWeight: 800 }} variant="h6">
                  Next Actions
                </Typography>
                {data.next_actions.length === 0 && <EmptyState title="No next actions" />}
                {data.next_actions.map((action, index) => (
                  <Box key={`${textField(action, "title")}-${index}`} sx={{ border: 1, borderColor: "divider", borderRadius: "10px", p: 1.5 }}>
                    <Typography sx={{ fontWeight: 800 }}>{textField(action, "title")}</Typography>
                    <Typography>{textField(action, "description")}</Typography>
                    <Typography color="text.secondary" variant="caption">
                      {textField(action, "priority")} | {textField(action, "owner_role")}
                    </Typography>
                  </Box>
                ))}
              </Stack>
            </Card>
            <Card>
              <Stack spacing={2}>
                <Typography component="h2" sx={{ fontWeight: 800 }} variant="h6">
                  Evidence
                </Typography>
                {data.evidence_refs.length === 0 && <EmptyState title="No evidence refs" />}
                {data.evidence_refs.length > 0 && (
                  <Stack spacing={2}>
                    <Stack direction="row" sx={{ flexWrap: "wrap", gap: 1 }}>
                      {data.evidence_refs.map((ref) => (
                        <EvidenceChip
                          key={`${ref.log_id}-${ref.line_number}`}
                          refItem={ref}
                          selected={selectedEvidence?.log_id === ref.log_id}
                          onClick={setSelectedEvidence}
                        />
                      ))}
                    </Stack>
                    <EvidenceDetail
                      caseId={caseId}
                      refItem={selectedEvidence}
                      runId={runId}
                    />
                    {selectedEvidence && (
                      <Typography color="text.secondary" sx={{ overflowWrap: "anywhere" }} variant="body2">
                        {selectedEvidence.file_path}:{selectedEvidence.line_number} at{" "}
                        {formatDateTime(selectedEvidence.timestamp)}
                      </Typography>
                    )}
                  </Stack>
                )}
              </Stack>
            </Card>
          </Box>
        </>
      )}
    </Stack>
  );
}
