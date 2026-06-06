"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import {
  FormEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { BarChart } from "echarts/charts";
import {
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  TooltipComponent,
} from "echarts/components";
import * as echarts from "echarts/core";
import type { EChartsCoreOption, EChartsType } from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { reportsApi, TemporalResponse, TemporalSeries } from "@/lib/api";
import { apiErrorMessage, formatShortTime } from "@/lib/format";
import { Shell } from "@/components/Shell";

const palette = ["#2d5f87", "#2f6f62", "#a6423c", "#8b6728", "#654f9f", "#4d7770"];

echarts.use([
  BarChart,
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  TooltipComponent,
  CanvasRenderer,
]);

function countFor(series: TemporalSeries, windowStart: string): number {
  return series.points.find((point) => point.window_start === windowStart)?.count || 0;
}

function windowEnd(windowStart: string, windowSizeSeconds: number): string {
  const start = new Date(windowStart);
  if (Number.isNaN(start.getTime())) {
    return windowStart;
  }
  return new Date(start.getTime() + windowSizeSeconds * 1000).toISOString();
}

interface SelectedWindow {
  start: string;
  end: string;
  total: number;
}

export default function TemporalPage() {
  const {caseId, runId} = useParams<{caseId: string; runId: string}>();
  const chartElement = useRef<HTMLDivElement | null>(null);
  const chart = useRef<EChartsType | null>(null);
  const [data, setData] = useState<TemporalResponse | null>(null);
  const [groupBy, setGroupBy] = useState("golden_signal");
  const [windowSizeSeconds, setWindowSizeSeconds] = useState(60);
  const [selectedWindow, setSelectedWindow] = useState<SelectedWindow | null>(null);
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
      setSelectedWindow(null);
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

  const activeWindowSize = data?.window_size_seconds || windowSizeSeconds;

  const selectWindow = useCallback(
    (windowStart: string) => {
      setSelectedWindow({
        start: windowStart,
        end: windowEnd(windowStart, activeWindowSize),
        total: totals.get(windowStart) || 0,
      });
    },
    [activeWindowSize, totals],
  );

  const chartOption = useMemo<EChartsCoreOption>(() => ({
    color: palette,
    dataZoom: [
      {
        type: "inside",
        xAxisIndex: 0,
        filterMode: "none",
      },
      {
        type: "slider",
        xAxisIndex: 0,
        bottom: 16,
        height: 28,
        filterMode: "none",
      },
    ],
    grid: {
      bottom: 74,
      containLabel: true,
      left: 18,
      right: 18,
      top: 54,
    },
    legend: {
      top: 0,
      type: "scroll",
    },
    series: (data?.series || []).map((series) => ({
      name: series.name,
      type: "bar",
      stack: "logs",
      barMaxWidth: 48,
      emphasis: {
        focus: "series",
      },
      data: windows.map((windowStart) => countFor(series, windowStart)),
    })),
    tooltip: {
      axisPointer: {
        type: "shadow",
      },
      trigger: "axis",
    },
    xAxis: {
      axisLabel: {
        formatter: (value: string) => formatShortTime(value),
        hideOverlap: true,
      },
      data: windows,
      type: "category",
    },
    yAxis: {
      minInterval: 1,
      name: "Logs",
      type: "value",
    },
  }), [data, windows]);

  useEffect(() => {
    if (loading || !data || data.series.length === 0) {
      chart.current?.dispose();
      chart.current = null;
      return;
    }

    if (!chartElement.current) {
      return;
    }

    const instance = chart.current || echarts.init(chartElement.current);
    chart.current = instance;
    instance.setOption(chartOption, true);

    const onChartClick = (params: {dataIndex?: number}) => {
      if (typeof params.dataIndex !== "number") {
        return;
      }
      const windowStart = windows[params.dataIndex];
      if (windowStart) {
        selectWindow(windowStart);
      }
    };

    const onCanvasClick = (event: {offsetX: number; offsetY: number; target?: unknown}) => {
      if (event.target) {
        return;
      }
      const point: [number, number] = [event.offsetX, event.offsetY];
      if (!instance.containPixel({gridIndex: 0}, point)) {
        return;
      }
      const converted = instance.convertFromPixel({gridIndex: 0}, point);
      const xValue = Array.isArray(converted) ? converted[0] : converted;
      const index = typeof xValue === "string" ? windows.indexOf(xValue) : Math.round(Number(xValue));
      const windowStart = windows[index];
      if (windowStart) {
        selectWindow(windowStart);
      }
    };

    const resizeObserver = new ResizeObserver(() => instance.resize());
    resizeObserver.observe(chartElement.current);
    instance.on("click", onChartClick);
    instance.getZr().on("click", onCanvasClick);

    return () => {
      resizeObserver.disconnect();
      instance.off("click", onChartClick);
      instance.getZr().off("click", onCanvasClick);
    };
  }, [chartOption, data, loading, selectWindow, windows]);

  useEffect(() => () => {
    chart.current?.dispose();
    chart.current = null;
  }, []);

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
        {loading && <div className="empty chart-state">Loading temporal data</div>}
        {!loading && data && data.series.length === 0 && <div className="empty chart-state">No temporal data</div>}
        {!loading && data && data.series.length > 0 && (
          <>
            <div
              aria-label="Temporal stacked bar chart"
              className="temporal-chart"
              data-testid="temporal-echarts"
              ref={chartElement}
            />
            <div className="selection-summary" data-testid="temporal-selection-summary">
              {selectedWindow ? (
                <>
                  <div>
                    <h2>Selected Window</h2>
                    <p>
                      <strong>{formatShortTime(selectedWindow.start)}</strong>
                      {" to "}
                      <strong>{formatShortTime(selectedWindow.end)}</strong>
                      {" | "}
                      {selectedWindow.total} logs
                    </p>
                  </div>
                  <Link
                    className="button secondary"
                    href={{
                      pathname: `/cases/${caseId}/runs/${runId}/logs`,
                      query: {
                        window_start: selectedWindow.start,
                        window_end: selectedWindow.end,
                      },
                    }}
                  >
                    Open in Tabular Logs
                  </Link>
                </>
              ) : (
                <div>
                  <h2>Selected Window</h2>
                  <p className="muted">Select a bar to inspect that time window.</p>
                </div>
              )}
            </div>
          </>
        )}
      </section>
    </Shell>
  );
}
