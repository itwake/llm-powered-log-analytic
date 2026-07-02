"use client";

import AccountTreeIcon from "@mui/icons-material/AccountTree";
import AddCircleIcon from "@mui/icons-material/AddCircle";
import AdminPanelSettingsIcon from "@mui/icons-material/AdminPanelSettings";
import ArticleIcon from "@mui/icons-material/Article";
import ChevronLeftIcon from "@mui/icons-material/ChevronLeft";
import ChevronRightIcon from "@mui/icons-material/ChevronRight";
import FactCheckIcon from "@mui/icons-material/FactCheck";
import FolderOpenIcon from "@mui/icons-material/FolderOpen";
import InsightsIcon from "@mui/icons-material/Insights";
import SettingsIcon from "@mui/icons-material/Settings";
import SpaceDashboardIcon from "@mui/icons-material/SpaceDashboard";
import SummarizeIcon from "@mui/icons-material/Summarize";
import TimelineIcon from "@mui/icons-material/Timeline";
import Avatar from "@mui/material/Avatar";
import Box from "@mui/material/Box";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Chip from "@mui/material/Chip";
import CircularProgress from "@mui/material/CircularProgress";
import Divider from "@mui/material/Divider";
import IconButton from "@mui/material/IconButton";
import List from "@mui/material/List";
import ListItemButton from "@mui/material/ListItemButton";
import ListItemIcon from "@mui/material/ListItemIcon";
import ListItemText from "@mui/material/ListItemText";
import Stack from "@mui/material/Stack";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import { usePathname, useRouter } from "next/navigation";
import { ReactNode, useCallback, useEffect, useMemo, useState } from "react";
import Link from "@/components/Link";
import { authApi, casesApi } from "@/lib/api";
import type { CaseResponse, UserOut } from "@/lib/api";
import { loganTokens } from "@/theme";

interface ShellProps {
  children: ReactNode;
  caseId?: string;
  runId?: string;
  caseTitle?: string | null;
}

interface NavItemProps {
  href: string;
  icon: ReactNode;
  label: string;
  active: boolean;
  collapsed: boolean;
  abbr?: string;
}

function displayNameFromEmail(email: string | null | undefined): string | null {
  const localPart = email?.split("@", 1)[0]?.trim() || "";
  if (!localPart) {
    return null;
  }

  const parts = localPart
    .replace(/[_-]/g, ".")
    .split(".")
    .map((part) => part.trim())
    .filter(Boolean)
    .map((part) => `${part.slice(0, 1).toUpperCase()}${part.slice(1).toLowerCase()}`);

  return parts.length ? parts.join(" ") : null;
}

function navSx(collapsed: boolean) {
  return {
    borderRadius: 2,
    color: "#d9e3f5",
    minHeight: 40,
    justifyContent: collapsed ? "center" : "flex-start",
    px: collapsed ? 1.25 : 1.5,
    transition: "background-color 160ms ease, color 160ms ease, transform 160ms ease",
    "&:hover": {
      bgcolor: "rgba(255,255,255,0.08)",
      color: "#ffffff",
      transform: "translateX(2px)",
    },
    "&.Mui-selected": {
      bgcolor: "rgba(91, 92, 246, 0.28)",
      boxShadow: "inset 0 0 0 1px rgba(255,255,255,0.08)",
      color: "#ffffff",
      fontWeight: 800,
      "&:hover": {
        bgcolor: "rgba(91, 92, 246, 0.34)",
      },
    },
  };
}

function NavItem({ href, icon, label, active, collapsed, abbr }: NavItemProps) {
  return (
    <Tooltip disableHoverListener={!collapsed} placement="right" title={label}>
      <ListItemButton
        aria-current={active ? "page" : undefined}
        component={Link}
        href={href}
        selected={active}
        sx={navSx(collapsed)}
      >
        <ListItemIcon sx={{ color: "inherit", minWidth: collapsed ? 0 : 36 }}>
          {collapsed && abbr ? (
            <Typography component="span" sx={{ fontSize: 12, fontWeight: 850 }}>
              {abbr}
            </Typography>
          ) : (
            icon
          )}
        </ListItemIcon>
        {!collapsed && (
          <ListItemText
            primary={
              <Typography sx={{ fontWeight: active ? 800 : 650 }} variant="body2">
                {label}
              </Typography>
            }
          />
        )}
      </ListItemButton>
    </Tooltip>
  );
}

export function Shell({ children, caseId, runId, caseTitle }: ShellProps) {
  const pathname = usePathname();
  const router = useRouter();
  const [user, setUser] = useState<UserOut | null>(null);
  const [sidebarCases, setSidebarCases] = useState<CaseResponse[]>([]);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [casesLoading, setCasesLoading] = useState(false);
  const [authState, setAuthState] = useState<"loading" | "signed-in" | "signed-out">("loading");

  const routeContext = useMemo(() => {
    const [section, routeCaseId, runsSegment, routeRunId] = pathname.split("/").filter(Boolean);
    return {
      caseId: section === "cases" && routeCaseId && routeCaseId !== "new" ? routeCaseId : undefined,
      runId: section === "cases" && runsSegment === "runs" ? routeRunId : undefined,
    };
  }, [pathname]);

  const activeCaseId = caseId ?? routeContext.caseId;
  const activeRunId = runId ?? routeContext.runId;

  useEffect(() => {
    try {
      setSidebarCollapsed(window.localStorage.getItem("logan:sidebar-collapsed") === "true");
    } catch {
      setSidebarCollapsed(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    authApi
      .me()
      .then((response) => {
        if (!cancelled) {
          setUser(response.user);
          setAuthState("signed-in");
        }
      })
      .catch(() => {
        if (!cancelled) {
          setUser(null);
          setAuthState("signed-out");
          const nextPath = `${window.location.pathname}${window.location.search}`;
          router.replace(`/login?next=${encodeURIComponent(nextPath || "/cases")}`);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [router]);

  const loadSidebarCases = useCallback(() => {
    let cancelled = false;
    setCasesLoading(true);
    casesApi
      .list({ page_size: 30 })
      .then((response) => {
        if (!cancelled) {
          setSidebarCases(response.items);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setSidebarCases([]);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setCasesLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (authState !== "signed-in") {
      return undefined;
    }
    return loadSidebarCases();
  }, [activeCaseId, authState, loadSidebarCases]);

  const selectedCase = useMemo(
    () => sidebarCases.find((item) => item.case_id === activeCaseId) || null,
    [activeCaseId, sidebarCases],
  );

  useEffect(() => {
    function handleCaseSaved(event: Event) {
      const detail = (event as CustomEvent<CaseResponse>).detail;
      if (!detail?.case_id) {
        return;
      }
      setSidebarCases((current) => {
        const existing = current.findIndex((item) => item.case_id === detail.case_id);
        if (existing < 0) {
          return [detail, ...current];
        }
        const next = [...current];
        next[existing] = detail;
        return next;
      });
    }

    function handleCaseDeleted(event: Event) {
      const deletedCaseId = (event as CustomEvent<{ caseId?: string }>).detail?.caseId;
      if (!deletedCaseId) {
        return;
      }
      setSidebarCases((current) => current.filter((item) => item.case_id !== deletedCaseId));
    }

    window.addEventListener("logan:case-saved", handleCaseSaved);
    window.addEventListener("logan:case-deleted", handleCaseDeleted);
    return () => {
      window.removeEventListener("logan:case-saved", handleCaseSaved);
      window.removeEventListener("logan:case-deleted", handleCaseDeleted);
    };
  }, []);

  const reportLinks = useMemo(() => {
    const links: [string, string, string, ReactNode][] = [];
    if (activeCaseId && activeRunId) {
      links.push(
        ["Data Summary", `/cases/${activeCaseId}/runs/${activeRunId}/summary`, "DS", <SummarizeIcon key="summary" fontSize="small" />],
        ["Temporal View", `/cases/${activeCaseId}/runs/${activeRunId}/temporal`, "TV", <TimelineIcon key="timeline" fontSize="small" />],
        ["Tabular Logs", `/cases/${activeCaseId}/runs/${activeRunId}/logs`, "LG", <ArticleIcon key="logs" fontSize="small" />],
        ["Causal Graph", `/cases/${activeCaseId}/runs/${activeRunId}/causal-graph`, "CG", <AccountTreeIcon key="graph" fontSize="small" />],
        ["Causal Summary", `/cases/${activeCaseId}/runs/${activeRunId}/causal-summary`, "RC", <FactCheckIcon key="rca" fontSize="small" />],
      );
    }
    return links;
  }, [activeCaseId, activeRunId]);

  const signedInDisplayName = user?.username || displayNameFromEmail(user?.email) || "Signed in";
  const headerTitle =
    caseTitle ||
    selectedCase?.title ||
    selectedCase?.case_key ||
    (pathname === "/cases/new"
      ? "New Case"
      : pathname.startsWith("/settings/ai-platform")
        ? "AI Platform"
        : pathname.startsWith("/admin")
          ? "Admin"
          : pathname.startsWith("/cases")
            ? "Cases"
            : "Incident workbench");

  function isActive(href: string): boolean {
    return pathname === href;
  }

  function toggleSidebar() {
    setSidebarCollapsed((current) => {
      const next = !current;
      try {
        window.localStorage.setItem("logan:sidebar-collapsed", String(next));
      } catch {
        // Some browser modes block localStorage; the in-memory state is enough for the session.
      }
      return next;
    });
  }

  function caseDotColor(status: string): string {
    if (status === "ready" || status === "completed") {
      return "success.main";
    }
    if (status === "processing" || status === "uploading" || status === "queued") {
      return "warning.main";
    }
    if (status === "failed" || status === "cancelled") {
      return "error.main";
    }
    return "info.main";
  }

  const sidebarWidth = sidebarCollapsed ? 72 : 292;

  return (
    <Box
      sx={{
        bgcolor: "background.default",
        display: "grid",
        gridTemplateColumns: { xs: "1fr", md: `${sidebarWidth}px minmax(0, 1fr)` },
        minHeight: "100vh",
      }}
    >
      <Box
        component="aside"
        sx={{
          bgcolor: loganTokens.sidebarBg,
          borderBottom: { xs: 1, md: 0 },
          borderColor: loganTokens.sidebarBorder,
          borderRight: { md: 1 },
          display: "flex",
          flexDirection: "column",
          height: { xs: "auto", md: "100vh" },
          minWidth: 0,
          overflow: "hidden",
          position: { xs: "relative", md: "sticky" },
          top: 0,
          width: { xs: "100%", md: sidebarWidth },
          zIndex: 10,
        }}
      >
        <Stack
          direction="row"
          spacing={1}
          sx={{
            alignItems: "center",
            justifyContent: sidebarCollapsed ? "center" : "space-between",
            px: sidebarCollapsed ? 1 : 2,
            py: 2,
          }}
        >
          {!sidebarCollapsed && (
            <Stack
              component={Link}
              direction="row"
              href="/cases"
              spacing={1.25}
              sx={{ alignItems: "center", color: "#ffffff", textDecoration: "none" }}
            >
              <Box
                sx={{
                  alignItems: "center",
                  background: "linear-gradient(135deg, #5b5cf6, #06b6d4)",
                  borderRadius: 2,
                  boxShadow: "0 10px 24px rgba(6,182,212,0.25)",
                  display: "flex",
                  fontSize: 12,
                  fontWeight: 900,
                  height: 34,
                  justifyContent: "center",
                  width: 34,
                }}
              >
                LA
              </Box>
              <Box>
                <Typography sx={{ fontWeight: 900, lineHeight: 1 }} variant="h6">
                  LogAn
                </Typography>
                <Typography sx={{ color: loganTokens.sidebarMuted, fontSize: 11, fontWeight: 700 }}>
                  Incident Workbench
                </Typography>
              </Box>
            </Stack>
          )}
          {sidebarCollapsed && (
            <Box
              sx={{
                alignItems: "center",
                background: "linear-gradient(135deg, #5b5cf6, #06b6d4)",
                borderRadius: 2,
                color: "#ffffff",
                display: "flex",
                fontSize: 12,
                fontWeight: 900,
                height: 34,
                justifyContent: "center",
                width: 34,
              }}
            >
              LA
            </Box>
          )}
          <Tooltip title={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}>
            <IconButton
              aria-label={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
              aria-pressed={sidebarCollapsed}
              size="small"
              sx={{ color: "#d9e3f5", "&:hover": { bgcolor: "rgba(255,255,255,0.08)" } }}
              onClick={toggleSidebar}
            >
              {sidebarCollapsed ? <ChevronRightIcon fontSize="small" /> : <ChevronLeftIcon fontSize="small" />}
            </IconButton>
          </Tooltip>
        </Stack>

        <Box sx={{ flex: 1, minHeight: 0, overflowY: "auto", px: sidebarCollapsed ? 1 : 1.5, pb: 1.5 }}>
          <List aria-label="Primary" dense disablePadding sx={{ display: "grid", gap: 0.5 }}>
            <NavItem
              active={isActive("/cases/new")}
              collapsed={sidebarCollapsed}
              href="/cases/new"
              icon={<AddCircleIcon fontSize="small" />}
              label="New Case"
            />
            <NavItem
              active={isActive("/cases")}
              collapsed={sidebarCollapsed}
              href="/cases"
              icon={<FolderOpenIcon fontSize="small" />}
              label="All Cases"
            />
          </List>

          <Divider sx={{ borderColor: loganTokens.sidebarBorder, my: 1.5 }} />

          {!sidebarCollapsed && (
            <Typography sx={{ color: loganTokens.sidebarMuted, fontWeight: 850, letterSpacing: 0.8, px: 1.5, py: 0.75, textTransform: "uppercase" }} variant="caption">
              Cases
            </Typography>
          )}
          <List aria-label="Cases" dense disablePadding sx={{ display: "grid", gap: 0.5 }}>
            {casesLoading && sidebarCases.length === 0 && (
              <Stack direction="row" spacing={1} sx={{ alignItems: "center", color: loganTokens.sidebarMuted, px: 1.5, py: 1 }}>
                <CircularProgress size={14} sx={{ color: loganTokens.sidebarMuted }} />
                {!sidebarCollapsed && <Typography variant="body2">Loading cases</Typography>}
              </Stack>
            )}
            {!casesLoading && sidebarCases.length === 0 && !sidebarCollapsed && (
              <Typography sx={{ color: loganTokens.sidebarMuted, px: 1.5, py: 1 }} variant="body2">
                No cases yet
              </Typography>
            )}
            {sidebarCases.map((item) => {
              const href = `/cases/${item.case_id}`;
              const active = activeCaseId === item.case_id || pathname === href;
              const label = item.title || item.case_key;
              return (
                <Tooltip disableHoverListener={!sidebarCollapsed} key={item.case_id} placement="right" title={label}>
                  <ListItemButton
                    aria-current={active ? "page" : undefined}
                    component={Link}
                    href={href}
                    selected={active}
                    sx={navSx(sidebarCollapsed)}
                  >
                    <Box
                      aria-hidden="true"
                      sx={{
                        bgcolor: caseDotColor(item.status),
                        borderRadius: "999px",
                        boxShadow: "0 0 0 3px rgba(255,255,255,0.08)",
                        flex: "0 0 auto",
                        height: 9,
                        mr: sidebarCollapsed ? 0 : 1.5,
                        width: 9,
                      }}
                    />
                    {!sidebarCollapsed && (
                      <ListItemText
                        primary={
                          <Typography noWrap sx={{ fontWeight: active ? 800 : 650 }} variant="body2">
                            {label}
                          </Typography>
                        }
                      />
                    )}
                  </ListItemButton>
                </Tooltip>
              );
            })}
          </List>

          {reportLinks.length > 0 && (
            <>
              <Divider sx={{ borderColor: loganTokens.sidebarBorder, my: 1.5 }} />
              {!sidebarCollapsed && (
                <Typography sx={{ color: loganTokens.sidebarMuted, fontWeight: 850, letterSpacing: 0.8, px: 1.5, py: 0.75, textTransform: "uppercase" }} variant="caption">
                  Current analysis
                </Typography>
              )}
              <List aria-label="Analysis views" dense disablePadding sx={{ display: "grid", gap: 0.5 }}>
                <NavItem
                  active={Boolean(activeCaseId && isActive(`/cases/${activeCaseId}`))}
                  collapsed={sidebarCollapsed}
                  href={`/cases/${activeCaseId}`}
                  icon={<SpaceDashboardIcon fontSize="small" />}
                  label="Case Workspace"
                  abbr="W"
                />
                {reportLinks.map(([label, href, abbr, icon]) => (
                  <NavItem
                    active={isActive(href)}
                    collapsed={sidebarCollapsed}
                    href={href}
                    icon={icon}
                    key={`${label}-${href}`}
                    label={label}
                    abbr={abbr}
                  />
                ))}
              </List>
            </>
          )}

          <Divider sx={{ borderColor: loganTokens.sidebarBorder, my: 1.5 }} />
          {!sidebarCollapsed && (
            <Typography sx={{ color: loganTokens.sidebarMuted, fontWeight: 850, letterSpacing: 0.8, px: 1.5, py: 0.75, textTransform: "uppercase" }} variant="caption">
              Settings
            </Typography>
          )}
          <List aria-label="Settings" dense disablePadding sx={{ display: "grid", gap: 0.5 }}>
            <NavItem
              active={isActive("/settings/ai-platform")}
              collapsed={sidebarCollapsed}
              href="/settings/ai-platform"
              icon={<SettingsIcon fontSize="small" />}
              label="AI Platform"
              abbr="AI"
            />
            {user?.role === "admin" && (
              <NavItem
                active={isActive("/admin")}
                collapsed={sidebarCollapsed}
                href="/admin"
                icon={<AdminPanelSettingsIcon fontSize="small" />}
                label="Admin"
                abbr="A"
              />
            )}
          </List>
        </Box>

        <Divider sx={{ borderColor: loganTokens.sidebarBorder }} />
        <Stack direction="row" spacing={1.25} sx={{ alignItems: "center", px: sidebarCollapsed ? 1 : 2, py: 1.5 }}>
          <Avatar sx={{ background: "linear-gradient(135deg, #5b5cf6, #06b6d4)", fontSize: 13, fontWeight: 850, height: 36, width: 36 }}>
            {signedInDisplayName.slice(0, 2).toUpperCase()}
          </Avatar>
          {!sidebarCollapsed && (
            <Box sx={{ minWidth: 0 }}>
              <Typography noWrap sx={{ color: "#ffffff", fontWeight: 800 }} variant="body2">
                {signedInDisplayName}
              </Typography>
              <Typography noWrap sx={{ color: loganTokens.sidebarMuted }} variant="caption">
                AI Platform
              </Typography>
            </Box>
          )}
        </Stack>
      </Box>

      <Box sx={{ display: "flex", flexDirection: "column", minWidth: 0 }}>
        <Box
          component="header"
          sx={{
            alignItems: "center",
            backdropFilter: "blur(10px)",
            bgcolor: "rgba(243, 245, 255, 0.72)",
            borderBottom: "1px solid rgba(91,92,246,0.08)",
            display: "flex",
            gap: 2,
            justifyContent: "space-between",
            minHeight: 64,
            px: { xs: 2, md: 3.5 },
            position: "sticky",
            top: 0,
            zIndex: 9,
          }}
        >
          <Typography component="div" noWrap sx={{ fontWeight: 800 }} variant="subtitle1">
            {headerTitle}
          </Typography>
          <Box sx={{ flex: "0 0 auto" }}>
            {authState === "loading" && <Chip color="default" label="Checking session" variant="outlined" />}
            {authState === "signed-in" && <Chip icon={<InsightsIcon />} label="AI Platform" variant="outlined" />}
            {authState === "signed-out" && (
              <Chip component={Link} clickable href="/login" label="Continue with SSO" variant="outlined" />
            )}
          </Box>
        </Box>
        <Box
          component="main"
          sx={{
            mx: "auto",
            p: { xs: 2.25, md: 3.5 },
            width: "100%",
            maxWidth: 1440,
          }}
        >
          {children}
        </Box>
      </Box>
    </Box>
  );
}

export function Metric({ label, value }: { label: string; value: string }) {
  return (
    <Card sx={{ border: "1px solid rgba(91,92,246,0.1)", borderRadius: 4, overflow: "hidden" }}>
      <CardContent sx={{ p: 2.5, position: "relative", "&:last-child": { pb: 2.5 } }}>
        <Box
          sx={{
            bgcolor: "primary.main",
            borderRadius: "999px",
            height: 8,
            left: 18,
            position: "absolute",
            top: 16,
            width: 36,
          }}
        />
        <Stack spacing={0.75}>
          <Typography color="text.secondary" sx={{ pt: 1.25 }} variant="body2">
            {label}
          </Typography>
          <Typography component="strong" sx={{ fontWeight: 850 }} variant="h5">
            {value}
          </Typography>
        </Stack>
      </CardContent>
    </Card>
  );
}
