"use client";

import Box from "@mui/material/Box";
import Tooltip from "@mui/material/Tooltip";
import type { SxProps, Theme } from "@mui/material/styles";
import { useMemo } from "react";
import {
  hasTemplatePlaceholder,
  segmentsToText,
  templateView,
  type TemplateSegment,
} from "@/lib/templates";

interface TemplateTextProps {
  /** Template text as returned by the API, with `<*>` marking the values that vary. */
  template: string | null | undefined;
  /** One log line the template covers; its values fill the slots and restore the casing. */
  sample?: string | null;
  /** Show a structured line's msg="..." value first and the remaining fields muted below it. */
  headline?: boolean;
  /** Keep to one line with an ellipsis and offer the full text in a tooltip. */
  truncate?: boolean;
  /** Show the sample itself when it does not match the template, instead of the template shape. */
  preferSample?: boolean;
  /** Monospace rendering; pass false inside text that already sets a font. */
  mono?: boolean;
  sx?: SxProps<Theme>;
}

const VALUE_SX = {
  bgcolor: "rgba(91,92,246,0.12)",
  borderRadius: "4px",
  color: "primary.dark",
  px: 0.4,
} as const;

const SLOT_SX = {
  bgcolor: "rgba(100,116,139,0.1)",
  border: "1px dashed rgba(100,116,139,0.55)",
  borderRadius: "4px",
  color: "text.secondary",
  px: 0.5,
} as const;

const CODE_SX = {
  bgcolor: "rgba(91,92,246,0.11)",
  border: "1px solid rgba(91,92,246,0.12)",
  borderRadius: "6px",
  color: "primary.dark",
  fontFamily: "var(--font-mono), Consolas, Monaco, monospace",
  fontSize: "0.92em",
  px: 0.55,
  py: 0.15,
} as const;

/**
 * Plain text that quotes templates in backticks, as the structured summary's claims and next
 * actions do. Each quoted span becomes a code chip and its `<*>` slots become placeholders.
 */
export function TextWithTemplates({ text }: { text: string | null | undefined }) {
  const parts = useMemo(() => (text ?? "").split("`"), [text]);
  return (
    <>
      {parts.map((part, index) =>
        index % 2 === 1 ? (
          <Box component="code" key={`${index}:${part}`} sx={CODE_SX}>
            {hasTemplatePlaceholder(part) ? <TemplateText mono={false} template={part} /> : part}
          </Box>
        ) : (
          <span key={`${index}:${part}`}>{part}</span>
        ),
      )}
    </>
  );
}

function Segments({ segments }: { segments: TemplateSegment[] }) {
  return (
    <>
      {segments.map((segment, index) => {
        const key = `${index}:${segment.text}`;
        if (!segment.variable) {
          return <span key={key}>{segment.text}</span>;
        }
        return (
          <Box
            component="mark"
            key={key}
            sx={segment.text ? VALUE_SX : SLOT_SX}
            title={
              segment.text
                ? "This value varies between the lines of the template"
                : "A value that varies between the lines of the template"
            }
          >
            {segment.text || "…"}
          </Box>
        );
      })}
    </>
  );
}

/**
 * A log template rendered as one real line with the variable values highlighted, so `<*>` never
 * reaches the screen. Without a matching sample the template shape is shown with a placeholder
 * per slot.
 */
export function TemplateText({
  headline = false,
  mono = true,
  preferSample = false,
  sample,
  sx,
  template,
  truncate = false,
}: TemplateTextProps) {
  const view = useMemo(() => templateView(template, sample), [sample, template]);
  const fullText = useMemo(() => segmentsToText(view.segments), [view]);
  const showSample = preferSample && !view.filled && Boolean(sample);
  const splitHeadline = !showSample && headline && view.headline !== null;
  const primary: TemplateSegment[] = showSample
    ? [{ text: sample ?? "", variable: false }]
    : splitHeadline
      ? view.headline ?? []
      : view.segments;
  const secondary = splitHeadline && !truncate ? view.rest : [];
  const sxArray = Array.isArray(sx) ? sx : sx ? [sx] : [];

  if (primary.length === 0 && secondary.length === 0) {
    return null;
  }

  const content = (
    <Box
      component="span"
      sx={[
        {
          display: truncate ? "block" : "inline",
          fontFamily: mono ? "var(--font-mono), Consolas, Monaco, monospace" : "inherit",
          fontSize: mono ? "0.92em" : "inherit",
          lineHeight: 1.6,
          overflowWrap: "anywhere",
          ...(truncate ? { overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } : {}),
        },
        ...sxArray,
      ]}
    >
      {splitHeadline ? (
        <>
          <Box component="span" sx={{ display: truncate ? "inline" : "block", fontWeight: 700 }}>
            <Segments segments={primary} />
          </Box>
          {secondary.length > 0 && (
            <Box component="span" sx={{ color: "text.secondary", display: "block", fontSize: "0.86em", mt: 0.25 }}>
              <Segments segments={secondary} />
            </Box>
          )}
        </>
      ) : (
        <Segments segments={primary} />
      )}
    </Box>
  );

  if (!truncate) {
    return content;
  }
  return (
    <Tooltip enterDelay={400} title={showSample ? sample ?? "" : fullText}>
      {content}
    </Tooltip>
  );
}
