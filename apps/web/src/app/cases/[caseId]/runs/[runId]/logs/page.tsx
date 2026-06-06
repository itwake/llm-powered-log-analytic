import { Shell } from "@/components/Shell";
import { logs } from "@/lib/fixtures";

export default function LogsPage() {
  return (
    <Shell>
      <div className="toolbar">
        <h1>Tabular Logs</h1>
        <input placeholder="Search redacted logs" defaultValue="timeout" />
        <select><option>Redacted</option><option>Raw</option><option>Template</option></select>
      </div>
      <section className="panel">
        <table>
          <thead><tr><th>Time</th><th>Level</th><th>Service</th><th>Evidence</th><th>Message</th></tr></thead>
          <tbody>
            {logs.map(item => (
              <tr key={`${item.file_path}-${item.line_number}`}>
                <td>{item.timestamp}</td>
                <td>{item.level}</td>
                <td>{item.service}</td>
                <td>{item.file_path}:{item.line_number}</td>
                <td>{item.message}<br /><span className="muted">{item.golden_signal}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </Shell>
  );
}
