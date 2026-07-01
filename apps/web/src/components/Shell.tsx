"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { ReactNode, useEffect, useMemo, useState } from "react";
import { authApi, UserOut } from "@/lib/api";

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

  const nav = useMemo(() => {
    const links: [string, string][] = [
      ["Cases", "/cases"],
      ["New Case", "/cases/new"],
    ];
    if (caseId) {
      links.push(["Case Workspace", `/cases/${caseId}`]);
    }
    if (caseId && runId) {
      links.push(
        ["Data Summary", `/cases/${caseId}/runs/${runId}/summary`],
        ["Temporal View", `/cases/${caseId}/runs/${runId}/temporal`],
        ["Tabular Logs", `/cases/${caseId}/runs/${runId}/logs`],
        ["Causal Graph", `/cases/${caseId}/runs/${runId}/causal-graph`],
        ["Causal Summary", `/cases/${caseId}/runs/${runId}/causal-summary`],
      );
    }
    links.push(["AI Platform", "/settings/ai-platform"]);
    if (user?.role === "admin") {
      links.push(["Admin", "/admin"]);
    }
    return links;
  }, [caseId, runId, user?.role]);

  const signedInDisplayName = displayNameFromEmail(user?.email) || user?.username || "Signed in";

  function isActive(href: string): boolean {
    return pathname === href || pathname.startsWith(`${href}/`);
  }

  return (
    <div className="app-shell">
      <aside className="app-sidebar sidebar">
        <div className="app-sidebar-header">
          <Link href="/cases" className="brand app-brand">LogAn</Link>
          <div className="app-subtitle">Incident Copilot</div>
        </div>
        <nav className="app-nav" aria-label="Primary">
          {nav.map(([label, href]) => {
            const active = isActive(href);
            return (
              <Link
                aria-current={active ? "page" : undefined}
                className={`app-nav-link ${active ? "active" : ""}`}
                key={`${label}-${href}`}
                href={href}
              >
                {label}
              </Link>
            );
          })}
        </nav>
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
