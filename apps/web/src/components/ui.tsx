import Box from "@mui/material/Box";
import AutoAwesomeIcon from "@mui/icons-material/AutoAwesome";
import MuiButton from "@mui/material/Button";
import type { ButtonProps as MuiButtonProps } from "@mui/material/Button";
import MuiCard from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import type { CardProps as MuiCardProps } from "@mui/material/Card";
import Chip from "@mui/material/Chip";
import type { ChipProps } from "@mui/material/Chip";
import Skeleton from "@mui/material/Skeleton";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import type { HTMLAttributes, ReactNode } from "react";

type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
type ButtonSize = "sm" | "md";
export type BadgeTone = "neutral" | "info" | "success" | "warning" | "danger";
type CardTone = "default" | "subtle";
interface InfoGridRow {
  label: string;
  value: ReactNode;
}

export function statusTone(status: string | null | undefined): BadgeTone {
  if (status === "ready" || status === "completed" || status === "success") {
    return "success";
  }
  if (status === "failed" || status === "error" || status === "cancelled") {
    return "danger";
  }
  if (
    status === "processing" ||
    status === "uploading" ||
    status === "queued" ||
    status === "running"
  ) {
    return "warning";
  }
  if (status === "created" || status === "pending") {
    return "info";
  }
  return "neutral";
}

interface ButtonProps extends Omit<MuiButtonProps, "variant" | "size" | "color"> {
  size?: ButtonSize;
  variant?: ButtonVariant;
  type?: "button" | "submit" | "reset";
}

export function Button({
  children,
  size = "md",
  sx,
  variant = "primary",
  type = "button",
  ...props
}: ButtonProps) {
  const mappedVariant =
    variant === "primary" || variant === "danger"
      ? "contained"
      : variant === "secondary"
        ? "outlined"
        : "text";
  const color = variant === "danger" ? "error" : variant === "ghost" ? "inherit" : "primary";
  const variantSx = {
    ...(variant === "secondary"
      ? {
          bgcolor: "rgba(255,255,255,0.82)",
          borderColor: "rgba(91,92,246,0.22)",
          color: "primary.dark",
          "&:hover": {
            bgcolor: "rgba(91,92,246,0.08)",
            borderColor: "rgba(91,92,246,0.32)",
          },
        }
      : {}),
    ...(variant === "ghost"
      ? {
          bgcolor: "rgba(91,92,246,0.07)",
          color: "primary.dark",
          "&:hover": { bgcolor: "rgba(91,92,246,0.12)" },
        }
      : {}),
  };
  const sxArray = Array.isArray(sx) ? sx : sx ? [sx] : [];

  return (
    <MuiButton
      color={color}
      size={size === "sm" ? "small" : "medium"}
      type={type}
      variant={mappedVariant}
      sx={[variantSx, ...sxArray]}
      {...props}
    >
      {children}
    </MuiButton>
  );
}

interface BadgeProps extends Omit<ChipProps, "children" | "color" | "size" | "label"> {
  tone?: BadgeTone;
  children?: ReactNode;
}

export function Badge({ children, tone = "neutral", variant = "outlined", ...props }: BadgeProps) {
  const color =
    tone === "danger"
      ? "error"
      : tone === "neutral"
        ? "default"
        : (tone as "info" | "success" | "warning");

  return (
    <Chip
      color={color}
      label={children}
      size="small"
      variant={variant}
      {...props}
    />
  );
}

interface ColorBadgeProps extends Omit<ChipProps, "children" | "color" | "size" | "label"> {
  color: string;
  children?: ReactNode;
}

/** A chip tinted with an arbitrary semantic color (used for golden signals and log levels). */
export function ColorBadge({ children, color, sx, ...props }: ColorBadgeProps) {
  const sxArray = Array.isArray(sx) ? sx : sx ? [sx] : [];
  return (
    <Chip
      label={children}
      size="small"
      sx={[
        {
          bgcolor: `${color}1a`,
          border: `1px solid ${color}59`,
          color,
          fontWeight: 700,
        },
        ...sxArray,
      ]}
      {...props}
    />
  );
}

interface CardProps extends Omit<MuiCardProps, "variant"> {
  children: ReactNode;
  tone?: CardTone;
}

export function Card({ children, sx, tone = "default", ...props }: CardProps) {
  return (
    <MuiCard
      sx={{
        bgcolor: tone === "subtle" ? "rgba(217,236,255,0.55)" : "background.paper",
        borderRadius: "14px",
        ...sx,
      }}
      {...props}
    >
      <CardContent sx={{ "&:last-child": { pb: { xs: 2.5, sm: 3.5 } }, p: { xs: 2.5, sm: 3.5 } }}>
        {children}
      </CardContent>
    </MuiCard>
  );
}

interface EmptyStateProps extends HTMLAttributes<HTMLDivElement> {
  title?: string;
  children?: ReactNode;
  icon?: ReactNode;
}

export function EmptyState({ title, children, icon, ...props }: EmptyStateProps) {
  return (
    <Box
      {...props}
      sx={{
        alignItems: "center",
        background:
          "linear-gradient(180deg, rgba(255,255,255,0.92), rgba(244,247,255,0.72))",
        border: "1px solid",
        borderColor: "rgba(91,92,246,0.12)",
        borderRadius: "14px",
        color: "text.secondary",
        display: "flex",
        flexDirection: "column",
        gap: 1.5,
        justifyContent: "center",
        minHeight: 180,
        p: 4,
        textAlign: "center",
      }}
    >
      <Box
        sx={{
          alignItems: "center",
          bgcolor: "rgba(91,92,246,0.1)",
          borderRadius: "50%",
          color: "primary.main",
          display: "flex",
          height: 46,
          justifyContent: "center",
          width: 46,
        }}
      >
        {icon || <AutoAwesomeIcon fontSize="small" />}
      </Box>
      {title && (
        <Typography color="text.primary" component="p" sx={{ fontWeight: 750 }} variant="subtitle1">
          {title}
        </Typography>
      )}
      {children && <Box>{children}</Box>}
    </Box>
  );
}

interface SkeletonBlockProps extends HTMLAttributes<HTMLDivElement> {
  lines?: number;
}

export function SkeletonBlock({ lines = 3, ...props }: SkeletonBlockProps) {
  return (
    <Stack {...props} spacing={1}>
      {Array.from({ length: lines }).map((_, index) => (
        <Skeleton height={22} key={index} variant="rounded" />
      ))}
    </Stack>
  );
}

export function FieldHint({ children, ...props }: HTMLAttributes<HTMLParagraphElement>) {
  return (
    <Typography color="text.secondary" component="p" variant="caption" {...props}>
      {children}
    </Typography>
  );
}

export function InfoGrid({ minColumnWidth = 220, rows }: { minColumnWidth?: number; rows: InfoGridRow[] }) {
  return (
    <Box
      sx={{
        display: "grid",
        gap: 1.25,
        gridTemplateColumns: { xs: "1fr", sm: `repeat(auto-fit, minmax(${minColumnWidth}px, 1fr))` },
      }}
    >
      {rows.map((row) => (
        <Box
          key={row.label}
          sx={{
            bgcolor: "rgba(91,92,246,0.055)",
            border: "1px solid",
            borderColor: "rgba(91,92,246,0.1)",
            borderRadius: "10px",
            p: 1.75,
          }}
        >
          <Typography
            color="text.secondary"
            sx={{ display: "block", fontWeight: 800, letterSpacing: 0.4, mb: 0.5, textTransform: "uppercase" }}
            variant="caption"
          >
            {row.label}
          </Typography>
          <Box sx={{ color: "text.primary", fontWeight: 750, overflowWrap: "anywhere" }}>{row.value}</Box>
        </Box>
      ))}
    </Box>
  );
}

interface SectionHeaderProps extends HTMLAttributes<HTMLDivElement> {
  title: string;
  eyebrow?: string;
  actions?: ReactNode;
}

export function SectionHeader({ actions, eyebrow, title, ...props }: SectionHeaderProps) {
  return (
    <Stack
      direction={{ xs: "column", sm: "row" }}
      spacing={2}
      sx={{ alignItems: { xs: "flex-start", sm: "center" }, justifyContent: "space-between" }}
      {...props}
    >
      <Box>
        {eyebrow && (
          <Typography
            color="primary"
            sx={{ display: "block", fontWeight: 850, letterSpacing: 0.5, mb: 0.5, textTransform: "uppercase" }}
            variant="caption"
          >
            {eyebrow}
          </Typography>
        )}
        <Typography component="h2" sx={{ fontWeight: 850 }} variant="h6">
          {title}
        </Typography>
      </Box>
      {actions && <Box>{actions}</Box>}
    </Stack>
  );
}
