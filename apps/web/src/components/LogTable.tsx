"use client";

import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useEffect, useMemo, useState } from "react";
import { SignalBadge } from "@/components/SignalBadge";
import { Button, EmptyState } from "@/components/ui";
import type { LogItem } from "@/lib/api";
import { formatDateTime } from "@/lib/format";

interface LogTableProps {
  emptyTitle?: string;
  items: LogItem[];
}

type FilterKey = "time" | "service" | "signal" | "source";

type Filters = Record<FilterKey, string>;

const EMPTY_FILTERS: Filters = {
  time: "",
  service: "",
  signal: "",
  source: "",
};

function uniqueSorted(values: string[]): string[] {
  return Array.from(new Set(values)).sort((left, right) => left.localeCompare(right));
}

function timeValue(item: LogItem): string {
  return formatDateTime(item.timestamp);
}

function serviceValue(item: LogItem): string {
  return item.service || "unknown";
}

function signalValue(item: LogItem): string {
  return item.golden_signal || "unknown";
}

function sourceValue(item: LogItem): string {
  return `${item.file_path}:${item.line_number}`;
}

function hasActiveFilters(filters: Filters): boolean {
  return Object.values(filters).some(Boolean);
}

interface HeaderFilterProps {
  label: string;
  onChange: (value: string) => void;
  options: string[];
  value: string;
}

function HeaderFilter({ label, onChange, options, value }: HeaderFilterProps) {
  return (
    <Stack spacing={0.75} sx={{ minWidth: 140 }}>
      <Typography component="span" sx={{ fontWeight: 800 }} variant="caption">
        {label}
      </Typography>
      <TextField
        select
        aria-label={`Filter ${label}`}
        size="small"
        value={value}
        onChange={(event) => onChange(event.target.value)}
      >
        <MenuItem value="">All</MenuItem>
        {options.map((option) => (
          <MenuItem key={option} value={option}>
            {option}
          </MenuItem>
        ))}
      </TextField>
    </Stack>
  );
}


export function LogTable({ emptyTitle = "No matching logs", items }: LogTableProps) {
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS);

  useEffect(() => {
    setFilters(EMPTY_FILTERS);
  }, [items]);

  const options = useMemo(() => ({
    service: uniqueSorted(items.map(serviceValue)),
    signal: uniqueSorted(items.map(signalValue)),
    source: uniqueSorted(items.map(sourceValue)),
    time: uniqueSorted(items.map(timeValue)),
  }), [items]);

  const filteredItems = useMemo(() => items.filter((item) => (
    (!filters.time || timeValue(item) === filters.time)
    && (!filters.service || serviceValue(item) === filters.service)
    && (!filters.signal || signalValue(item) === filters.signal)
    && (!filters.source || sourceValue(item) === filters.source)
  )), [filters, items]);

  const updateFilter = (key: FilterKey, value: string) => {
    setFilters((current) => ({ ...current, [key]: value }));
  };

  if (items.length === 0) {
    return <EmptyState title={emptyTitle} />;
  }

  return (
    <Stack spacing={1.5}>
      {hasActiveFilters(filters) && (
        <Stack
          direction={{ xs: "column", sm: "row" }}
          spacing={1}
          sx={{ alignItems: "flex-start" }}
        >
          <Typography color="text.secondary" variant="body2">
            Showing {filteredItems.length} of {items.length} loaded logs.
          </Typography>
          <Button
            size="sm"
            variant="secondary"
            onClick={() => setFilters(EMPTY_FILTERS)}
          >
            Clear filters
          </Button>
        </Stack>
      )}
      <TableContainer>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>
                <HeaderFilter
                  label="Time"
                  options={options.time}
                  value={filters.time}
                  onChange={(value) => updateFilter("time", value)}
                />
              </TableCell>
              <TableCell>
                <HeaderFilter
                  label="Service"
                  options={options.service}
                  value={filters.service}
                  onChange={(value) => updateFilter("service", value)}
                />
              </TableCell>
              <TableCell>
                <HeaderFilter
                  label="Signal"
                  options={options.signal}
                  value={filters.signal}
                  onChange={(value) => updateFilter("signal", value)}
                />
              </TableCell>
              <TableCell>Message</TableCell>
              <TableCell>
                <HeaderFilter
                  label="Source"
                  options={options.source}
                  value={filters.source}
                  onChange={(value) => updateFilter("source", value)}
                />
              </TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {filteredItems.map((item) => (
              <TableRow hover key={item.log_id}>
                <TableCell sx={{ whiteSpace: "nowrap" }}>{timeValue(item)}</TableCell>
                <TableCell>{serviceValue(item)}</TableCell>
                <TableCell><SignalBadge signal={signalValue(item)} /></TableCell>
                <TableCell sx={{ maxWidth: 640, overflowWrap: "anywhere" }}>
                  {item.message}
                </TableCell>
                <TableCell sx={{ whiteSpace: "nowrap" }}>{sourceValue(item)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>
      {filteredItems.length === 0 && <EmptyState title="No logs match the selected filters" />}
    </Stack>
  );
}

