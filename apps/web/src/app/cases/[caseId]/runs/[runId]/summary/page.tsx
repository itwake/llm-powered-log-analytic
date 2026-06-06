"use client";

import { useParams } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";
import { reportsApi, SummaryResponse } from "@/lib/api";
import { apiErrorMessage, formatDateTime, formatPercent, valueLabel } from "@/lib/format";
import { Metric, Shell } from "@/components/Shell";

function signalClass(signal: string): string {
  if (signal === "error") {
    return "red";
  }
  if (signal === "availability" || signal === "saturation") {
    return "amber";
  }
  return "blue";
}

export default function SummaryPage() {
  const {caseId, runId} = useParams<{caseId: string; runId: string}>();
  const [data, setData] = useState<SummaryResponse | null>(null);
  const [goldenSignal, setGoldenSignal] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function load(signal = goldenSignal) {
    setLoading(true);
    setError(null);
    try {
      const response = await reportsApi.summary(caseId, runId, {
        golden_signal: signal || undefined,
        limit: 100,
      });
      setData(response);
    } catch (caught) {
      setError(apiErrorMessage(caught));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load("");
  }, [caseId, runId]);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void load();
  }

  return (
    <Shell caseId={caseId} runId={runId}>
      <form className="toolbar" onSubmit={submit}>
        <h1>Data Summary</h1>
        <label className="inline-field">
          Signal
          <select value={goldenSignal} onChange={(event) => setGoldenSignal(event.target.value)}>
            <option value="">All offending</option>
            <option value="error">Error</option>
            <option value="availability">Availability</option>
            <option value="latency">Latency</option>
            <option value="saturation">Saturation</option>
            <option value="traffic">Traffic</option>
          </select>
        </label>
        <button className="button secondary" disabled={loading} type="submit">Apply</button>
      </form>

      {error && <div className="alert error">{error}</div>}
      <section className="grid three">
        <Metric label="Raw lines" value={data ? String(data.reduction.raw_log_lines) : "n/a"} />
        <Metric label="Offending templates" value={data ? String(data.reduction.offending_templates) : "n/a"} />
        <Metric
          label="Review reduction"
          value={data ? formatPercent(data.reduction.estimated_review_reduction) : "n/a"}
        />
      </section>

      <section className="panel" style={{marginTop: 14}}>
        {loading && <div className="empty">Loading summary</div>}
        {!loading && data && data.items.length === 0 && <div className="empty">No summary rows</div>}
        {!loading && data && data.items.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Signal</th>
                  <th>Representative log</th>
                  <th>Count</th>
                  <th>Service</th>
                  <th>First seen</th>
                  <th>Confidence</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((item) => (
                  <tr key={item.template_id}>
                    <td><span className={`pill ${signalClass(item.golden_signal)}`}>{item.golden_signal}</span></td>
                    <td>
                      {item.representative_message}
                      <br />
                      <span className="muted">{item.fault_categories.join(", ") || "uncategorized"}</span>
                    </td>
                    <td>{item.occurrence_count}</td>
                    <td>{item.services.map(valueLabel).join(", ")}</td>
                    <td>{formatDateTime(item.first_seen)}</td>
                    <td>{formatPercent(item.confidence)}</td>
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
