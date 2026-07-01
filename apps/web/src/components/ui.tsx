import type {
  ButtonHTMLAttributes,
  HTMLAttributes,
  ReactNode,
} from "react";

function classes(...values: Array<string | false | null | undefined>): string {
  return values.filter(Boolean).join(" ");
}

type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
type ButtonSize = "sm" | "md";
export type BadgeTone = "neutral" | "info" | "success" | "warning" | "danger";
type CardTone = "default" | "subtle";

export function statusTone(status: string | null | undefined): BadgeTone {
  if (status === "ready" || status === "completed" || status === "success") {
    return "success";
  }
  if (status === "failed" || status === "error") {
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

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  size?: ButtonSize;
  variant?: ButtonVariant;
}

export function Button({
  className,
  size = "md",
  variant = "primary",
  type = "button",
  ...props
}: ButtonProps) {
  return (
    <button
      className={classes(
        "ui-button",
        variant,
        size,
        "button",
        variant !== "primary" && variant,
        className,
      )}
      type={type}
      {...props}
    />
  );
}

interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  tone?: BadgeTone;
}

export function Badge({children, className, tone = "neutral", ...props}: BadgeProps) {
  return (
    <span className={classes("ui-badge", tone, "pill", className)} {...props}>
      {children}
    </span>
  );
}

interface CardProps extends HTMLAttributes<HTMLElement> {
  children: ReactNode;
  tone?: CardTone;
}

export function Card({children, className, tone = "default", ...props}: CardProps) {
  return (
    <section className={classes("panel", "ui-card", tone !== "default" && tone, className)} {...props}>
      {children}
    </section>
  );
}

interface EmptyStateProps extends HTMLAttributes<HTMLDivElement> {
  title?: string;
  children?: ReactNode;
}

export function EmptyState({title, children, className, ...props}: EmptyStateProps) {
  return (
    <div className={classes("empty", "empty-state", className)} {...props}>
      {title && <strong>{title}</strong>}
      {children && <span>{children}</span>}
    </div>
  );
}

interface SkeletonBlockProps extends HTMLAttributes<HTMLDivElement> {
  lines?: number;
}

export function SkeletonBlock({className, lines = 3, ...props}: SkeletonBlockProps) {
  return (
    <div className={classes("skeleton-block", className)} {...props}>
      {Array.from({length: lines}).map((_, index) => (
        <span key={index} />
      ))}
    </div>
  );
}

export function FieldHint({children, className, ...props}: HTMLAttributes<HTMLParagraphElement>) {
  return (
    <p className={classes("field-hint", className)} {...props}>
      {children}
    </p>
  );
}

interface SectionHeaderProps extends HTMLAttributes<HTMLDivElement> {
  title: string;
  eyebrow?: string;
  actions?: ReactNode;
}

export function SectionHeader({
  actions,
  className,
  eyebrow,
  title,
  ...props
}: SectionHeaderProps) {
  return (
    <div className={classes("section-header", className)} {...props}>
      <div>
        {eyebrow && <span className="eyebrow">{eyebrow}</span>}
        <h2>{title}</h2>
      </div>
      {actions && <div className="section-actions">{actions}</div>}
    </div>
  );
}
