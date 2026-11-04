"use client";

import clsx from "clsx";
import { useEffect, useState } from "react";
import type { Approval } from "@/lib/types";

function secondsLeft(approval: Approval): number {
  if (typeof approval.seconds_remaining === "number") return approval.seconds_remaining;
  const ms = new Date(approval.expires_at).getTime() - Date.now();
  return Number.isFinite(ms) ? Math.max(0, Math.round(ms / 1000)) : 0;
}

export function ApprovalCard({
  approval,
  busy,
  onApprove,
  onReject,
  onRetry,
}: {
  approval: Approval;
  busy: boolean;
  onApprove: (approvalId: string) => void;
  onReject: (approvalId: string) => void;
  onRetry: (runId: string) => void;
}) {
  const [remaining, setRemaining] = useState(() => secondsLeft(approval));
  const [confirmed, setConfirmed] = useState(false);

  useEffect(() => setRemaining(secondsLeft(approval)), [approval]);
  useEffect(() => {
    const timer = window.setInterval(() => setRemaining((value) => Math.max(0, value - 1)), 1000);
    return () => window.clearInterval(timer);
  }, []);

  const expired = remaining <= 0 || approval.status === "expired";
  const highRisk = approval.risk === "high";

  return (
    <section className="animate-fade-up rounded-xl border border-warning/50 bg-warning/5 p-4 shadow-lg" aria-label="Approval required">
      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded border border-warning/50 bg-warning/10 px-2 py-0.5 text-[11px] font-bold uppercase tracking-wider text-warning">
          {expired ? "Approval expired" : "Approval required"}
        </span>
        <span className="font-mono text-caption text-fg">{approval.tool}</span>
        <span className="text-caption text-fgmuted">risk: {approval.risk}</span>
        <span className={clsx("ml-auto font-mono text-caption", expired ? "text-danger" : "text-fgmuted")}>
          {expired ? "no time remaining" : `${remaining}s remaining`}
        </span>
      </div>
      <p className="mt-2 text-body text-fg">{approval.description}</p>
      <details className="mt-2 rounded-md border border-edge/70 bg-bg/50 p-2">
        <summary className="cursor-pointer text-caption text-fgmuted">Exact arguments and action hash</summary>
        <pre className="mt-2 overflow-x-auto whitespace-pre-wrap break-all text-[11px] text-fgmuted">{JSON.stringify(approval.args, null, 2)}</pre>
        <p className="mt-1 break-all font-mono text-[10px] text-fgmuted/80">hash: {approval.action_hash}</p>
      </details>
      {expired ? (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <p className="text-caption text-danger">This approval cannot be reused. A fresh one must be issued for the same action.</p>
          <button
            type="button"
            disabled={busy || !approval.run_id}
            onClick={() => approval.run_id && onRetry(approval.run_id)}
            className="rounded-md border border-accent/60 bg-accent/10 px-3 py-1.5 text-caption font-semibold text-accent hover:bg-accent/20 disabled:opacity-50"
          >
            Ask again — create a new approval
          </button>
        </div>
      ) : (
        <div className="mt-3 space-y-3">
          {highRisk && (
            <label className="flex items-start gap-2 text-caption text-fgmuted">
              <input
                type="checkbox"
                checked={confirmed}
                onChange={(event) => setConfirmed(event.target.checked)}
                className="mt-0.5 h-4 w-4 accent-[rgb(var(--accent))]"
              />
              I understand this sensitive action will be executed with my permissions.
            </label>
          )}
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              disabled={busy || (highRisk && !confirmed)}
              onClick={() => onApprove(approval.id)}
              className="rounded-md bg-accent px-3 py-1.5 text-caption font-bold text-ink disabled:opacity-50"
            >
              Approve & execute
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => onReject(approval.id)}
              className="rounded-md border border-edge px-3 py-1.5 text-caption text-fgmuted hover:border-danger/50 hover:text-danger disabled:opacity-50"
            >
              Reject
            </button>
            {approval.can_retry && approval.run_id && (
              <button
                type="button"
                disabled={busy}
                onClick={() => onRetry(approval.run_id!)}
                className="rounded-md border border-edge px-3 py-1.5 text-caption text-fgmuted hover:border-accent/50 hover:text-accent disabled:opacity-50"
              >
                Replace with a new approval
              </button>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
