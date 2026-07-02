"use client";

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
    <div className="inspector-stack">
      <AnalysisProgressPanel
        cancelling={cancelling}
        caseId={caseId}
        events={events}
        run={run}
        onCancel={onCancel}
      />

      <Card className="inspector-card">
        <EvidenceDetail
          caseId={caseId}
          refItem={selectedEvidence}
          runId={run?.analysis_run_id || ""}
        />
      </Card>

      <Card className="inspector-card">
        <SectionHeader eyebrow="Case" title={caseRecord?.case_key || "Case Details"} />
        {!caseRecord && <EmptyState title="Loading case" />}
        {caseRecord && (
          <dl className="detail-kv detail-list">
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
          </dl>
        )}
      </Card>

      <Card className="inspector-card">
        <SectionHeader eyebrow="Run" title={run ? `Run #${run.run_number}` : "Latest Run"} />
        {!run && <EmptyState title="No analysis runs" />}
        {run && (
          <dl className="detail-kv detail-list">
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
                <dd>{run.error_message}</dd>
              </>
            )}
          </dl>
        )}
      </Card>
    </div>
  );
}
