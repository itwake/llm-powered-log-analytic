"use client";

import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";
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
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { LogTable } from "@/components/LogTable";
import { Button, Card, EmptyState } from "@/components/ui";
import { reportsApi } from "@/lib/api";
import type { LogsResponse, TemporalResponse, TemporalSeries } from "@/lib/api";
import { apiErrorMessage, formatDateTime, formatShortTime } from "@/lib/format";
import { SIGNAL_COLORS } from "@/lib/signals";

echarts.use([
  BarChart,
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  TooltipComponent,
  CanvasRenderer,
]);

type TemporalGroup = "golden_signal" | "service" | "fault_category" | "template";

function countFor(series: TemporalSeries, windowStart: string): number {
  return series.points.find((point) => point.window_start === windowStart)?.count ?? 0;
}

function windowEnd(windowStart: string, windowSizeSeconds: number): string {
  const start = new Date(windowStart);
  if (Number.isNaN(start.getTime())) {
    return windowStart;
  }
  return new Date(start.getTime() + windowSizeSeconds * 1000).toISOString();
}

export default function TemporalPage() {
  const { caseId, runId } = useParams<{ caseId: string; runId: string }>();
  const theme = useTheme();
  const chartElement = useRef<HTMLDivElement | null>(null);
  const chart = useRef<EChartsType | null>(null);
  const [groupBy, setGroupBy] = useState<TemporalGroup>("golden_signal");
  const [data, setData] = useState<TemporalResponse | null>(null);
  const [selectedWindow, setSelectedWindow] = useState<string | null>(null);
  const [windowLogs, setWindowLogs] = useState<LogsResponse | null>(null);
  const [windowLogsError, setWindowLogsError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setData(null);
    setSelectedWindow(null);
    setError(null);
    reportsApi.temporal(caseId, runId, { group_by: groupBy })
      .then((response) => {
        if (active) {
          setData(response);
        }
      })
      .catch((caught) => {
        if (active) {
          setError(apiErrorMessage(caught));
        }
      });
    return () => {
      active = false;
    };
  }, [caseId, runId, groupBy]);

  const windows = useMemo(() => {
    const values = new Set<string>();
    for (const series of data?.series ?? []) {
      for (const point of series.points) {
        values.add(point.window_start);
      }
    }
    return Array.from(values).sort();
  }, [data]);

  const selectedTotal = useMemo(() => {
    if (!selectedWindow) {
      return 0;
    }
    return (data?.series ?? []).reduce(
      (total, series) => total + countFor(series, selectedWindow),
      0,
    );
  }, [data, selectedWindow]);

  const selectedWindowEnd = useMemo(() => (
    selectedWindow ? windowEnd(selectedWindow, data?.window_size_seconds ?? 60) : null
  ), [data, selectedWindow]);

  useEffect(() => {
    if (!selectedWindow || !selectedWindowEnd) {
      setWindowLogs(null);
      setWindowLogsError(null);
      return;
    }

    let active = true;
    setWindowLogs(null);
    setWindowLogsError(null);
    reportsApi.logs(caseId, runId, {
      limit: 100,
      window_start: selectedWindow,
      window_end: selectedWindowEnd,
    })
      .then((response) => {
        if (active) {
          setWindowLogs(response);
        }
      })
      .catch((caught) => {
        if (active) {
          setWindowLogsError(apiErrorMessage(caught));
        }
      });

    return () => {
      active = false;
    };
  }, [caseId, runId, selectedWindow, selectedWindowEnd]);

  const chartOption = useMemo<EChartsCoreOption>(() => ({
    animationDuration: 350,
    color: [
      theme.palette.primary.main,
      theme.palette.info.main,
      theme.palette.success.main,
      theme.palette.warning.main,
      theme.palette.error.main,
      theme.palette.secondary.main,
    ],
    dataZoom: [
      {
        type: "inside",
        filterMode: "none",
        xAxisIndex: 0,
      },
      {
        type: "slider",
        bottom: 8,
        filterMode: "none",
        height: 24,
        xAxisIndex: 0,
      },
    ],
    grid: {
      bottom: 64,
      containLabel: true,
      left: 16,
      right: 16,
      top: 56,
    },
    legend: {
      top: 0,
      type: "scroll",
    },
    series: (data?.series ?? []).map((series) => ({
      name: series.name,
      type: "bar",
      stack: "logs",
      barMaxWidth: 46,
      data: windows.map((windowStart) => countFor(series, windowStart)),
      emphasis: {
        focus: "series",
      },
      ...(SIGNAL_COLORS[series.name]
        ? { itemStyle: { color: SIGNAL_COLORS[series.name] } }
        : {}),
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
  }), [data, theme, windows]);

  useEffect(() => {
    if (!data || data.series.length === 0 || !chartElement.current) {
      chart.current?.dispose();
      chart.current = null;
      return;
    }

    const instance = echarts.init(chartElement.current);
    chart.current = instance;
    instance.setOption(chartOption);

    const selectBar = (params: { dataIndex?: number }) => {
      if (typeof params.dataIndex !== "number") {
        return;
      }
      setSelectedWindow(windows[params.dataIndex] ?? null);
    };
    instance.on("click", selectBar);

    const resizeObserver = new ResizeObserver(() => instance.resize());
    resizeObserver.observe(chartElement.current);

    return () => {
      resizeObserver.disconnect();
      instance.off("click", selectBar);
      instance.dispose();
      if (chart.current === instance) {
        chart.current = null;
      }
    };
  }, [chartOption, data, windows]);

  const selectedLogsHref = selectedWindow
    ? `/cases/${caseId}/runs/${runId}/logs?${new URLSearchParams({
        window_start: selectedWindow,
        window_end: selectedWindowEnd
          ?? windowEnd(selectedWindow, data?.window_size_seconds ?? 60),
      }).toString()}`
    : `/cases/${caseId}/runs/${runId}/logs`;

  return (
    <Stack spacing={2.5}>
      <Stack
        direction={{ xs: "column", sm: "row" }}
        spacing={2}
        sx={{ justifyContent: "space-between" }}
      >
        <Box>
          <Typography component="h1" sx={{ fontWeight: 850 }} variant="h4">
            Temporal Activity
          </Typography>
          <Typography color="text.secondary">
            Compare log volume across aligned analysis windows.
          </Typography>
        </Box>
        <TextField
          select
          label="Group by"
          size="small"
          value={groupBy}
          onChange={(event) => setGroupBy(event.target.value as TemporalGroup)}
        >
          <MenuItem value="golden_signal">Signal</MenuItem>
          <MenuItem value="service">Service</MenuItem>
          <MenuItem value="fault_category">Fault category</MenuItem>
          <MenuItem value="template">Template</MenuItem>
        </TextField>
      </Stack>

      {error && <Alert severity="error">{error}</Alert>}
      {!data && !error && <Card><EmptyState title="Loading temporal activity" /></Card>}
      {data && data.series.length === 0 && (
        <Card><EmptyState title="No temporal activity" /></Card>
      )}
      {data && data.series.length > 0 && (
        <Card>
          <Stack spacing={2}>
            <Box
              aria-label="Stacked log activity over time"
              ref={chartElement}
              role="img"
              sx={{ height: { xs: 360, md: 460 }, width: "100%" }}
            />
            <Stack
              direction={{ xs: "column", sm: "row" }}
              spacing={1.5}
              sx={{
                alignItems: { xs: "flex-start", sm: "center" },
                bgcolor: "rgba(91,92,246,0.055)",
                borderRadius: 2,
                justifyContent: "space-between",
                p: 2,
              }}
            >
              {selectedWindow ? (
                <Box>
                  <Typography sx={{ fontWeight: 800 }}>Selected window</Typography>
                  <Typography color="text.secondary" variant="body2">
                    {formatDateTime(selectedWindow)} · {selectedTotal} logs
                  </Typography>
                </Box>
              ) : (
                <Typography color="text.secondary" variant="body2">
                  Select a bar to inspect its matching logs.
                </Typography>
              )}
              <Button
                component={Link}
                disabled={!selectedWindow}
                href={selectedLogsHref}
                variant="secondary"
              >
                Open logs
              </Button>
            </Stack>
          </Stack>
        </Card>
      )}
      {data && selectedWindow && (
        <Card>
          <Stack spacing={2}>
            <Stack
              direction={{ xs: "column", sm: "row" }}
              spacing={1.5}
              sx={{
                alignItems: { xs: "flex-start", sm: "center" },
                justifyContent: "space-between",
              }}
            >
              <Box>
                <Typography component="h2" sx={{ fontWeight: 850 }} variant="h6">
                  Logs for selected window
                </Typography>
                <Typography color="text.secondary" variant="body2">
                  {formatDateTime(selectedWindow)} to {formatDateTime(selectedWindowEnd)} ·{" "}
                  {selectedTotal} matching logs
                </Typography>
                {windowLogs && windowLogs.total > windowLogs.items.length && (
                  <Typography color="text.secondary" variant="caption">
                    Showing first {windowLogs.items.length} of {windowLogs.total} matching logs.
                  </Typography>
                )}
              </Box>
              <Button component={Link} href={selectedLogsHref} variant="secondary">
                Open full logs view
              </Button>
            </Stack>

            {windowLogsError && <Alert severity="error">{windowLogsError}</Alert>}
            {!windowLogs && !windowLogsError && <EmptyState title="Loading selected logs" />}
            {windowLogs && windowLogs.items.length === 0 && (
              <EmptyState title="No logs in this window" />
            )}
            {windowLogs && windowLogs.items.length > 0 && (
              <LogTable emptyTitle="No logs in this window" items={windowLogs.items} />
            )}
          </Stack>
        </Card>
      )}
    </Stack>
  );
}
