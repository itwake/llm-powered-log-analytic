import { ApiError } from "@/lib/api";

export function formatDateTime(value: string | null | undefined): string {
  if (!value) {
    return "n/a";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

export function formatShortTime(value: string | null | undefined): string {
  if (!value) {
    return "n/a";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat(undefined, {
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

/** Clock time with seconds in UTC, matching the timestamps inside log lines. */
export function formatUtcClockTime(value: string | null | undefined): string {
  if (!value) {
    return "n/a";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
    timeZone: "UTC",
  }).format(date);
}

/**
 * Full log timestamp in UTC with milliseconds, the precision and zone of the log files
 * themselves; columns that use it say "UTC" in their header.
 */
export function formatLogTimestamp(value: string | null | undefined): string {
  if (!value) {
    return "n/a";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toISOString().replace("T", " ").replace("Z", "");
}

export function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "n/a";
  }
  return `${(value * 100).toFixed(1)}%`;
}

type ErrorRewrite = [RegExp, string | ((match: RegExpMatchArray) => string)];

/** API `detail` strings are written for logs; these are the same facts written for people. */
const ERROR_REWRITES: ErrorRewrite[] = [
  [/^not authenticated$/i, "Your session has expired. Sign in again."],
  [/^case not found$/i, "This case was not found in your account."],
  [/^analysis run not found$/i, "This analysis run was not found in your account."],
  [/^analysis result is not ready$/i, "This run has not finished yet. Reports open once it completes."],
  [/^analysis failed before producing a result$/i, "This run failed before producing a result."],
  [/^analysis was cancelled$/i, "This run was cancelled before producing a result."],
  [/^analysis completed without a readable result$/i, "This run completed, but its result could not be read."],
  [/^upload exceeds the configured (.+) limit$/i, (match) => `The file exceeds the upload limit of ${match[1]}.`],
  [/^upload (?:size|content) does not match/i, "The uploaded file did not match what was announced. Try the upload again."],
  [/^AI provider not found$/i, "This AI provider no longer exists."],
  [/^upload failed$/i, "The upload failed. Check the connection and try again."],
  [/^upload aborted$/i, "The upload was interrupted."],
  [/^Request failed with HTTP (\d+)$/i, (match) => `The server answered with HTTP ${match[1]}.`],
];

export function apiErrorMessage(error: unknown): string {
  const raw = (error instanceof ApiError || error instanceof Error) ? error.message.trim() : "";
  if (!raw) {
    return "The request failed. Try again.";
  }
  for (const [pattern, rewrite] of ERROR_REWRITES) {
    const match = raw.match(pattern);
    if (match) {
      return typeof rewrite === "string" ? rewrite : rewrite(match);
    }
  }
  return `${raw.charAt(0).toUpperCase()}${raw.slice(1)}`;
}

export function valueLabel(value: string | null | undefined): string {
  return value && value.trim() ? value : "n/a";
}
