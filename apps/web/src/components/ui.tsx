import Box from "@mui/material/Box";
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

  return (
    <MuiButton
      color={color}
      size={size === "sm" ? "small" : "medium"}
      type={type}
      variant={mappedVariant}
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

export function Badge({ children, tone = "neutral", variant = "filled", ...props }: BadgeProps) {
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
      variant={tone === "neutral" ? "outlined" : variant}
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
        bgcolor: tone === "subtle" ? "grey.50" : "background.paper",
        ...sx,
      }}
      {...props}
    >
      <CardContent sx={{ "&:last-child": { pb: 3 }, p: { xs: 2, sm: 3 } }}>
        {children}
      </CardContent>
    </MuiCard>
  );
}

interface EmptyStateProps extends HTMLAttributes<HTMLDivElement> {
  title?: string;
  children?: ReactNode;
}

export function EmptyState({ title, children, ...props }: EmptyStateProps) {
  return (
    <Box
      {...props}
      sx={{
        alignItems: "center",
        border: "1px dashed",
        borderColor: "divider",
        borderRadius: 2,
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
      {title && (
        <Typography color="text.primary" sx={{ fontWeight: 750 }} variant="h6">
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
          <Typography color="text.secondary" sx={{ fontWeight: 800, textTransform: "uppercase" }} variant="caption">
            {eyebrow}
          </Typography>
        )}
        <Typography component="h2" sx={{ fontWeight: 800 }} variant="h6">
          {title}
        </Typography>
      </Box>
      {actions && <Box>{actions}</Box>}
    </Stack>
  );
}
