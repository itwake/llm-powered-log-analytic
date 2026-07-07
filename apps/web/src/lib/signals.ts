/**
 * One semantic color per golden signal, shared by every view (summary badges,
 * temporal chart, tabular logs, causal graph) so the same signal always looks
 * the same everywhere. Red is reserved for errors.
 */
export const SIGNAL_COLORS: Record<string, string> = {
  error: "#dc2626",
  availability: "#7c3aed",
  saturation: "#ea580c",
  latency: "#0891b2",
  traffic: "#2563eb",
  information: "#10b981",
  unknown: "#6b7280",
};

export const SIGNAL_ORDER = [
  "error",
  "availability",
  "saturation",
  "latency",
  "traffic",
  "information",
  "unknown",
];

export function signalColor(signal: string | null | undefined): string {
  return SIGNAL_COLORS[(signal || "").toLowerCase()] || SIGNAL_COLORS.unknown;
}

const LEVEL_COLORS: Record<string, string> = {
  error: "#dc2626",
  fatal: "#b91c1c",
  warn: "#d97706",
  warning: "#d97706",
  info: "#6b7280",
  debug: "#9ca3af",
  trace: "#9ca3af",
};

export function levelColor(level: string | null | undefined): string | null {
  return LEVEL_COLORS[(level || "").toLowerCase()] || null;
}

/**
 * Turn a raw template text into a human-friendly label: drop `<*>`
 * placeholders and collapse whitespace so graph nodes and lists read as a
 * message shape instead of parser output.
 */
export function cleanTemplateLabel(text: string | null | undefined, maxLength = 64): string {
  const cleaned = (text || "")
    .replaceAll("<*>", " ")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/^[.…\s]+/, "");
  if (!cleaned) {
    return "template";
  }
  return cleaned.length > maxLength ? `${cleaned.slice(0, maxLength - 3)}...` : cleaned;
}

/** Strip a leading ISO timestamp from a raw log message for display. */
export function stripLeadingTimestamp(message: string | null | undefined): string {
  return (message || "").replace(
    /^\s*\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?\s*/i,
    "",
  );
}
