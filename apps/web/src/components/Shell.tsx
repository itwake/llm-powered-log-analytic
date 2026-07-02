"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { ReactNode, useEffect, useMemo, useState } from "react";
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
  const [casesLoading, setCasesLoading] = useState(false);
  const [authState, setAuthState] = useState<"loading" | "signed-in" | "signed-out">("loading");

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

  useEffect(() => {
    if (authState !== "signed-in") {
      return;
    }
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
  }, [authState, pathname]);

  const reportLinks = useMemo(() => {
    const links: [string, string][] = [];
    if (caseId && runId) {
      links.push(
        ["Data Summary", `/cases/${caseId}/runs/${runId}/summary`],
        ["Temporal View", `/cases/${caseId}/runs/${runId}/temporal`],
        ["Tabular Logs", `/cases/${caseId}/runs/${runId}/logs`],
        ["Causal Graph", `/cases/${caseId}/runs/${runId}/causal-graph`],
        ["Causal Summary", `/cases/${caseId}/runs/${runId}/causal-summary`],
      );
    }
    return links;
  }, [caseId, runId]);

  const signedInDisplayName = displayNameFromEmail(user?.email) || user?.username || "Signed in";

  function isActive(href: string): boolean {
    return pathname === href;
  }

  function caseTone(status: string): string {
    if (status === "ready" || status === "completed") {
      return "success";
    }
    if (status === "processing" || status === "uploading" || status === "queued") {
      return "warning";
    }
    if (status === "failed") {
      return "danger";
    }
    return "info";
  }

  return (
    <div className="app-shell">
      <aside className="app-sidebar sidebar">
        <div className="app-sidebar-scroll">
          <div className="app-sidebar-header">
            <Link href="/cases" className="brand app-brand">LogAn</Link>
            <span className="app-sidebar-toggle" aria-hidden="true">▣</span>
          </div>

          <nav className="app-primary-actions" aria-label="Primary">
            <Link className="app-action-link new-case" href="/cases/new">
              <span className="app-action-icon" aria-hidden="true">✎</span>
              <span>New Case</span>
            </Link>
            <Link className={`app-action-link ${isActive("/cases") ? "active" : ""}`} href="/cases">
              <span className="app-action-icon" aria-hidden="true">⌕</span>
              <span>All Cases</span>
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
                const active = caseId === item.case_id || pathname === href;
                return (
                  <Link
                    aria-current={active ? "page" : undefined}
                    className={`case-thread-link ${active ? "active" : ""}`}
                    href={href}
                    key={item.case_id}
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
                  className={`app-nav-link ${caseId && isActive(`/cases/${caseId}`) ? "active" : ""}`}
                  href={`/cases/${caseId}`}
                >
                  Case Workspace
                </Link>
                {reportLinks.map(([label, href]) => (
                  <Link
                    aria-current={isActive(href) ? "page" : undefined}
                    className={`app-nav-link ${isActive(href) ? "active" : ""}`}
                    key={`${label}-${href}`}
                    href={href}
                  >
                    {label}
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
              >
                AI Platform
              </Link>
              {user?.role === "admin" && (
                <Link className={`app-nav-link ${isActive("/admin") ? "active" : ""}`} href="/admin">
                  Admin
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
          <div className="app-header-title topbar-title">{caseTitle || "Incident workbench"}</div>
          <div className="app-header-status status">
            {authState === "loading" && "Checking session"}
            {authState === "signed-in" && `${signedInDisplayName} · AI Platform`}
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
