import Link from "next/link";
import { Shell } from "@/components/Shell";
import { caseId } from "@/lib/fixtures";

export default function NewCasePage() {
  return (
    <Shell>
      <h1>New Case</h1>
      <section className="grid two">
        <form className="panel">
          <label className="field">Title<input defaultValue="Checkout API intermittent 500 errors" /></label>
          <label className="field">Issue description<textarea defaultValue="Customers report intermittent 500 during checkout after deployment." /></label>
          <label className="field">Product<input defaultValue="commerce-platform" /></label>
          <label className="field">Service<input defaultValue="checkout" /></label>
          <label className="field">Environment<input defaultValue="production" /></label>
          <Link className="button" href={`/cases/${caseId}`}>Create and open</Link>
        </form>
        <div className="panel">
          <h2>Upload</h2>
          <p className="muted">Drop .log, .txt, .jsonl, .zip, .gz, .tar, or .tgz files. The backend stores evidence refs for file path and line number.</p>
          <button className="button secondary">Select files</button>
        </div>
      </section>
    </Shell>
  );
}
