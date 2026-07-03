"use client";

import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import type { ReactNode } from "react";
import type {
  AnalysisRunResponse,
  CaseResponse,
  EvidenceRef,
  JobEventResponse,
} from "@/lib/api";
import { formatDateTime, valueLabel } from "@/lib/format";
import { AnalysisProgressPanel } from "@/components/AnalysisProgressPanel";
import { EvidenceDetail } from "@/components/Evidence";
import { Badge, Card, EmptyState, SectionHeader, statusTone } from "@/components/ui";

interface CaseRunInspectorProps {
  caseId: string;
  caseRecord: CaseResponse | null;
  run: AnalysisRunResponse | null;
  events: JobEventResponse[];
  selectedEvidence: EvidenceRef | null;
  cancelling?: boolean;
  onCancel?: (run: AnalysisRunResponse) => void;
}

function DetailList({ children }: { children: ReactNode }) {
  return (
    <Box
      component="dl"
      sx={{
        display: "grid",
        gap: 1,
        gridTemplateColumns: "120px minmax(0, 1fr)",
        m: 0,
        "& dt": { color: "text.secondary" },
        "& dd": { m: 0, overflowWrap: "anywhere" },
      }}
    >
      {children}
    </Box>
  );
}

export function CaseRunInspector({
  cancelling = false,
  caseId,
  caseRecord,
  events,
  onCancel,
  run,
  selectedEvidence,
}: CaseRunInspectorProps) {
  return (
    <Stack spacing={2}>
      <AnalysisProgressPanel
        cancelling={cancelling}
        caseId={caseId}
        events={events}
        run={run}
        onCancel={onCancel}
      />

      <Card>
        <EvidenceDetail
          caseId={caseId}
          refItem={selectedEvidence}
          runId={run?.analysis_run_id || ""}
        />
      </Card>

      <Card>
        <Stack spacing={2}>
          <SectionHeader eyebrow="Case" title={caseRecord?.case_key || "Case Details"} />
          {!caseRecord && <EmptyState title="Loading case" />}
          {caseRecord && (
            <DetailList>
              <dt>Status</dt>
              <dd><Badge tone={statusTone(caseRecord.status)}>{caseRecord.status}</Badge></dd>
              <dt>Title</dt>
              <dd>{valueLabel(caseRecord.title)}</dd>
              <dt>Product</dt>
              <dd>{valueLabel(caseRecord.product)}</dd>
              <dt>Service</dt>
              <dd>{valueLabel(caseRecord.service)}</dd>
              <dt>Environment</dt>
              <dd>{valueLabel(caseRecord.environment)}</dd>
              <dt>Incident start</dt>
              <dd>{formatDateTime(caseRecord.incident_start)}</dd>
              <dt>Incident end</dt>
              <dd>{formatDateTime(caseRecord.incident_end)}</dd>
            </DetailList>
          )}
        </Stack>
      </Card>

      <Card>
        <Stack spacing={2}>
          <SectionHeader eyebrow="Run" title={run ? `Run #${run.run_number}` : "Latest Run"} />
          {!run && <EmptyState title="No analysis runs" />}
          {run && (
            <DetailList>
              <dt>Run</dt>
              <dd>#{run.run_number}</dd>
              <dt>Status</dt>
              <dd><Badge tone={statusTone(run.status)}>{run.status}</Badge></dd>
              <dt>Step</dt>
              <dd>{run.current_step}</dd>
              <dt>Started</dt>
              <dd>{formatDateTime(run.started_at)}</dd>
              <dt>Completed</dt>
              <dd>{formatDateTime(run.completed_at)}</dd>
              <dt>Model</dt>
              <dd>{run.model_provider} / {run.model_name}</dd>
              {run.error_message && (
                <>
                  <dt>Error</dt>
                  <dd>
                    <Typography color="error" variant="body2">{run.error_message}</Typography>
                  </dd>
                </>
              )}
            </DetailList>
          )}
        </Stack>
      </Card>
    </Stack>
  );
}
