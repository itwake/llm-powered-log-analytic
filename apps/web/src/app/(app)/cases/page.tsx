"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { CaseListResponse, casesApi } from "@/lib/api";
import { apiErrorMessage, formatDateTime, valueLabel } from "@/lib/format";
import { Badge, Card, EmptyState, SkeletonBlock, statusTone } from "@/components/ui";

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
    <div className="page-stack">
        <section className="page-hero compact">
          <div>
            <span className="eyebrow">Incident queue</span>
            <h1>Cases</h1>
            <p>Open incidents, active analyses, and completed reports.</p>
          </div>
          <Link className="button" href="/cases/new">New case</Link>
        </section>

        <form className="tool-strip toolbar" onSubmit={submit}>
          <label className="inline-field">
            Status
            <select value={status} onChange={(event) => setStatus(event.target.value)}>
              <option value="">Any</option>
              <option value="created">Created</option>
              <option value="uploading">Uploading</option>
              <option value="processing">Processing</option>
              <option value="ready">Ready</option>
              <option value="failed">Failed</option>
              <option value="cancelled">Cancelled</option>
            </select>
          </label>
          <label className="inline-field">
            Product
            <input value={product} onChange={(event) => setProduct(event.target.value)} />
          </label>
          <button className="button secondary" disabled={loading} type="submit">Apply</button>
        </form>

        {error && <div className="alert error">{error}</div>}

        {loading && (
          <section className="case-card-grid">
            <Card><SkeletonBlock lines={4} /></Card>
            <Card><SkeletonBlock lines={4} /></Card>
            <Card><SkeletonBlock lines={4} /></Card>
          </section>
        )}

        {!loading && data && data.items.length === 0 && (
          <Card>
            <EmptyState title="No cases found">
              <Link className="button secondary" href="/cases/new">Create a case</Link>
            </EmptyState>
          </Card>
        )}

        {!loading && data && data.items.length > 0 && (
          <section className="case-card-grid">
            {data.items.map((item) => (
              <Link className="case-card panel" href={`/cases/${item.case_id}`} key={item.case_id}>
                <div className="case-card-header">
                  <span className="eyebrow">{item.case_key}</span>
                  <Badge tone={statusTone(item.status)}>{item.status}</Badge>
                </div>
                <h2>{valueLabel(item.title)}</h2>
                <dl className="case-card-meta">
                  <dt>Product</dt>
                  <dd>{valueLabel(item.product)}</dd>
                  <dt>Service</dt>
                  <dd>{valueLabel(item.service)}</dd>
                  <dt>Incident start</dt>
                  <dd>{formatDateTime(item.incident_start)}</dd>
                </dl>
                <span className="case-card-cta">Open workspace</span>
              </Link>
            ))}
          </section>
        )}
    </div>
  );
}
