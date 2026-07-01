"use client";

import Link from "next/link";
import type { EvidenceRef } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { EmptyState } from "@/components/ui";

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
    const params = new URLSearchParams({q: refItem.template_id});
    return `${basePath}?${params.toString()}`;
  }
  return basePath;
}

interface EvidenceChipProps {
  refItem: EvidenceRef;
  onClick?: (refItem: EvidenceRef) => void;
}

export function EvidenceChip({onClick, refItem}: EvidenceChipProps) {
  const label = formatEvidenceLabel(refItem);
  return (
    <button
      aria-label={`Evidence ${label}`}
      className="evidence-chip"
      type="button"
      onClick={() => onClick?.(refItem)}
    >
      {label}
    </button>
  );
}

interface EvidenceDetailProps {
  caseId: string;
  runId: string;
  refItem: EvidenceRef | null;
}

export function EvidenceDetail({caseId, refItem, runId}: EvidenceDetailProps) {
  if (!refItem) {
    return (
      <EmptyState title="Selected evidence">
        Select evidence from an answer to inspect it.
      </EmptyState>
    );
  }

  return (
    <div className="evidence-detail">
      <div className="section-header compact">
        <div>
          <span className="eyebrow">Selected evidence</span>
          <h2>{refItem.file_path}</h2>
        </div>
        {runId && (
          <Link className="button secondary" href={evidenceLogsHref(caseId, runId, refItem)}>
            Open logs around this evidence
          </Link>
        )}
      </div>
      <dl className="detail-kv detail-list">
        <dt>Line</dt>
        <dd>{refItem.line_number}</dd>
        <dt>Timestamp</dt>
        <dd>{formatDateTime(refItem.timestamp)}</dd>
        <dt>Template</dt>
        <dd>{refItem.template_id || "n/a"}</dd>
        <dt>Log id</dt>
        <dd>{refItem.log_id}</dd>
      </dl>
    </div>
  );
}
