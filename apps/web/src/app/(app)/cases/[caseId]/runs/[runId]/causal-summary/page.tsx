"use client";

import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { ConfidenceExplainer, confidenceLabel, formatConfidence } from "@/components/ConfidenceExplainer";
import { EvidenceChip, EvidenceDetail } from "@/components/Evidence";
import { MarkdownMessage } from "@/components/MarkdownMessage";
import { Metric } from "@/components/Shell";
import { Card, EmptyState } from "@/components/ui";
import { reportsApi } from "@/lib/api";
import type { CausalSummaryResponse, EvidenceRef } from "@/lib/api";
import { apiErrorMessage } from "@/lib/format";

function textField(item: Record<string, unknown>, key: string): string {
  const value = item[key];
  return typeof value === "string" && value.trim() ? value : "n/a";
}

export default function CausalSummaryPage() {
  const { caseId, runId } = useParams<{ caseId: string; runId: string }>();
  const [data, setData] = useState<CausalSummaryResponse | null>(null);
  const [selectedEvidence, setSelectedEvidence] = useState<EvidenceRef | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setData(null);
    setSelectedEvidence(null);
    setError(null);
    reportsApi.causalSummary(caseId, runId)
      .then((response) => {
        if (!active) return;
        setData(response);
        setSelectedEvidence(response.evidence_refs[0] || null);
      })
      .catch((caught) => {
        if (active) setError(apiErrorMessage(caught));
      });
    return () => {
      active = false;
    };
  }, [caseId, runId]);

  return (
    <Stack spacing={2.5}>
      <Box>
        <Typography component="h1" sx={{ fontWeight: 850 }} variant="h4">
          Causal Summary
        </Typography>
        <Typography color="text.secondary" variant="body2">
          A cautious incident narrative linked to the supporting log lines.
        </Typography>
      </Box>

      {error && <Alert severity="error">{error}</Alert>}
      {!data && !error && <Card><EmptyState title="Loading causal summary" /></Card>}

      {data && (
        <>
          <Box sx={{ display: "grid", gap: 2, gridTemplateColumns: { xs: "1fr", sm: "repeat(3, minmax(0, 1fr))" } }}>
            <Metric label={`${confidenceLabel(data.confidence)} confidence`} value={formatConfidence(data.confidence)} />
            <Metric label="Evidence" value={String(data.evidence_refs.length)} />
            <Metric label="Next actions" value={String(data.next_actions.length)} />
          </Box>

          <ConfidenceExplainer
            confidence={data.confidence}
            details={data.details}
            evidenceClaims={data.evidence_claims}
            uncertainties={data.uncertainties}
            variant="rca"
          />

          <Box sx={{ display: "grid", gap: 2, gridTemplateColumns: { xs: "1fr", xl: "minmax(0, 1.35fr) minmax(320px, 0.65fr)" } }}>
            <Stack spacing={2}>
              <Card>
                <MarkdownMessage content={data.summary_markdown} headingMode="presentation" />
              </Card>
              {data.customer_update_markdown && (
                <Card>
                  <Typography component="h2" gutterBottom sx={{ fontWeight: 800 }} variant="h6">
                    Customer Update
                  </Typography>
                  <MarkdownMessage content={data.customer_update_markdown} headingMode="presentation" />
                </Card>
              )}
            </Stack>

            <Card>
              <Stack spacing={2}>
                <Typography component="h2" sx={{ fontWeight: 800 }} variant="h6">
                  Evidence
                </Typography>
                {data.evidence_refs.length === 0 ? (
                  <EmptyState title="No evidence available" />
                ) : (
                  <>
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
                    <EvidenceDetail caseId={caseId} refItem={selectedEvidence} runId={runId} />
                  </>
                )}
              </Stack>
            </Card>
          </Box>

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
                    {textField(action, "priority")} · {textField(action, "owner_role")}
                  </Typography>
                </Box>
              ))}
            </Stack>
          </Card>
        </>
      )}
    </Stack>
  );
}
