"use client";

import Link from "next/link";
import { ReactNode, useEffect, useMemo, useState } from "react";
import { authApi, UserOut } from "@/lib/api";

interface ShellProps {
  children: ReactNode;
  caseId?: string;
  runId?: string;
  caseTitle?: string | null;
}

export function Shell({children, caseId, runId, caseTitle}: ShellProps) {
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
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

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
    links.push(["Copilot", "/settings/copilot"]);
    return links;
  }, [caseId, runId]);

  const copilotStatus = user?.has_copilot_credential ? "Copilot connected" : "Copilot disconnected";

  return (
    <>
      <header className="topbar">
        <Link href="/cases" className="brand">LogAn</Link>
        <span className="topbar-title">{caseTitle || "Incident workbench"}</span>
        <span className="status">
          {authState === "loading" && "Checking session"}
          {authState === "signed-in" && `${user?.username || "Signed in"} · ${copilotStatus}`}
          {authState === "signed-out" && <Link href="/login">Sign in</Link>}
        </span>
      </header>
      <div className="layout">
        <nav className="sidebar">
          {nav.map(([label, href]) => (
            <Link key={href} href={href}>{label}</Link>
          ))}
        </nav>
        <main className="main">{children}</main>
      </div>
    </>
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
