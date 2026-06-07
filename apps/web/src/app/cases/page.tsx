"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { CaseListResponse, casesApi } from "@/lib/api";
import { apiErrorMessage, formatDateTime, valueLabel } from "@/lib/format";
import { Shell } from "@/components/Shell";

function statusClass(status: string): string {
  if (status === "ready" || status === "completed") {
    return "green";
  }
  if (status === "failed") {
    return "red";
  }
  if (status === "processing" || status === "uploading") {
    return "amber";
  }
  return "blue";
}

export default function CasesPage() {
  const [data, setData] = useState<CaseListResponse | null>(null);
  const [status, setStatus] = useState("");
  const [product, setProduct] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function load(nextStatus = status, nextProduct = product) {
    setLoading(true);
    setError(null);
    try {
      const response = await casesApi.list({
        status: nextStatus || undefined,
        product: nextProduct || undefined,
        page_size: 50,
      });
      setData(response);
    } catch (caught) {
      setError(apiErrorMessage(caught));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load("", "");
  }, []);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void load();
  }

  return (
    <Shell>
      <div className="toolbar">
        <h1>Cases</h1>
        <Link className="button" href="/cases/new">New case</Link>
      </div>

      <form className="toolbar" onSubmit={submit}>
        <label className="inline-field">
          Status
          <select value={status} onChange={(event) => setStatus(event.target.value)}>
            <option value="">Any</option>
            <option value="created">Created</option>
            <option value="uploading">Uploading</option>
            <option value="processing">Processing</option>
            <option value="ready">Ready</option>
            <option value="failed">Failed</option>
          </select>
        </label>
        <label className="inline-field">
          Product
          <input value={product} onChange={(event) => setProduct(event.target.value)} />
        </label>
        <button className="button secondary" disabled={loading} type="submit">Apply</button>
      </form>

      {error && <div className="alert error">{error}</div>}
      <section className="panel">
        {loading && <div className="empty">Loading cases</div>}
        {!loading && data && data.items.length === 0 && <div className="empty">No cases found</div>}
        {!loading && data && data.items.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Case</th>
                  <th>Product</th>
                  <th>Service</th>
                  <th>Status</th>
                  <th>Incident start</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((item) => (
                  <tr key={item.case_id}>
                    <td>
                      <Link href={`/cases/${item.case_id}`}>
                        {item.case_key} {valueLabel(item.title)}
                      </Link>
                    </td>
                    <td>{valueLabel(item.product)}</td>
                    <td>{valueLabel(item.service)}</td>
                    <td><span className={`pill ${statusClass(item.status)}`}>{item.status}</span></td>
                    <td>{formatDateTime(item.incident_start)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </Shell>
  );
}
