"use client";

import clsx from "clsx";
import Link from "next/link";
import { useId, useState, type ReactNode } from "react";

export function AuthBrand() {
  return (
    <div className="mb-6 text-center">
      <Link href="/login" aria-label="A.R.M.X AI sign in" className="inline-flex items-center gap-3">
        <span className="relative grid h-11 w-11 place-items-center rounded-xl border border-accent/50 bg-gradient-to-br from-accent to-emerald-500 text-xl font-black text-ink shadow-[0_0_28px_rgba(0,255,65,0.18)]">
          A
          <span className="absolute -right-1 -top-1 h-2.5 w-2.5 rounded-full border-2 border-[#010503] bg-accent" />
        </span>
        <span className="text-left">
          <span className="block text-h3 font-bold tracking-[-0.03em] text-fg">A.R.M.X AI</span>
          <span className="block text-[9px] font-semibold uppercase tracking-[0.28em] text-accent/70">Control Intelligence</span>
        </span>
      </Link>
    </div>
  );
}

export function AuthCard({
  title,
  subtitle,
  children,
  footer,
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
  footer?: ReactNode;
}) {
  return (
    <section className="animate-fade-up w-full max-w-[420px] rounded-2xl border border-edge/80 bg-surface/85 p-6 shadow-[0_24px_70px_rgba(0,0,0,0.55),0_0_0_1px_rgba(0,255,65,0.04)] backdrop-blur-md sm:p-7">
      <header className="mb-5 text-center">
        <h1 className="text-h2 font-bold tracking-[-0.025em] text-fg">{title}</h1>
        {subtitle && <p className="mt-1.5 text-body text-fgmuted">{subtitle}</p>}
      </header>
      {children}
      {footer && <div className="mt-6 border-t border-edge/60 pt-4 text-center text-caption text-fgmuted">{footer}</div>}
    </section>
  );
}

export function Notice({
  tone = "error",
  children,
  title,
}: {
  tone?: "error" | "success" | "info";
  children: ReactNode;
  title?: string;
}) {
  return (
    <div
      role={tone === "error" ? "alert" : "status"}
      aria-live={tone === "error" ? "assertive" : "polite"}
      className={clsx(
        "rounded-lg border px-3 py-2.5 text-body",
        tone === "error" && "border-danger/45 bg-danger/10 text-danger",
        tone === "success" && "border-success/45 bg-success/10 text-success",
        tone === "info" && "border-edge bg-bg/60 text-fgmuted",
      )}
    >
      {title && <p className="mb-0.5 font-semibold">{title}</p>}
      <div>{children}</div>
    </div>
  );
}

export function TextField({
  id,
  label,
  value,
  onChange,
  type = "text",
  autoComplete,
  placeholder,
  error,
  hint,
  disabled,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: string;
  autoComplete?: string;
  placeholder?: string;
  error?: string;
  hint?: string;
  disabled?: boolean;
}) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="block text-caption font-semibold text-fg">{label}</label>
      <input
        id={id}
        type={type}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        autoComplete={autoComplete}
        placeholder={placeholder}
        disabled={disabled}
        aria-invalid={Boolean(error)}
        aria-describedby={error ? `${id}-error` : hint ? `${id}-hint` : undefined}
        className="h-11 w-full rounded-lg border border-edge bg-bg/70 px-3.5 text-body text-fg outline-none transition placeholder:text-fgmuted/50 focus:border-accent/70 focus:ring-2 focus:ring-accent/10 disabled:opacity-60"
      />
      {error && <p id={`${id}-error`} className="text-caption text-danger">{error}</p>}
      {!error && hint && <p id={`${id}-hint`} className="text-caption text-fgmuted">{hint}</p>}
    </div>
  );
}

export function PasswordField({
  id,
  label,
  value,
  onChange,
  autoComplete,
  placeholder = "••••••••••",
  error,
  hint,
  showStrength = false,
  disabled,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  autoComplete?: string;
  placeholder?: string;
  error?: string;
  hint?: string;
  showStrength?: boolean;
  disabled?: boolean;
}) {
  const [visible, setVisible] = useState(false);
  const strength = passwordScore(value);
  const labels = ["Too weak", "Weak", "Fair", "Good", "Strong"];
  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="block text-caption font-semibold text-fg">{label}</label>
      <div className="relative">
        <input
          id={id}
          type={visible ? "text" : "password"}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          autoComplete={autoComplete}
          placeholder={placeholder}
          disabled={disabled}
          aria-invalid={Boolean(error)}
          aria-describedby={error ? `${id}-error` : hint ? `${id}-hint` : undefined}
          className="h-11 w-full rounded-lg border border-edge bg-bg/70 px-3.5 pr-12 text-body text-fg outline-none transition placeholder:text-fgmuted/50 focus:border-accent/70 focus:ring-2 focus:ring-accent/10 disabled:opacity-60"
        />
        <button
          type="button"
          onClick={() => setVisible((v) => !v)}
          aria-label={visible ? `Hide ${label.toLowerCase()}` : `Show ${label.toLowerCase()}`}
          aria-pressed={visible}
          className="absolute right-1 top-1 grid h-9 w-9 place-items-center rounded-md text-fgmuted transition hover:bg-white/5 hover:text-fg"
        >
          {visible ? "◉" : "◎"}
        </button>
      </div>
      {showStrength && (
        <div className="pt-1">
          <div className="flex gap-1" aria-hidden="true">
            {[0, 1, 2, 3].map((index) => (
              <span
                key={index}
                className={clsx(
                  "h-1 flex-1 rounded-full transition-colors",
                  value && index < strength ? (strength >= 4 ? "bg-success" : strength >= 3 ? "bg-accent" : "bg-warning") : "bg-edge",
                )}
              />
            ))}
          </div>
          <p className="mt-1 text-[11px] text-fgmuted">
            {value ? `${labels[strength]} · ` : ""}10+ characters, an uppercase letter and a symbol
          </p>
        </div>
      )}
      {error && <p id={`${id}-error`} className="text-caption text-danger">{error}</p>}
      {!error && hint && <p id={`${id}-hint`} className="text-caption text-fgmuted">{hint}</p>}
    </div>
  );
}

export function passwordScore(value: string): number {
  let score = 0;
  if (value.length >= 10) score += 1;
  if (/[A-Z]/.test(value) && /[a-z]/.test(value)) score += 1;
  if (/[^A-Za-z0-9]/.test(value)) score += 1;
  if (value.length >= 14 && /\d/.test(value)) score += 1;
  return Math.min(4, score);
}

export function PasswordRequirements({ password }: { password: string }) {
  const rules = [
    { label: "At least 10 characters", ok: password.length >= 10 },
    { label: "Upper and lowercase letters", ok: /[A-Z]/.test(password) && /[a-z]/.test(password) },
    { label: "A symbol", ok: /[^A-Za-z0-9]/.test(password) },
    { label: "Not a common password", ok: !/^(password123!|armx12345!|letmein123!)$/i.test(password) },
  ];
  return (
    <ul className="grid grid-cols-1 gap-1 text-[11px] text-fgmuted sm:grid-cols-2">
      {rules.map((rule) => (
        <li key={rule.label} className={clsx("flex items-center gap-1.5", rule.ok && "text-success")}>
          <span aria-hidden="true">{rule.ok ? "✓" : "○"}</span>
          {rule.label}
        </li>
      ))}
    </ul>
  );
}

export function PrimaryButton({
  children,
  busy,
  disabled,
  type = "submit",
}: {
  children: ReactNode;
  busy?: boolean;
  disabled?: boolean;
  type?: "submit" | "button";
}) {
  return (
    <button
      type={type}
      disabled={busy || disabled}
      className="inline-flex h-11 w-full items-center justify-center gap-2 rounded-lg bg-gradient-to-br from-accent to-emerald-400 text-body font-bold text-ink shadow-[0_8px_24px_rgba(0,255,65,0.14)] transition hover:brightness-110 active:brightness-95 disabled:cursor-not-allowed disabled:opacity-55"
    >
      {busy && <span className="h-4 w-4 animate-spin rounded-full border-2 border-ink/50 border-t-transparent" />}
      {children}
    </button>
  );
}

export function AuthFooterLinks({ children }: { children: ReactNode }) {
  return <div className="flex flex-wrap items-center justify-center gap-x-4 gap-y-1 text-caption">{children}</div>;
}

export function AuthLink({ href, children }: { href: string; children: ReactNode }) {
  return <Link href={href} className="text-fgmuted transition hover:text-accent hover:underline">{children}</Link>;
}

export function useFieldId(prefix: string) {
  const generated = useId();
  return `${prefix}-${generated.replace(/:/g, "")}`;
}
