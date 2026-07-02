"use client";

import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import FormControl from "@mui/material/FormControl";
import InputLabel from "@mui/material/InputLabel";
import MenuItem from "@mui/material/MenuItem";
import Select from "@mui/material/Select";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";
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
import Link from "@/components/Link";
import { reportsApi, TemporalResponse, TemporalSeries } from "@/lib/api";
import { apiErrorMessage, formatShortTime } from "@/lib/format";
import { Button, Card, EmptyState } from "@/components/ui";

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
  const { caseId, runId } = useParams<{ caseId: string; runId: string }>();
  const theme = useTheme();
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

  const chartPalette = useMemo(
    () => [
      theme.palette.primary.main,
      theme.palette.success.main,
      theme.palette.error.main,
      theme.palette.warning.main,
      theme.palette.info.main,
      theme.palette.secondary.main,
    ],
    [theme],
  );

  const chartOption = useMemo<EChartsCoreOption>(() => ({
    color: chartPalette,
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
  }), [chartPalette, data, windows]);

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

    const onChartClick = (params: { dataIndex?: number }) => {
      if (typeof params.dataIndex !== "number") {
        return;
      }
      const windowStart = windows[params.dataIndex];
      if (windowStart) {
        selectWindow(windowStart);
      }
    };

    const onCanvasClick = (event: { offsetX: number; offsetY: number; target?: unknown }) => {
      if (event.target) {
        return;
      }
      const point: [number, number] = [event.offsetX, event.offsetY];
      if (!instance.containPixel({ gridIndex: 0 }, point)) {
        return;
      }
      const converted = instance.convertFromPixel({ gridIndex: 0 }, point);
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

  const selectedLogsHref = selectedWindow
    ? `/cases/${caseId}/runs/${runId}/logs?${new URLSearchParams({
        window_start: selectedWindow.start,
        window_end: selectedWindow.end,
      }).toString()}`
    : `/cases/${caseId}/runs/${runId}/logs`;

  return (
    <Stack spacing={2.5}>
      <Stack
        component="form"
        direction={{ xs: "column", lg: "row" }}
        spacing={2}
        sx={{ alignItems: { xs: "flex-start", lg: "center" }, justifyContent: "space-between" }}
        onSubmit={submit}
      >
        <Typography component="h1" sx={{ fontWeight: 850 }} variant="h4">
          Temporal View
        </Typography>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} sx={{ width: { xs: "100%", lg: "auto" } }}>
          <FormControl sx={{ minWidth: 160 }}>
            <InputLabel id="temporal-window-label">Window</InputLabel>
            <Select
              label="Window"
              labelId="temporal-window-label"
              value={String(windowSizeSeconds)}
              onChange={(event) => setWindowSizeSeconds(Number(event.target.value))}
            >
              <MenuItem value="60">1 minute</MenuItem>
              <MenuItem value="300">5 minutes</MenuItem>
              <MenuItem value="900">15 minutes</MenuItem>
            </Select>
          </FormControl>
          <FormControl sx={{ minWidth: 190 }}>
            <InputLabel id="temporal-group-label">Group</InputLabel>
            <Select
              label="Group"
              labelId="temporal-group-label"
              value={groupBy}
              onChange={(event) => setGroupBy(event.target.value)}
            >
              <MenuItem value="golden_signal">Golden signal</MenuItem>
              <MenuItem value="service">Service</MenuItem>
              <MenuItem value="fault_category">Fault category</MenuItem>
              <MenuItem value="template">Template</MenuItem>
            </Select>
          </FormControl>
          <Button disabled={loading} type="submit" variant="secondary">
            Apply
          </Button>
        </Stack>
      </Stack>

      {error && <Alert severity="error">{error}</Alert>}
      <Card>
        {loading && <EmptyState title="Loading temporal data" />}
        {!loading && data && data.series.length === 0 && <EmptyState title="No temporal data" />}
        {!loading && data && data.series.length > 0 && (
          <Stack spacing={2}>
            <Box
              aria-label="Temporal stacked bar chart"
              className="temporal-chart"
              data-testid="temporal-echarts"
              ref={chartElement}
            />
            <Stack
              data-testid="temporal-selection-summary"
              direction={{ xs: "column", sm: "row" }}
              spacing={1.5}
              sx={{ alignItems: { xs: "flex-start", sm: "center" }, border: 1, borderColor: "divider", borderRadius: 2, justifyContent: "space-between", p: 2 }}
            >
              {selectedWindow ? (
                <>
                  <Box>
                    <Typography component="h2" sx={{ fontWeight: 800 }} variant="h6">
                      Selected Window
                    </Typography>
                    <Typography>
                      <strong>{formatShortTime(selectedWindow.start)}</strong>
                      {" to "}
                      <strong>{formatShortTime(selectedWindow.end)}</strong>
                      {" | "}
                      {selectedWindow.total} logs
                    </Typography>
                  </Box>
                  <Button component={Link} href={selectedLogsHref} variant="secondary">
                    Open in Tabular Logs
                  </Button>
                </>
              ) : (
                <Box>
                  <Typography component="h2" sx={{ fontWeight: 800 }} variant="h6">
                    Selected Window
                  </Typography>
                  <Typography color="text.secondary">Select a bar to inspect that time window.</Typography>
                </Box>
              )}
            </Stack>
          </Stack>
        )}
      </Card>
    </Stack>
  );
}
