"use client";

import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { Button, Card, EmptyState } from "@/components/ui";
import { casesApi, runsApi } from "@/lib/api";
import { apiErrorMessage } from "@/lib/format";

interface RunShortcutRedirectProps {
  reportLabel: string;
  reportPath: string;
}

async function findCaseIdForRun(runId: string): Promise<string | null> {
  const pageSize = 100;
  let page = 1;

  for (;;) {
    const cases = await casesApi.list({ page, page_size: pageSize });
    for (const item of cases.items) {
      const runs = await runsApi.list(item.case_id);
      if (runs.items.some((run) => run.analysis_run_id === runId)) {
        return item.case_id;
      }
    }

    if (page * pageSize >= cases.total || cases.items.length === 0) {
      return null;
    }
    page += 1;
  }
}

export function RunShortcutRedirect({ reportLabel, reportPath }: RunShortcutRedirectProps) {
  const { runId } = useParams<{ runId: string }>();
  const router = useRouter();
  const searchParams = useSearchParams();
  const queryString = searchParams.toString();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;

    async function resolveRun() {
      setError(null);
      try {
        const caseId = await findCaseIdForRun(runId);
        if (!active) {
          return;
        }
        if (!caseId) {
          setError("Analysis run not found in your cases.");
          return;
        }

        router.replace(
          `/cases/${caseId}/runs/${runId}${reportPath}${queryString ? `?${queryString}` : ""}`,
        );
      } catch (caught) {
        if (active) {
          setError(apiErrorMessage(caught));
        }
      }
    }

    void resolveRun();
    return () => {
      active = false;
    };
  }, [queryString, reportPath, router, runId]);

  return (
    <Stack spacing={2.5}>
      <Box>
        <Typography component="h1" sx={{ fontWeight: 850 }} variant="h4">
          Opening {reportLabel}
        </Typography>
        <Typography color="text.secondary">
          Resolving the case for this analysis run.
        </Typography>
      </Box>

      {error ? (
        <Card>
          <Stack spacing={2}>
            <Alert severity="error">{error}</Alert>
            <Typography color="text.secondary" variant="body2">
              Report URLs are case-scoped. Open the case workspace and select the run from the run
              history.
            </Typography>
            <Button component={Link} href="/cases" variant="secondary">
              Browse cases
            </Button>
          </Stack>
        </Card>
      ) : (
        <Card>
          <EmptyState title="Finding run">
            <Typography color="text.secondary" variant="body2">
              You will be redirected to the case-scoped report when the run is found.
            </Typography>
          </EmptyState>
        </Card>
      )}
    </Stack>
  );
}

