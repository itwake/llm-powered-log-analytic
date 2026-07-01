"use client";

import { useParams } from "next/navigation";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { LogsResponse, reportsApi } from "@/lib/api";
import { apiErrorMessage, formatDateTime, valueLabel } from "@/lib/format";
import { Shell } from "@/components/Shell";

function signalClass(signal: string): string {
  if (signal === "error") {
    return "red";
  }
  if (signal === "availability" || signal === "saturation") {
    return "amber";
  }
  return "blue";
}

export default function LogsPage() {
  const {caseId, runId} = useParams<{caseId: string; runId: string}>();
  const [data, setData] = useState<LogsResponse | null>(null);
  const [keyword, setKeyword] = useState("");
  const [service, setService] = useState("");
  const [windowStart, setWindowStart] = useState("");
  const [windowEnd, setWindowEnd] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function load(
    nextKeyword = keyword,
    nextService = service,
    nextWindowStart = windowStart,
    nextWindowEnd = windowEnd,
  ) {
    setLoading(true);
    setError(null);
    try {
      const response = await reportsApi.logs(caseId, runId, {
        q: nextKeyword || undefined,
        service: nextService || undefined,
        window_start: nextWindowStart || undefined,
        window_end: nextWindowEnd || undefined,
        limit: 200,
      });
      setData(response);
    } catch (caught) {
      setError(apiErrorMessage(caught));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const nextWindowStart = params.get("window_start") || "";
    const nextWindowEnd = params.get("window_end") || "";
    setWindowStart(nextWindowStart);
    setWindowEnd(nextWindowEnd);
    void load("", "", nextWindowStart, nextWindowEnd);
  }, [caseId, runId]);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void load();
  }

  function clearWindowFilter() {
    setWindowStart("");
    setWindowEnd("");
    void load(keyword, service, "", "");
  }

  async function copyEvidenceRef(value: string) {
    try {
      await navigator.clipboard?.writeText(value);
    } catch {
      // Clipboard access can be unavailable in some browser contexts.
    }
  }

  const serviceOptions = useMemo(() => {
    const values = new Set<string>();
    if (service) {
      values.add(service);
    }
    for (const facet of data?.facets.service || []) {
      values.add(facet.value);
    }
    return Array.from(values).sort();
  }, [data, service]);

  return (
    <Shell caseId={caseId} runId={runId}>
      <form className="toolbar" onSubmit={submit}>
        <h1>Tabular Logs</h1>
        <label className="inline-field">
          Keyword
          <input
            placeholder="Search redacted logs"
            value={keyword}
            onChange={(event) => setKeyword(event.target.value)}
          />
        </label>
        <label className="inline-field">
          Service
          <select value={service} onChange={(event) => setService(event.target.value)}>
            <option value="">Any</option>
            {serviceOptions.map((value) => (
              <option key={value} value={value}>{value}</option>
            ))}
          </select>
        </label>
        <button className="button secondary" disabled={loading} type="submit">Apply</button>
      </form>

      {error && <div className="alert error">{error}</div>}
      {(windowStart || windowEnd) && (
        <div className="filter-summary" data-testid="logs-window-filter">
          <span>
            Window filter: {windowStart ? formatDateTime(windowStart) : "start"} to{" "}
            {windowEnd ? formatDateTime(windowEnd) : "end"}
          </span>
          <button className="button secondary" onClick={clearWindowFilter} type="button">
            Clear window
          </button>
        </div>
      )}
      <section className="panel">
        {loading && <div className="empty">Loading logs</div>}
        {!loading && data && data.items.length === 0 && <div className="empty">No logs found</div>}
        {!loading && data && data.items.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Level</th>
                  <th>Service</th>
                  <th>Evidence</th>
                  <th>Message</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((item) => (
                  <tr key={item.log_id}>
                    <td>{formatDateTime(item.timestamp)}</td>
                    <td>{valueLabel(item.level)}</td>
                    <td>{valueLabel(item.service)}</td>
                    <td>
                      <code>{item.file_path}:{item.line_number}</code>
                      <br />
                      <button
                        className="button ghost"
                        type="button"
                        onClick={() => void copyEvidenceRef(`${item.file_path}:${item.line_number}`)}
                      >
                        Copy ref
                      </button>
                    </td>
                    <td>
                      {item.message}
                      <br />
                      <span className={`pill ${signalClass(item.golden_signal)}`}>{item.golden_signal}</span>
                      <span className="muted"> {item.fault_categories.join(", ")}</span>
                    </td>
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
