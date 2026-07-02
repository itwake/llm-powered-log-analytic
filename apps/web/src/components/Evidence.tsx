"use client";

import Box from "@mui/material/Box";
import Chip from "@mui/material/Chip";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import Link from "@/components/Link";
import type { EvidenceRef } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { Button, EmptyState } from "@/components/ui";

export function formatEvidenceLabel(ref: EvidenceRef): string {
  const fileName = ref.file_path.split(/[\\/]/).filter(Boolean).pop() || ref.file_path;
  return `${fileName}:${ref.line_number}`;
}

export function evidenceLogsHref(caseId: string, runId: string, refItem: EvidenceRef): string {
  const basePath = `/cases/${caseId}/runs/${runId}/logs`;
  if (!runId) {
    return basePath;
  }
  if (refItem.timestamp) {
    const timestamp = new Date(refItem.timestamp);
    if (!Number.isNaN(timestamp.getTime())) {
      const params = new URLSearchParams({
        window_start: new Date(timestamp.getTime() - 60_000).toISOString(),
        window_end: new Date(timestamp.getTime() + 60_000).toISOString(),
      });
      return `${basePath}?${params.toString()}`;
    }
  }
  if (refItem.template_id) {
    const params = new URLSearchParams({ q: refItem.template_id });
    return `${basePath}?${params.toString()}`;
  }
  return basePath;
}

interface EvidenceChipProps {
  refItem: EvidenceRef;
  onClick?: (refItem: EvidenceRef) => void;
  selected?: boolean;
}

export function EvidenceChip({ onClick, refItem, selected = false }: EvidenceChipProps) {
  const label = formatEvidenceLabel(refItem);
  return (
    <Chip
      aria-label={`Evidence ${label}`}
      clickable
      color={selected ? "primary" : "default"}
      component="button"
      label={label}
      variant={selected ? "filled" : "outlined"}
      onClick={() => onClick?.(refItem)}
    />
  );
}

interface EvidenceDetailProps {
  caseId: string;
  runId: string;
  refItem: EvidenceRef | null;
}

export function EvidenceDetail({ caseId, refItem, runId }: EvidenceDetailProps) {
  if (!refItem) {
    return (
      <EmptyState title="Selected evidence">
        Select evidence from an answer to inspect it.
      </EmptyState>
    );
  }

  return (
    <Stack spacing={2}>
      <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} sx={{ alignItems: { xs: "flex-start", sm: "center" }, justifyContent: "space-between" }}>
        <Box sx={{ minWidth: 0 }}>
          <Typography color="text.secondary" sx={{ fontWeight: 800, textTransform: "uppercase" }} variant="caption">
            Selected evidence
          </Typography>
          <Typography component="h2" sx={{ fontWeight: 800, overflowWrap: "anywhere" }} variant="h6">
            {refItem.file_path}
          </Typography>
        </Box>
        {runId && (
          <Button component={Link} href={evidenceLogsHref(caseId, runId, refItem)} variant="secondary">
            Open logs around this evidence
          </Button>
        )}
      </Stack>
      <Box
        component="dl"
        sx={{
          display: "grid",
          gap: 1,
          gridTemplateColumns: "110px minmax(0, 1fr)",
          m: 0,
          "& dt": { color: "text.secondary" },
          "& dd": { m: 0, overflowWrap: "anywhere" },
        }}
      >
        <dt>Line</dt>
        <dd>{refItem.line_number}</dd>
        <dt>Timestamp</dt>
        <dd>{formatDateTime(refItem.timestamp)}</dd>
        <dt>Template</dt>
        <dd>{refItem.template_id || "n/a"}</dd>
        <dt>Log id</dt>
        <dd>{refItem.log_id}</dd>
      </Box>
    </Stack>
  );
}
