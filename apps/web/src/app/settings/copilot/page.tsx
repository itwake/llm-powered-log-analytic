import { Shell } from "@/components/Shell";

export default function CopilotSettingsPage() {
  return (
    <Shell>
      <div className="toolbar">
        <h1>Copilot Settings</h1>
        <button className="button">Connect GitHub Copilot</button>
      </div>
      <section className="grid two">
        <div className="panel">
          <h2>Status</h2>
          <p><span className="pill green">connected</span></p>
          <p className="muted">Runtime type: github_copilot. Token values are never displayed.</p>
        </div>
        <div className="panel">
          <h2>Device Code</h2>
          <p><strong>LOGAN-TEST</strong></p>
          <p className="muted">Open the GitHub device page and enter the code. Polling uses the backend check endpoint.</p>
        </div>
      </section>
    </Shell>
  );
}
