"use client";

import Stack from "@mui/material/Stack";
import { useParams } from "next/navigation";
import type { ReactNode } from "react";
import { CaseAnalysisNav } from "@/components/CaseAnalysisNav";

export default function AnalysisRunLayout({ children }: { children: ReactNode }) {
  const { caseId, runId } = useParams<{ caseId: string; runId: string }>();

  return (
    <Stack spacing={2.5}>
      <CaseAnalysisNav caseId={caseId} runId={runId} />
      {children}
    </Stack>
  );
}
