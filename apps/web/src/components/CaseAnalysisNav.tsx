"use client";

import AccountTreeIcon from "@mui/icons-material/AccountTree";
import ArticleIcon from "@mui/icons-material/Article";
import FactCheckIcon from "@mui/icons-material/FactCheck";
import SpaceDashboardIcon from "@mui/icons-material/SpaceDashboard";
import SummarizeIcon from "@mui/icons-material/Summarize";
import TimelineIcon from "@mui/icons-material/Timeline";
import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import Link from "@/components/Link";

interface CaseAnalysisNavProps {
  caseId: string;
  runId: string;
  variant?: "card" | "inline";
  title?: string;
  subtitle?: string;
}

interface AnalysisNavItem {
  key: string;
  shortLabel: string;
  fullLabel: string;
  href: string;
  icon: ReactNode;
  active: boolean;
}

function analysisNavItems(caseId: string, runId: string, pathname: string): AnalysisNavItem[] {
  return [
    {
      key: "workspace",
      shortLabel: "Workspace",
      fullLabel: "Case Workspace",
      href: `/cases/${caseId}`,
      icon: <SpaceDashboardIcon fontSize="small" />,
      active: pathname === `/cases/${caseId}`,
    },
    {
      key: "summary",
      shortLabel: "Summary",
      fullLabel: "Data Summary",
      href: `/cases/${caseId}/runs/${runId}/summary`,
      icon: <SummarizeIcon fontSize="small" />,
      active: pathname.endsWith(`/runs/${runId}/summary`),
    },
    {
      key: "temporal",
      shortLabel: "Timeline",
      fullLabel: "Temporal View",
      href: `/cases/${caseId}/runs/${runId}/temporal`,
      icon: <TimelineIcon fontSize="small" />,
      active: pathname.endsWith(`/runs/${runId}/temporal`),
    },
    {
      key: "logs",
      shortLabel: "Logs",
      fullLabel: "Tabular Logs",
      href: `/cases/${caseId}/runs/${runId}/logs`,
      icon: <ArticleIcon fontSize="small" />,
      active: pathname.endsWith(`/runs/${runId}/logs`),
    },
    {
      key: "graph",
      shortLabel: "Graph",
      fullLabel: "Causal Graph",
      href: `/cases/${caseId}/runs/${runId}/causal-graph`,
      icon: <AccountTreeIcon fontSize="small" />,
      active: pathname.endsWith(`/runs/${runId}/causal-graph`),
    },
    {
      key: "rca",
      shortLabel: "RCA",
      fullLabel: "Causal Summary",
      href: `/cases/${caseId}/runs/${runId}/causal-summary`,
      icon: <FactCheckIcon fontSize="small" />,
      active: pathname.endsWith(`/runs/${runId}/causal-summary`),
    },
  ];
}

export function CaseAnalysisNav({
  caseId,
  runId,
  subtitle = "Navigate the workspace and report views for this run.",
  title = "Case analysis",
  variant = "card",
}: CaseAnalysisNavProps) {
  const pathname = usePathname();
  const items = analysisNavItems(caseId, runId, pathname);
  const card = variant === "card";

  return (
    <Box
      aria-label="Case analysis navigation"
      component="nav"
      sx={{
        background: card
          ? "linear-gradient(135deg, rgba(255,255,255,0.96), rgba(230,225,255,0.5))"
          : "transparent",
        border: card ? "1px solid rgba(91,92,246,0.12)" : 0,
        borderRadius: card ? "14px" : 0,
        boxShadow: card ? "0 18px 45px rgba(36,59,122,0.08)" : "none",
        p: card ? { xs: 1.5, md: 2 } : 0,
      }}
    >
      <Stack direction={{ xs: "column", lg: "row" }} spacing={1.5} sx={{ alignItems: { xs: "stretch", lg: "center" } }}>
        {(title || subtitle) && (
          <Box sx={{ flex: "1 1 220px", minWidth: 0 }}>
            {title && (
              <Typography component="h2" sx={{ fontWeight: 900, lineHeight: 1.2 }} variant="subtitle1">
                {title}
              </Typography>
            )}
            {subtitle && (
              <Typography color="text.secondary" sx={{ mt: 0.35 }} variant="body2">
                {subtitle}
              </Typography>
            )}
          </Box>
        )}
        <Stack
          aria-label="Analysis views"
          direction="row"
          sx={{
            bgcolor: "rgba(91,92,246,0.07)",
            border: "1px solid rgba(91,92,246,0.1)",
            borderRadius: "14px",
            flex: "0 1 auto",
            flexWrap: "wrap",
            gap: 0.75,
            justifyContent: { xs: "flex-start", lg: "flex-end" },
            minWidth: 0,
            p: 0.75,
          }}
        >
          {items.map((item) => (
            <Tooltip key={item.key} title={item.fullLabel}>
              <Box
                aria-current={item.active ? "page" : undefined}
                aria-label={item.fullLabel}
                component={Link}
                href={item.href}
                sx={{
                  alignItems: "center",
                  borderRadius: "12px",
                  display: "inline-flex",
                  gap: 0.85,
                  minHeight: 38,
                  px: 1.5,
                  textDecoration: "none",
                  transition: "background-color 160ms ease, box-shadow 160ms ease, color 160ms ease, transform 160ms ease",
                  ...(item.active
                    ? {
                        background: "linear-gradient(135deg, #5b5cf6, #8b5cf6)",
                        boxShadow: "0 12px 24px rgba(91,92,246,0.22)",
                        color: "#ffffff",
                      }
                    : {
                        bgcolor: "rgba(255,255,255,0.72)",
                        color: "text.secondary",
                        "&:hover": {
                          bgcolor: "rgba(91,92,246,0.08)",
                          color: "primary.dark",
                          transform: "translateY(-1px)",
                        },
                      }),
                }}
              >
                {item.icon}
                <Typography component="span" sx={{ color: "inherit", fontWeight: 850 }} variant="body2">
                  {item.shortLabel}
                </Typography>
              </Box>
            </Tooltip>
          ))}
        </Stack>
      </Stack>
    </Box>
  );
}
