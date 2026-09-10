import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { Card, EmptyState } from "@/components/ui";
import type { CausalSummaryClaim } from "@/lib/api";

type ConfidenceExplainerVariant = "summary" | "rca";

interface ConfidenceExplainerProps {
  confidence?: number;
  details?: Record<string, unknown>;
  evidenceClaims?: CausalSummaryClaim[];
  uncertainties?: string[];
  variant: ConfidenceExplainerVariant;
}

function clampConfidence(value: number): number {
  if (!Number.isFinite(value)) return 0;
  return Math.min(1, Math.max(0, value));
}

export function confidenceLabel(value: number): string {
  const confidence = clampConfidence(value);
  if (confidence >= 0.81) return "Very high";
  if (confidence >= 0.61) return "High";
  if (confidence >= 0.31) return "Medium";
  return "Low";
}

export function formatConfidence(value: number): string {
  return `${Math.round(clampConfidence(value) * 100)}%`;
}

export function confidenceReason(value: number): string {
  const confidence = clampConfidence(value);
  if (confidence >= 0.81) {
    return "Strong supporting evidence, but still requires human validation.";
  }
  if (confidence >= 0.61) {
    return "Good supporting evidence with some uncertainty to validate.";
  }
  if (confidence >= 0.31) {
    return "Partial support; use the linked logs before relying on this finding.";
  }
  return "Weak, missing, or low-confidence evidence; treat as a review prompt.";
}

function textField(item: object, key: string): string {
  const value = (item as Record<string, unknown>)[key];
  return typeof value === "string" && value.trim() ? value : "n/a";
}

function optionalTextField(item: object, key: string): string | null {
  const value = (item as Record<string, unknown>)[key];
  return typeof value === "string" && value.trim() ? value : null;
}

function numberField(item: object, key: string): number | null {
  const value = (item as Record<string, unknown>)[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function stringArrayField(item: object, key: string): string[] {
  const value = (item as Record<string, unknown>)[key];
  return Array.isArray(value) ? value.filter((entry): entry is string => typeof entry === "string") : [];
}

function methodItems(variant: ConfidenceExplainerVariant): string[] {
  if (variant === "summary") {
    return [
      "Template confidence comes from the validated template annotation for the redacted representative samples.",
      "AI Platform annotations provide a 0-1 confidence score; invalid annotation output is treated as 0%.",
      "When model enrichment is unavailable, deterministic heuristic annotations use conservative confidence, so users should validate the linked logs.",
      "The score ranks evidence for review. It is not a probability that the classification or cause is proven.",
    ];
  }
  return [
    "Causal graph edge confidence is deterministic: 45% support ratio, 30% lag closeness, 15% shared service/entity context, and 10% source severity.",
    "Root-cause candidate score ranks early high-severity signals with supported downstream associations: 50% early timing, 30% downstream edge confidence, and 20% severity.",
    "Claim-level reasons are generated from this run's linked evidence to explain why each candidate claim was selected.",
    "The RCA summary confidence is a validated model score when AI Platform generated the narrative; the fallback summary uses the average of the strongest causal edge confidences.",
    "Every causal statement is a candidate that needs validation with metrics, traces, deployment history, and service knowledge.",
  ];
}

export function ConfidenceExplainer({
  confidence,
  details,
  evidenceClaims = [],
  uncertainties = [],
  variant,
}: ConfidenceExplainerProps) {
  const source = typeof details?.source === "string" ? details.source : null;

  return (
    <Card tone="subtle">
      <Stack spacing={2}>
        <Box>
          <Typography component="h2" sx={{ fontWeight: 850 }} variant="h6">
            How confidence is calculated
          </Typography>
          <Typography color="text.secondary" variant="body2">
            Confidence measures evidence strength for prioritization, not guaranteed correctness.
          </Typography>
        </Box>

        {typeof confidence === "number" && (
          <Box
            sx={{
              bgcolor: "rgba(255,255,255,0.7)",
              border: "1px solid rgba(91,92,246,0.12)",
              borderRadius: "12px",
              p: 1.5,
            }}
          >
            <Typography sx={{ fontWeight: 850 }}>
              {confidenceLabel(confidence)} confidence · {formatConfidence(confidence)}
            </Typography>
            <Typography color="text.secondary" variant="body2">
              {confidenceReason(confidence)}
              {source ? ` Source: ${source}.` : ""}
            </Typography>
          </Box>
        )}

        <Stack component="ul" spacing={1} sx={{ m: 0, pl: 2.25 }}>
          {methodItems(variant).map((item) => (
            <Typography component="li" key={item} variant="body2">
              {item}
            </Typography>
          ))}
        </Stack>

        {variant === "rca" && (
          <Stack spacing={1.5}>
            <Typography sx={{ fontWeight: 800 }} variant="subtitle2">
              Claim-level reasons
            </Typography>
            {evidenceClaims.length === 0 ? (
              <EmptyState title="No claim-level confidence supplied">
                <Typography color="text.secondary" variant="body2">
                  Use the summary, evidence links, and next actions to validate the candidate RCA.
                </Typography>
              </EmptyState>
            ) : (
              <Stack spacing={1}>
                {evidenceClaims.map((claim, index) => {
                  const claimConfidence = numberField(claim, "confidence");
                  const claimReason = optionalTextField(claim, "reason");
                  const refs = stringArrayField(claim, "evidence_refs");
                  return (
                    <Box
                      key={`${textField(claim, "claim")}-${index}`}
                      sx={{
                        bgcolor: "rgba(255,255,255,0.72)",
                        border: "1px solid rgba(91,92,246,0.12)",
                        borderRadius: "10px",
                        p: 1.5,
                      }}
                    >
                      <Typography sx={{ fontWeight: 800 }}>{textField(claim, "claim")}</Typography>
                      {claimReason && (
                        <Typography color="text.secondary" variant="body2">
                          Why this was chosen: {claimReason}
                        </Typography>
                      )}
                      <Typography color="text.secondary" variant="body2">
                        {claimConfidence === null
                          ? "Confidence not supplied for this claim."
                          : `${confidenceLabel(claimConfidence)} · ${formatConfidence(claimConfidence)} — ${confidenceReason(claimConfidence)}`}
                      </Typography>
                      <Typography color="text.secondary" variant="caption">
                        Evidence refs: {refs.length || "n/a"} · Needs validation
                      </Typography>
                    </Box>
                  );
                })}
              </Stack>
            )}
          </Stack>
        )}

        {variant === "rca" && uncertainties.length > 0 && (
          <Stack spacing={1}>
            <Typography sx={{ fontWeight: 800 }} variant="subtitle2">
              What reduces confidence
            </Typography>
            <Stack component="ul" spacing={0.75} sx={{ m: 0, pl: 2.25 }}>
              {uncertainties.map((item) => (
                <Typography color="text.secondary" component="li" key={item} variant="body2">
                  {item}
                </Typography>
              ))}
            </Stack>
          </Stack>
        )}
      </Stack>
    </Card>
  );
}

