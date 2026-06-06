import { Metric, Shell } from "@/components/Shell";
import { summaryItems } from "@/lib/fixtures";

export default function SummaryPage() {
  return (
    <Shell>
      <div className="toolbar">
        <h1>Data Summary</h1>
        <select><option>All offending signals</option></select>
        <select><option>All services</option></select>
      </div>
      <section className="grid three">
        <Metric label="Templates" value="6" />
        <Metric label="Offending templates" value="3" />
        <Metric label="Model calls" value="6" />
      </section>
      <section className="panel" style={{marginTop: 14}}>
        <table>
          <thead><tr><th>Signal</th><th>Representative log</th><th>Count</th><th>Service</th><th>Confidence</th></tr></thead>
          <tbody>
            {summaryItems.map(item => (
              <tr key={item.template_id}>
                <td><span className={item.golden_signal === "error" ? "pill red" : "pill amber"}>{item.golden_signal}</span></td>
                <td>{item.representative_message}<br /><span className="muted">{item.fault_categories.join(", ")}</span></td>
                <td>{item.occurrence_count}</td>
                <td>{item.services.join(", ")}</td>
                <td>{item.confidence}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </Shell>
  );
}
