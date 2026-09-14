/**
 * Readable rendering of log templates.
 *
 * The pipeline groups log lines by a template in which every variable token (timestamp, id,
 * number, or the value of a key=value pair) is masked as `<*>`, and the text is lowercased
 * before grouping. That form is a grouping key rather than a label, so the UI recovers a
 * readable version by matching the template against one line it covers: literal text and
 * casing come from that sample line and each `<*>` slot is filled with the value found there.
 * When no sample line matches, the template shape is kept and the slots stay empty so the
 * caller can draw a placeholder instead of the raw marker.
 *
 * This module has no dependencies so it can also be exercised outside the browser.
 */

export const TEMPLATE_PLACEHOLDER = "<*>";

export interface TemplateSegment {
  text: string;
  /** True for the value of a `<*>` slot. Empty text means the value could not be recovered. */
  variable: boolean;
}

export interface TemplateView {
  /** The `msg="..."` payload of a structured line, or null when the template has none. */
  headline: TemplateSegment[] | null;
  /** The segments outside the headline, in order; equals `segments` when there is no headline. */
  rest: TemplateSegment[];
  /** Every segment of the filled template in order. */
  segments: TemplateSegment[];
  /** True when the sample matched the template and slot values were recovered from it. */
  filled: boolean;
}

/** Only the head of a sample is matched; longer text (stack traces) is appended unchanged. */
const MAX_MATCH_CHARS = 2000;
const MAX_CACHED_PATTERNS = 2000;
const ELLIPSIS = "…";
const WHITESPACE = /\s+/g;
const HEADLINE = /(?:^|\s)(?:msg|message)=(?:"([^"]*)"|'([^']*)'|([^\s"']+))/i;
/** The timestamp shape the extractor masks as one token at the head of a line. */
const LEADING_TIMESTAMP = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?$/i;

const patternCache = new Map<string, RegExp>();

function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * The template as an anchored, case-insensitive pattern: literal text between slots is matched
 * exactly and each slot captures the shortest text that lets the next literal match. A slot that
 * ends the template captures the rest of the matched head.
 */
function templatePattern(template: string): RegExp {
  const cached = patternCache.get(template);
  if (cached) {
    return cached;
  }
  const parts = template.split(TEMPLATE_PLACEHOLDER);
  const source = parts
    .map((part, index) => {
      const literal = escapeRegExp(part);
      if (index === parts.length - 1) {
        return literal;
      }
      const closesTemplate = index === parts.length - 2 && parts[index + 1] === "";
      return `${literal}(${closesTemplate ? "[\\s\\S]+" : "[\\s\\S]+?"})`;
    })
    .join("");
  const pattern = new RegExp(`^${source}`, "i");
  if (patternCache.size >= MAX_CACHED_PATTERNS) {
    patternCache.clear();
  }
  patternCache.set(template, pattern);
  return pattern;
}

function shapeSegments(parts: string[]): TemplateSegment[] {
  const segments: TemplateSegment[] = [];
  parts.forEach((part, index) => {
    if (part) {
      segments.push({ text: part, variable: false });
    }
    if (index < parts.length - 1) {
      segments.push({ text: "", variable: true });
    }
  });
  return segments;
}

/** Fill the template's slots from one line it covers; keep the shape when the line does not match. */
export function fillTemplate(
  template: string,
  sample?: string | null,
): { segments: TemplateSegment[]; filled: boolean } {
  const parts = template.split(TEMPLATE_PLACEHOLDER);
  const text = (sample ?? "").replace(WHITESPACE, " ").trim();
  // A sample that is itself a template (the API falls back to the template text when a run has
  // no sample line) would fill every slot with the marker, so it counts as no sample.
  if (!text || text.includes(TEMPLATE_PLACEHOLDER)) {
    return { segments: shapeSegments(parts), filled: false };
  }
  const head = text.slice(0, MAX_MATCH_CHARS);
  const match = templatePattern(template).exec(head);
  if (!match) {
    return { segments: shapeSegments(parts), filled: false };
  }
  const segments: TemplateSegment[] = [];
  let cursor = 0;
  parts.forEach((part, index) => {
    if (part) {
      // Case-insensitive matching keeps lengths equal, so the literal is read back from the
      // sample to restore its original casing.
      segments.push({ text: head.slice(cursor, cursor + part.length), variable: false });
      cursor += part.length;
    }
    if (index < parts.length - 1) {
      const value = match[index + 1] ?? "";
      segments.push({ text: value, variable: true });
      cursor += value.length;
    }
  });
  const tail = text.slice(cursor);
  if (tail) {
    segments.push({ text: tail, variable: false });
  }
  return { segments, filled: true };
}

/** Plain text of the segments; an unknown slot value renders as an ellipsis. */
export function segmentsToText(segments: TemplateSegment[]): string {
  return segments
    .map((segment) => (segment.variable && !segment.text ? ELLIPSIS : segment.text))
    .join("");
}

function segmentLength(segment: TemplateSegment): number {
  return segment.variable && !segment.text ? ELLIPSIS.length : segment.text.length;
}

/** The segments covering [start, end) of the text produced by `segmentsToText`. */
function sliceSegments(segments: TemplateSegment[], start: number, end: number): TemplateSegment[] {
  const sliced: TemplateSegment[] = [];
  let offset = 0;
  for (const segment of segments) {
    const length = segmentLength(segment);
    const from = Math.max(start, offset);
    const to = Math.min(end, offset + length);
    if (from < to) {
      sliced.push(
        segment.variable && !segment.text
          ? segment
          : { text: segment.text.slice(from - offset, to - offset), variable: segment.variable },
      );
    }
    offset += length;
  }
  return sliced;
}

/**
 * Drop a recovered timestamp at the head of the line: every view that shows a template also shows
 * the time in its own column or legend, so repeating it inside the text only costs space.
 */
function dropLeadingTimestamp(segments: TemplateSegment[]): TemplateSegment[] {
  const [first, second, ...others] = segments;
  if (!first || !first.variable || !LEADING_TIMESTAMP.test(first.text.trim())) {
    return segments;
  }
  if (second && !second.variable) {
    const text = second.text.replace(/^\s+/, "");
    return text ? [{ text, variable: false }, ...others] : others;
  }
  return second ? [second, ...others] : [];
}

function trimSegments(segments: TemplateSegment[]): TemplateSegment[] {
  const trimmed = segments.map((segment) => ({ ...segment }));
  while (trimmed.length > 0 && !trimmed[0].variable) {
    trimmed[0].text = trimmed[0].text.replace(/^\s+/, "");
    if (trimmed[0].text) {
      break;
    }
    trimmed.shift();
  }
  while (trimmed.length > 0 && !trimmed[trimmed.length - 1].variable) {
    const last = trimmed[trimmed.length - 1];
    last.text = last.text.replace(/\s+$/, "");
    if (last.text) {
      break;
    }
    trimmed.pop();
  }
  return trimmed;
}

/**
 * The filled template split into a headline and the remaining fields. Structured lines such as
 * `level=INFO service=auth msg="session token validated"` read best when the message payload
 * comes first and the metadata is shown as secondary text.
 */
export function templateView(template: string | null | undefined, sample?: string | null): TemplateView {
  const filledTemplate = fillTemplate(template ?? "", sample);
  const segments = dropLeadingTimestamp(filledTemplate.segments);
  const filled = filledTemplate.filled;
  const text = segmentsToText(segments);
  const match = HEADLINE.exec(text);
  const value = match ? (match[1] ?? match[2] ?? match[3] ?? "") : "";
  if (!match || !value.trim()) {
    return { headline: null, rest: segments, segments, filled };
  }
  const quoted = match[3] === undefined;
  const tokenEnd = match.index + match[0].length;
  const valueEnd = tokenEnd - (quoted ? 1 : 0);
  const valueStart = valueEnd - value.length;
  const tokenStart = match.index + (/^\s/.test(match[0]) ? 1 : 0);
  const before = sliceSegments(segments, 0, tokenStart);
  const after = sliceSegments(segments, tokenEnd, text.length);
  // Removing the msg token leaves the whitespace on both sides of it; keep one space.
  const left = before[before.length - 1];
  const right = after[0];
  if (left && right && !left.variable && !right.variable && /\s$/.test(left.text)) {
    after[0] = { text: right.text.replace(/^\s+/, ""), variable: false };
  }
  return {
    headline: sliceSegments(segments, valueStart, valueEnd),
    rest: trimSegments([...before, ...after]),
    segments,
    filled,
  };
}

/** One-line label for places that only take a string, such as chart legends and graph nodes. */
export function templateLabel(
  template: string | null | undefined,
  sample?: string | null,
  maxLength = 64,
): string {
  const view = templateView(template, sample);
  const text = segmentsToText(view.headline ?? view.segments).trim();
  if (text.length <= maxLength) {
    return text;
  }
  return `${text.slice(0, Math.max(1, maxLength - 1)).trimEnd()}${ELLIPSIS}`;
}

export function hasTemplatePlaceholder(text: string | null | undefined): boolean {
  return Boolean(text && text.includes(TEMPLATE_PLACEHOLDER));
}
