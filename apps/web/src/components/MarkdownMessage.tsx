"use client";

import ContentCopyIcon from "@mui/icons-material/ContentCopy";
import Box from "@mui/material/Box";
import Divider from "@mui/material/Divider";
import IconButton from "@mui/material/IconButton";
import Link from "@mui/material/Link";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import { isValidElement, type ReactNode, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import type { Components } from "react-markdown";
import rehypeSanitize from "rehype-sanitize";
import remarkGfm from "remark-gfm";

interface MarkdownMessageProps {
  content: string;
}

interface CodeBlockProps {
  children: ReactNode;
}

const disallowedElements = [
  "script",
  "style",
  "iframe",
  "object",
  "embed",
  "form",
  "input",
  "img",
  "video",
  "audio",
];

function textFromReactNode(node: ReactNode): string {
  if (node == null || typeof node === "boolean") {
    return "";
  }
  if (typeof node === "string" || typeof node === "number" || typeof node === "bigint") {
    return String(node);
  }
  if (Array.isArray(node)) {
    return node.map((child) => textFromReactNode(child)).join("");
  }
  if (isValidElement<{ children?: ReactNode }>(node)) {
    return textFromReactNode(node.props.children);
  }
  return "";
}

function safeHref(href: string | undefined): string | undefined {
  if (!href) {
    return undefined;
  }
  const trimmed = href.trim();
  const lower = trimmed.toLowerCase();
  if (
    lower.startsWith("http://") ||
    lower.startsWith("https://") ||
    lower.startsWith("mailto:") ||
    trimmed.startsWith("#") ||
    (trimmed.startsWith("/") && !trimmed.startsWith("//"))
  ) {
    return trimmed;
  }
  return undefined;
}

function CodeBlock({ children }: CodeBlockProps) {
  const [copied, setCopied] = useState(false);
  const code = useMemo(() => textFromReactNode(children).replace(/\n$/, ""), [children]);

  async function copyCode() {
    try {
      if (!navigator.clipboard?.writeText) {
        setCopied(false);
        return;
      }
      await navigator.clipboard.writeText(code);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1200);
    } catch {
      setCopied(false);
    }
  }

  return (
    <Box sx={{ my: 1.5, position: "relative" }}>
      <Tooltip title={copied ? "Copied" : "Copy code"}>
        <IconButton
          aria-label={copied ? "Copied code" : "Copy code"}
          size="small"
          sx={{
            bgcolor: "rgba(255,255,255,0.08)",
            color: "rgba(255,255,255,0.78)",
            position: "absolute",
            right: 8,
            top: 8,
            zIndex: 1,
            "&:hover": {
              bgcolor: "rgba(255,255,255,0.16)",
              color: "#ffffff",
            },
          }}
          onClick={copyCode}
        >
          <ContentCopyIcon fontSize="inherit" />
        </IconButton>
      </Tooltip>
      <Box
        component="pre"
        sx={{
          bgcolor: "#111827",
          border: "1px solid rgba(255,255,255,0.1)",
          borderRadius: "12px",
          color: "#e5e7eb",
          fontFamily: "var(--font-mono), Consolas, Monaco, monospace",
          fontSize: 13,
          lineHeight: 1.65,
          m: 0,
          maxWidth: "100%",
          overflowX: "auto",
          p: 2,
          pr: 6,
          whiteSpace: "pre",
          "& code": {
            bgcolor: "transparent",
            border: 0,
            borderRadius: 0,
            color: "inherit",
            fontFamily: "inherit",
            fontSize: "inherit",
            p: 0,
          },
        }}
      >
        {children}
      </Box>
    </Box>
  );
}

const markdownComponents: Components = {
  h1({ children }) {
    return (
      <Typography component="h3" sx={{ fontWeight: 850, mb: 1, mt: 1.5 }} variant="h6">
        {children}
      </Typography>
    );
  },
  h2({ children }) {
    return (
      <Typography component="h4" sx={{ fontWeight: 820, mb: 0.75, mt: 1.5 }} variant="subtitle1">
        {children}
      </Typography>
    );
  },
  h3({ children }) {
    return (
      <Typography component="h5" sx={{ fontWeight: 800, mb: 0.75, mt: 1.25 }} variant="subtitle2">
        {children}
      </Typography>
    );
  },
  h4({ children }) {
    return (
      <Typography component="h6" sx={{ fontWeight: 780, mb: 0.5, mt: 1 }} variant="body2">
        {children}
      </Typography>
    );
  },
  p({ children }) {
    return (
      <Typography component="p" sx={{ lineHeight: 1.7, mb: 1 }} variant="body2">
        {children}
      </Typography>
    );
  },
  strong({ children }) {
    return (
      <Box component="strong" sx={{ fontWeight: 850 }}>
        {children}
      </Box>
    );
  },
  em({ children }) {
    return <Box component="em">{children}</Box>;
  },
  ul({ children }) {
    return (
      <Box component="ul" sx={{ mb: 1, mt: 0.5, pl: 2.5 }}>
        {children}
      </Box>
    );
  },
  ol({ children }) {
    return (
      <Box component="ol" sx={{ mb: 1, mt: 0.5, pl: 2.5 }}>
        {children}
      </Box>
    );
  },
  li({ children }) {
    return (
      <Box component="li" sx={{ mb: 0.5, pl: 0.25, "&::marker": { color: "primary.main", fontWeight: 800 } }}>
        {children}
      </Box>
    );
  },
  blockquote({ children }) {
    return (
      <Box
        component="blockquote"
        sx={{
          bgcolor: "rgba(91,92,246,0.08)",
          borderLeft: 4,
          borderColor: "primary.main",
          borderRadius: "10px",
          color: "text.secondary",
          m: 0,
          my: 1.25,
          px: 1.5,
          py: 1,
          "& > :last-child": { mb: 0 },
        }}
      >
        {children}
      </Box>
    );
  },
  code({ children, className }) {
    const isCodeBlock = Boolean(className?.includes("language-"));
    if (isCodeBlock) {
      return (
        <Box component="code" className={className}>
          {children}
        </Box>
      );
    }
    return (
      <Box
        component="code"
        sx={{
          bgcolor: "rgba(91,92,246,0.11)",
          border: "1px solid rgba(91,92,246,0.12)",
          borderRadius: "6px",
          color: "primary.dark",
          fontFamily: "var(--font-mono), Consolas, Monaco, monospace",
          fontSize: "0.92em",
          px: 0.55,
          py: 0.15,
        }}
      >
        {children}
      </Box>
    );
  },
  pre({ children }) {
    return <CodeBlock>{children}</CodeBlock>;
  },
  table({ children }) {
    return (
      <TableContainer
        sx={{
          border: "1px solid rgba(91,92,246,0.14)",
          borderRadius: "12px",
          my: 1.5,
          maxWidth: "100%",
          overflowX: "auto",
        }}
      >
        <Table size="small">{children}</Table>
      </TableContainer>
    );
  },
  thead({ children }) {
    return <TableHead sx={{ bgcolor: "#e6e1ff" }}>{children}</TableHead>;
  },
  tbody({ children }) {
    return <TableBody>{children}</TableBody>;
  },
  tr({ children }) {
    return <TableRow>{children}</TableRow>;
  },
  th({ children }) {
    return (
      <TableCell
        component="th"
        sx={{
          borderColor: "rgba(91,92,246,0.12)",
          color: "text.primary",
          fontWeight: 850,
          lineHeight: 1.45,
          whiteSpace: "nowrap",
        }}
      >
        {children}
      </TableCell>
    );
  },
  td({ children }) {
    return (
      <TableCell
        sx={{
          borderColor: "rgba(91,92,246,0.1)",
          lineHeight: 1.55,
          overflowWrap: "anywhere",
          verticalAlign: "top",
          whiteSpace: "normal",
        }}
      >
        {children}
      </TableCell>
    );
  },
  a({ children, href }) {
    const hrefValue = safeHref(href);
    if (!hrefValue) {
      return <Box component="span">{children}</Box>;
    }
    return (
      <Link href={hrefValue} rel="noopener noreferrer" target="_blank" underline="hover">
        {children}
      </Link>
    );
  },
  hr() {
    return <Divider sx={{ my: 2 }} />;
  },
  img() {
    return null;
  },
};

export function MarkdownMessage({ content }: MarkdownMessageProps) {
  return (
    <Box
      className="markdown-message"
      sx={{
        color: "text.primary",
        fontSize: 14,
        lineHeight: 1.7,
        maxWidth: "100%",
        overflowWrap: "anywhere",
        "& > :first-of-type": { mt: 0 },
        "& > :last-child": { mb: 0 },
      }}
    >
      <ReactMarkdown
        components={markdownComponents}
        disallowedElements={disallowedElements}
        rehypePlugins={[rehypeSanitize]}
        remarkPlugins={[remarkGfm]}
        skipHtml
        unwrapDisallowed
      >
        {content}
      </ReactMarkdown>
    </Box>
  );
}
