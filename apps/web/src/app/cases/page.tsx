import Link from "next/link";
import { Shell } from "@/components/Shell";
import { cases } from "@/lib/fixtures";

export default function CasesPage() {
  return (
    <Shell>
      <div className="toolbar">
        <h1>Cases</h1>
        <Link className="button" href="/cases/new">New case</Link>
      </div>
      <section className="panel">
        <table>
          <thead><tr><th>Case</th><th>Product</th><th>Service</th><th>Status</th></tr></thead>
          <tbody>
            {cases.map(item => (
              <tr key={item.case_id}>
                <td><Link href={`/cases/${item.case_id}`}>{item.case_key} {item.title}</Link></td>
                <td>{item.product}</td>
                <td>{item.service}</td>
                <td><span className="pill green">{item.status}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </Shell>
  );
}
