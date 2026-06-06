import { Shell } from "@/components/Shell";
import { summaryMarkdown } from "@/lib/fixtures";

export default function CausalSummaryPage() {
  return (
    <Shell>
      <div className="toolbar">
        <h1>Causal Summary</h1>
        <button className="button">Export Markdown</button>
        <button className="button secondary">Export HTML</button>
        <button className="button secondary">Export JSON</button>
      </div>
      <section className="grid two">
        <textarea className="panel" style={{minHeight: 460}} defaultValue={summaryMarkdown} />
        <div className="panel">
          <h2>Feedback</h2>
          <label className="field">Rating<select><option>Useful</option><option>Needs correction</option></select></label>
          <label className="field">Comment<textarea placeholder="Add validation notes" /></label>
          <button className="button">Submit feedback</button>
          <h2>Next Actions</h2>
          <label><input type="checkbox" /> Validate auth-service pool saturation</label><br />
          <label><input type="checkbox" /> Confirm payment timeout propagation</label>
        </div>
      </section>
    </Shell>
  );
}
