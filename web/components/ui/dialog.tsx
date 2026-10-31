"use client";

import { useEffect, useRef, type ReactNode } from "react";
import clsx from "clsx";
import { Button, RiskBadge } from "./primitives";

/** Accessible modal: focus trap-lite, Escape to close, scroll lock, labelled. */
export function Dialog({
  open,
  onClose,
  title,
  description,
  children,
  footer,
  tone = "default",
  labelledBy = "dialog-title",
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: string;
  children?: ReactNode;
  footer?: ReactNode;
  tone?: "default" | "danger";
  labelledBy?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    ref.current?.focus();
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-ink/70 p-0 backdrop-blur-sm sm:items-center sm:p-6">
      <div
        className="absolute inset-0"
        aria-hidden="true"
        onClick={onClose}
      />
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-labelledby={labelledBy}
        tabIndex={-1}
        className={clsx(
          "animate-fade-up relative w-full max-w-lg rounded-t-xl border bg-surface p-6 shadow-2xl shadow-black/40 sm:rounded-xl",
          tone === "danger" ? "border-danger/40" : "border-edge",
        )}
      >
        <h2 id={labelledBy} className="text-h2">
          {title}
        </h2>
        {description && <p className="mt-2 text-body text-fgmuted">{description}</p>}
        {children && <div className="mt-4">{children}</div>}
        {footer && <div className="mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">{footer}</div>}
      </div>
    </div>
  );
}

/**
 * Every MEDIUM/HIGH action shows this. The human sees the exact tool, risk tier
 * and arguments - including the deploy destination - before anything runs.
 */
export function ConfirmActionDialog({
  open,
  onCancel,
  onConfirm,
  busy,
  tool,
  risk,
  title,
  args,
  consequences,
  confirmLabel = "Approve and run",
}: {
  open: boolean;
  onCancel: () => void;
  onConfirm: () => void;
  busy?: boolean;
  tool: string;
  risk: string;
  title?: string;
  args?: Record<string, unknown>;
  consequences?: string[];
  confirmLabel?: string;
}) {
  const high = risk === "high";
  return (
    <Dialog
      open={open}
      onClose={onCancel}
      tone={high ? "danger" : "default"}
      title={title ?? `${high ? "High" : "Medium"}-risk action needs your approval`}
      description="Nothing runs until you approve. This approval is single-use and expires in two minutes."
      footer={
        <>
          <Button variant="ghost" onClick={onCancel} disabled={busy}>
            Cancel
          </Button>
          <Button variant={high ? "danger" : "primary"} onClick={onConfirm} loading={busy}>
            {confirmLabel}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <div className="flex items-center gap-2">
          <code className="rounded bg-bg px-2 py-1 font-mono text-caption text-accent">{tool}</code>
          <RiskBadge risk={risk} />
        </div>
        {args && Object.keys(args).length > 0 && (
          <dl className="space-y-1.5 rounded-md border border-edge bg-bg p-3 text-caption">
            {Object.entries(args).map(([key, value]) => (
              <div key={key} className="flex gap-3">
                <dt className="min-w-[7rem] shrink-0 text-fgmuted">{key}</dt>
                <dd className="break-words font-mono text-fg">
                  {typeof value === "string" ? value : JSON.stringify(value)}
                </dd>
              </div>
            ))}
          </dl>
        )}
        {consequences && consequences.length > 0 && (
          <ul className="list-inside list-disc space-y-1 text-caption text-fgmuted">
            {consequences.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        )}
      </div>
    </Dialog>
  );
}
