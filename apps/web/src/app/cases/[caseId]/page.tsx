import Link from "next/link";
import { Metric, Shell } from "@/components/Shell";
import { runId, summaryItems } from "@/lib/fixtures";

export default function CaseWorkspacePage() {
  return (
    <Shell>
      <div className="toolbar">
        <h1>Case Workspace</h1>
        <Link className="button" href={`runs/${runId}/summary`}>Open Data Summary</Link>
      </div>
      <section className="grid three">
        <Metric label="Raw lines" value="9" />
        <Metric label="Offending templates" value={String(summaryItems.length)} />
        <Metric label="Review reduction" value="66.7%" />
      </section>
      <section className="panel" style={{marginTop: 14}}>
        <h2>Processing</h2>
        <table>
          <tbody>
            {["File scan", "Parsing and redaction", "Drain templating", "Representative sampling", "Copilot annotation", "Temporal aggregation", "Causal inference"].map(step => (
              <tr key={step}><td>{step}</td><td><span className="pill green">complete</span></td></tr>
            ))}
          </tbody>
        </table>
      </section>
    </Shell>
  );
}
