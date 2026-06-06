import Link from "next/link";
import { ReactNode } from "react";
import { caseId, runId } from "@/lib/fixtures";

const nav = [
  ["Overview", `/cases/${caseId}`],
  ["Data Summary", `/cases/${caseId}/runs/${runId}/summary`],
  ["Temporal View", `/cases/${caseId}/runs/${runId}/temporal`],
  ["Tabular Logs", `/cases/${caseId}/runs/${runId}/logs`],
  ["Causal Graph", `/cases/${caseId}/runs/${runId}/causal-graph`],
  ["Causal Summary", `/cases/${caseId}/runs/${runId}/causal-summary`],
  ["Copilot", "/settings/copilot"]
];

export function Shell({children}: {children: ReactNode}) {
  return (
    <>
      <header className="topbar">
        <Link href="/cases" className="brand">LogAn</Link>
        <span>Checkout API intermittent 500 errors</span>
        <span className="status">Copilot: connected</span>
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
