import { redirect } from "next/navigation";

interface AnalysisRunPageProps {
  params: Promise<{
    caseId: string;
    runId: string;
  }>;
}

export default async function AnalysisRunPage({params}: AnalysisRunPageProps) {
  const {caseId, runId} = await params;
  redirect(`/cases/${caseId}/runs/${runId}/summary`);
}

