"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { ReactNode, useCallback, useEffect, useMemo, useState } from "react";
import { authApi, casesApi } from "@/lib/api";
import type { CaseResponse, UserOut } from "@/lib/api";

interface ShellProps {
  children: ReactNode;
  caseId?: string;
  runId?: string;
  caseTitle?: string | null;
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

export function Shell({children, caseId, runId, caseTitle}: ShellProps) {
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
      .list({page_size: 30})
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
      const deletedCaseId = (event as CustomEvent<{caseId?: string}>).detail?.caseId;
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
    const links: [string, string, string][] = [];
    if (activeCaseId && activeRunId) {
      links.push(
        ["Data Summary", `/cases/${activeCaseId}/runs/${activeRunId}/summary`, "DS"],
        ["Temporal View", `/cases/${activeCaseId}/runs/${activeRunId}/temporal`, "TV"],
        ["Tabular Logs", `/cases/${activeCaseId}/runs/${activeRunId}/logs`, "LG"],
        ["Causal Graph", `/cases/${activeCaseId}/runs/${activeRunId}/causal-graph`, "CG"],
        ["Causal Summary", `/cases/${activeCaseId}/runs/${activeRunId}/causal-summary`, "RC"],
      );
    }
    return links;
  }, [activeCaseId, activeRunId]);

  const signedInDisplayName = displayNameFromEmail(user?.email) || user?.username || "Signed in";
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

  function caseTone(status: string): string {
    if (status === "ready" || status === "completed") {
      return "success";
    }
    if (status === "processing" || status === "uploading" || status === "queued") {
      return "warning";
    }
    if (status === "failed" || status === "cancelled") {
      return "danger";
    }
    return "info";
  }

  return (
    <div className={`app-shell ${sidebarCollapsed ? "sidebar-collapsed" : ""}`}>
      <aside className="app-sidebar sidebar">
        <div className="app-sidebar-scroll">
          <div className="app-sidebar-header">
            <Link href="/cases" className="brand app-brand">LogAn</Link>
            <button
              aria-label={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
              aria-pressed={sidebarCollapsed}
              className="app-sidebar-toggle"
              title={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
              type="button"
              onClick={toggleSidebar}
            >
              <span className="sidebar-toggle-icon" aria-hidden="true" />
            </button>
          </div>

          <nav className="app-primary-actions" aria-label="Primary">
            <Link
              className="app-action-link new-case"
              href="/cases/new"
              title="New Case"
            >
              <span className="app-action-glyph compose" aria-hidden="true" />
              <span className="app-action-label">New Case</span>
            </Link>
            <Link
              className={`app-action-link ${isActive("/cases") ? "active" : ""}`}
              href="/cases"
              title="All Cases"
            >
              <span className="app-action-glyph cases" aria-hidden="true" />
              <span className="app-action-label">All Cases</span>
            </Link>
          </nav>

          <section className="app-sidebar-section">
            <div className="app-section-title">Cases</div>
            <nav className="case-thread-list" aria-label="Cases">
              {casesLoading && sidebarCases.length === 0 && (
                <div className="case-thread-empty">Loading cases</div>
              )}
              {!casesLoading && sidebarCases.length === 0 && (
                <div className="case-thread-empty">No cases yet</div>
              )}
              {sidebarCases.map((item) => {
                const href = `/cases/${item.case_id}`;
                const active = activeCaseId === item.case_id || pathname === href;
                return (
                  <Link
                    aria-current={active ? "page" : undefined}
                    className={`case-thread-link ${active ? "active" : ""}`}
                    href={href}
                    key={item.case_id}
                    title={item.title || item.case_key}
                  >
                    <span className={`case-status-dot ${caseTone(item.status)}`} aria-hidden="true" />
                    <span className="case-thread-title">{item.title || item.case_key}</span>
                  </Link>
                );
              })}
            </nav>
          </section>

          {reportLinks.length > 0 && (
            <section className="app-sidebar-section">
              <div className="app-section-title">Current analysis</div>
              <nav className="app-nav" aria-label="Analysis views">
                <Link
                  className={`app-nav-link ${activeCaseId && isActive(`/cases/${activeCaseId}`) ? "active" : ""}`}
                  href={`/cases/${activeCaseId}`}
                  title="Case Workspace"
                >
                  <span className="app-nav-abbr" aria-hidden="true">W</span>
                  <span className="app-nav-text">Case Workspace</span>
                </Link>
                {reportLinks.map(([label, href, abbr]) => (
                  <Link
                    aria-current={isActive(href) ? "page" : undefined}
                    className={`app-nav-link ${isActive(href) ? "active" : ""}`}
                    key={`${label}-${href}`}
                    href={href}
                    title={label}
                  >
                    <span className="app-nav-abbr" aria-hidden="true">{abbr}</span>
                    <span className="app-nav-text">{label}</span>
                  </Link>
                ))}
              </nav>
            </section>
          )}

          <section className="app-sidebar-section">
            <div className="app-section-title">Settings</div>
            <nav className="app-nav" aria-label="Settings">
              <Link
                className={`app-nav-link ${isActive("/settings/ai-platform") ? "active" : ""}`}
                href="/settings/ai-platform"
                title="AI Platform"
              >
                <span className="app-nav-abbr" aria-hidden="true">AI</span>
                <span className="app-nav-text">AI Platform</span>
              </Link>
              {user?.role === "admin" && (
                <Link
                  className={`app-nav-link ${isActive("/admin") ? "active" : ""}`}
                  href="/admin"
                  title="Admin"
                >
                  <span className="app-nav-abbr" aria-hidden="true">A</span>
                  <span className="app-nav-text">Admin</span>
                </Link>
              )}
            </nav>
          </section>
        </div>

        <div className="app-sidebar-user">
          <span className="app-user-avatar">{signedInDisplayName.slice(0, 2).toUpperCase()}</span>
          <span>
            <strong>{signedInDisplayName}</strong>
            <small>AI Platform</small>
          </span>
        </div>
      </aside>
      <div className="app-frame layout">
        <header className="app-header topbar">
          <div className="app-header-title topbar-title">{headerTitle}</div>
          <div className="app-header-status status">
            {authState === "loading" && "Checking session"}
            {authState === "signed-in" && `${signedInDisplayName} - AI Platform`}
            {authState === "signed-out" && <Link href="/login">Continue with SSO</Link>}
          </div>
        </header>
        <main className="main app-main">{children}</main>
      </div>
    </div>
  );
}

export function Metric({label, value}: {label: string; value: string}) {
  return (
    <div className="panel metric">
      <span className="muted">{label}</span>
      <strong>{value}</strong>
    </div>
  );
}
