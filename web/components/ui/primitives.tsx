"use client";

import clsx from "clsx";
import Link from "next/link";
import { forwardRef, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode, type TextareaHTMLAttributes } from "react";

/* ---------------------------------------------------------------- Button */
type Variant = "primary" | "secondary" | "ghost" | "danger";
type Size = "sm" | "md" | "lg";

const variants: Record<Variant, string> = {
  primary: "bg-accent text-ink hover:brightness-110 active:brightness-95",
  secondary: "border border-edge bg-surface text-fg hover:bg-white/5",
  ghost: "text-fg hover:bg-white/5",
  danger: "border border-danger/40 text-danger hover:bg-danger/10",
};

const sizes: Record<Size, string> = {
  sm: "min-h-[40px] px-3 text-caption",
  md: "min-h-touch px-4 text-body",
  lg: "min-h-[52px] px-6 text-body",
};

export function Button({
  variant = "primary",
  size = "md",
  loading = false,
  className,
  children,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: Size; loading?: boolean }) {
  return (
    <button
      className={clsx(
        "inline-flex items-center justify-center gap-2 rounded-md font-semibold transition disabled:cursor-not-allowed disabled:opacity-50",
        variants[variant],
        sizes[size],
        className,
      )}
      disabled={props.disabled || loading}
      {...props}
    >
      {loading && <Spinner className="h-4 w-4" />}
      {children}
    </button>
  );
}

export function Spinner({ className }: { className?: string }) {
  return (
    <span
      role="status"
      aria-label="Loading"
      className={clsx("inline-block animate-spin rounded-full border-2 border-current border-t-transparent", className ?? "h-4 w-4")}
    />
  );
}

/* ---------------------------------------------------------------- Card */
export function Card({
  className,
  children,
  as: Tag = "div",
}: {
  className?: string;
  children: ReactNode;
  as?: "div" | "section" | "article";
}) {
  return (
    <Tag className={clsx("rounded-lg border border-edge bg-surface", className)}>{children}</Tag>
  );
}

export function CardHeader({ title, description, action }: { title: string; description?: string; action?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3 border-b border-edge px-5 py-4">
      <div>
        <h3 className="text-h3">{title}</h3>
        {description && <p className="mt-1 text-caption text-fgmuted">{description}</p>}
      </div>
      {action}
    </div>
  );
}

/* ---------------------------------------------------------------- Field */
export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement> & { invalid?: boolean }>(
  function Input({ className, invalid, ...props }, ref) {
    return (
      <input
        ref={ref}
        aria-invalid={invalid || undefined}
        className={clsx(
          "min-h-touch w-full rounded-md border bg-bg px-3 text-body text-fg placeholder:text-fgmuted/60 transition",
          invalid ? "border-danger" : "border-edge",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
          className,
        )}
        {...props}
      />
    );
  },
);

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(
  function Textarea({ className, ...props }, ref) {
    return (
      <textarea
        ref={ref}
        className={clsx(
          "w-full rounded-md border border-edge bg-bg px-3 py-2.5 text-body text-fg placeholder:text-fgmuted/60",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
          className,
        )}
        {...props}
      />
    );
  },
);

export function Label({ children, htmlFor, hint }: { children: ReactNode; htmlFor?: string; hint?: string }) {
  return (
    <div className="mb-1.5 flex items-baseline justify-between gap-3">
      <label htmlFor={htmlFor} className="text-caption font-semibold text-fg">
        {children}
      </label>
      {hint && <span className="text-caption text-fgmuted">{hint}</span>}
    </div>
  );
}

export function FieldError({ children }: { children?: ReactNode }) {
  if (!children) return null;
  return (
    <p role="alert" className="mt-1.5 text-caption text-danger">
      {children}
    </p>
  );
}

/* ---------------------------------------------------------------- Badge */
const badgeTones = {
  neutral: "border-edge bg-bg text-fgmuted",
  accent: "border-accent/40 bg-accent/10 text-accent",
  success: "border-success/40 bg-success/10 text-success",
  warning: "border-warning/40 bg-warning/10 text-warning",
  danger: "border-danger/40 bg-danger/10 text-danger",
} as const;

export function Badge({
  children,
  tone = "neutral",
  className,
}: {
  children: ReactNode;
  tone?: keyof typeof badgeTones;
  className?: string;
}) {
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-caption font-medium",
        badgeTones[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

export function StatusDot({ tone = "success", label }: { tone?: "success" | "warning" | "danger" | "idle"; label: string }) {
  const color = { success: "bg-success", warning: "bg-warning", danger: "bg-danger", idle: "bg-fgmuted" }[tone];
  return (
    <span className="inline-flex items-center gap-2 text-caption text-fgmuted">
      <span className={clsx("h-2 w-2 rounded-full", color)} aria-hidden="true" />
      {label}
    </span>
  );
}

export function RiskBadge({ risk }: { risk: string }) {
  const tone = risk === "high" ? "danger" : risk === "medium" ? "warning" : "success";
  return <Badge tone={tone}>{risk.toUpperCase()} risk</Badge>;
}

/* ---------------------------------------------------------------- States */
export function EmptyState({
  title,
  description,
  action,
  icon = "◇",
}: {
  title: string;
  description?: string;
  action?: ReactNode;
  icon?: string;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-edge px-6 py-14 text-center">
      <span aria-hidden="true" className="grid h-10 w-10 place-items-center rounded-lg bg-bg text-lg text-fgmuted">
        {icon}
      </span>
      <h3 className="text-h3">{title}</h3>
      {description && <p className="max-w-md text-body text-fgmuted">{description}</p>}
      {action}
    </div>
  );
}

export function ErrorState({ title = "Something went wrong", message, onRetry }: { title?: string; message?: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="rounded-lg border border-danger/40 bg-danger/5 px-5 py-6">
      <h3 className="text-h3 text-danger">{title}</h3>
      {message && <p className="mt-1.5 text-body text-fgmuted">{message}</p>}
      {onRetry && (
        <Button variant="secondary" size="sm" className="mt-4" onClick={onRetry}>
          Try again
        </Button>
      )}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={clsx("animate-pulse rounded-md bg-white/5", className)} />;
}

export function LoadingBlock({ label = "Loading" }: { label?: string }) {
  return (
    <div className="space-y-3" aria-busy="true" aria-live="polite">
      <span className="sr-only">{label}</span>
      <Skeleton className="h-5 w-40" />
      <Skeleton className="h-24 w-full" />
      <Skeleton className="h-24 w-full" />
    </div>
  );
}

/* ---------------------------------------------------------------- Nav */
export function LinkButton({ href, children, variant = "secondary" }: { href: string; children: ReactNode; variant?: Variant }) {
  return (
    <Link
      href={href}
      className={clsx(
        "inline-flex min-h-touch items-center justify-center gap-2 rounded-md px-4 text-body font-semibold transition",
        variants[variant],
      )}
    >
      {children}
    </Link>
  );
}

export function PageHeader({ title, description, action }: { title: string; description?: string; action?: ReactNode }) {
  return (
    <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-h1">{title}</h1>
        {description && <p className="mt-1.5 max-w-2xl text-body text-fgmuted">{description}</p>}
      </div>
      {action}
    </header>
  );
}

export function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="rounded border border-edge bg-bg px-1.5 py-0.5 font-mono text-[11px] text-fgmuted">{children}</kbd>
  );
}
