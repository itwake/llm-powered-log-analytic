"use client";

import { useParams } from "next/navigation";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { reportsApi, TemporalResponse, TemporalSeries } from "@/lib/api";
import { apiErrorMessage, formatShortTime } from "@/lib/format";
import { Shell } from "@/components/Shell";

const palette = ["#2d5f87", "#2f6f62", "#a6423c", "#8b6728", "#654f9f", "#4d7770"];

function countFor(series: TemporalSeries, windowStart: string): number {
  return series.points.find((point) => point.window_start === windowStart)?.count || 0;
}

export default function TemporalPage() {
  const {caseId, runId} = useParams<{caseId: string; runId: string}>();
  const [data, setData] = useState<TemporalResponse | null>(null);
  const [groupBy, setGroupBy] = useState("golden_signal");
  const [windowSizeSeconds, setWindowSizeSeconds] = useState(60);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function load(nextGroupBy = groupBy, nextWindowSize = windowSizeSeconds) {
    setLoading(true);
    setError(null);
    try {
      const response = await reportsApi.temporal(caseId, runId, {
        group_by: nextGroupBy,
        window_size_seconds: nextWindowSize,
      });
      setData(response);
    } catch (caught) {
      setError(apiErrorMessage(caught));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load("golden_signal", 60);
  }, [caseId, runId]);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void load();
  }

  const windows = useMemo(() => {
    const values = new Set<string>();
    for (const series of data?.series || []) {
      for (const point of series.points) {
        values.add(point.window_start);
      }
    }
    return Array.from(values).sort();
  }, [data]);

  const totals = useMemo(() => {
    const map = new Map<string, number>();
    for (const windowStart of windows) {
      map.set(
        windowStart,
        (data?.series || []).reduce((total, series) => total + countFor(series, windowStart), 0),
      );
    }
    return map;
  }, [data, windows]);

  const maxTotal = Math.max(1, ...Array.from(totals.values()));

  return (
    <Shell caseId={caseId} runId={runId}>
      <form className="toolbar" onSubmit={submit}>
        <h1>Temporal View</h1>
        <label className="inline-field">
          Window
          <select
            value={windowSizeSeconds}
            onChange={(event) => setWindowSizeSeconds(Number(event.target.value))}
          >
            <option value={60}>1 minute</option>
            <option value={300}>5 minutes</option>
            <option value={900}>15 minutes</option>
          </select>
        </label>
        <label className="inline-field">
          Group
          <select value={groupBy} onChange={(event) => setGroupBy(event.target.value)}>
            <option value="golden_signal">Golden signal</option>
            <option value="service">Service</option>
            <option value="fault_category">Fault category</option>
            <option value="template">Template</option>
          </select>
        </label>
        <button className="button secondary" disabled={loading} type="submit">Apply</button>
      </form>

      {error && <div className="alert error">{error}</div>}
      <section className="panel chart-area">
        {loading && <div className="empty">Loading temporal data</div>}
        {!loading && data && data.series.length === 0 && <div className="empty">No temporal data</div>}
        {!loading && data && data.series.length > 0 && (
          <>
            <div className="legend">
              {data.series.map((series, index) => (
                <span className="legend-item" key={series.name}>
                  <span
                    className="legend-swatch"
                    style={{background: palette[index % palette.length]}}
                  />
                  {series.name}
                </span>
              ))}
            </div>
            {windows.map((windowStart) => {
              const total = totals.get(windowStart) || 0;
              return (
                <div className="stacked-row" key={windowStart}>
                  <div className="stacked-row-header">
                    <strong>{formatShortTime(windowStart)}</strong>
                    <span className="muted">{total} logs</span>
                  </div>
                  <div className="stacked-track" aria-label={`${formatShortTime(windowStart)} ${total} logs`}>
                    <div
                      className="stacked-fill"
                      style={{width: `${Math.max(2, (total / maxTotal) * 100)}%`}}
                    >
                      {data.series.map((series, index) => {
                        const count = countFor(series, windowStart);
                        if (!count || total === 0) {
                          return null;
                        }
                        return (
                          <span
                            aria-label={`${series.name}: ${count}`}
                            className="stack-segment"
                            key={series.name}
                            style={{
                              background: palette[index % palette.length],
                              width: `${(count / total) * 100}%`,
                            }}
                            title={`${series.name}: ${count}`}
                          />
                        );
                      })}
                    </div>
                  </div>
                </div>
              );
            })}
          </>
        )}
      </section>
    </Shell>
  );
}
