"use client";

import clsx from "clsx";
import { Badge, RiskBadge } from "@/components/ui/primitives";
import type { ToolEvent } from "@/lib/types";

function extractPreview(event: ToolEvent): string | null {
  const data = event.result?.data as Record<string, unknown> | undefined;
  if (!data) return null;
  const url = data.preview_url;
  return typeof url === "string" ? url : null;
}

export function ToolEventCard({ event }: { event: ToolEvent }) {
  const preview = extractPreview(event);
  const data = (event.result?.data ?? {}) as Record<string, unknown>;
  const simulated = data.simulated === true;
  const liveUrl = typeof data.url === "string" ? data.url : undefined;
  const lint = data.lint as { ok?: boolean; score?: number; errors?: { message: string }[] } | undefined;

  return (
    <div className="rounded-lg border border-edge bg-surface">
      <div className="flex flex-wrap items-center gap-2 border-b border-edge px-4 py-3">
        <code className="rounded bg-bg px-2 py-0.5 font-mono text-caption text-accent">{event.tool}</code>
        {event.risk !== "unknown" && <RiskBadge risk={event.risk} />}
        {event.approved && <Badge tone="accent">approved</Badge>}
        <Badge tone={event.ok ? "success" : "danger"}>{event.ok ? "succeeded" : event.blocked ? "blocked" : "failed"}</Badge>
        {simulated && <Badge tone="warning">simulated</Badge>}
      </div>

      <div className="px-4 py-3 text-body">
        {event.blocked && <p className="text-warning">{event.blocked}</p>}
        {event.error && <p className="text-danger">{event.error}</p>}
        {event.result?.error && !event.error && <p className="text-danger">{event.result.error}</p>}
        {event.result?.message && <p className="text-fg">{event.result.message}</p>}

        {lint && (
          <p className={clsx("mt-2 text-caption", lint.ok ? "text-success" : "text-danger")}>
            Design audit {lint.ok ? "passed" : "found blocking issues"} · score {lint.score ?? "—"}
            {lint.errors?.length ? ` · ${lint.errors.slice(0, 2).map((e) => e.message).join("; ")}` : ""}
          </p>
        )}

        {liveUrl && (
          <a
            href={liveUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="mt-2 inline-block text-accent hover:underline"
          >
            Open live site ↗
          </a>
        )}
      </div>

      {preview && (
        <div className="border-t border-edge p-3">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-caption text-fgmuted">Sandbox preview</span>
            <a href={preview} target="_blank" rel="noopener noreferrer" className="text-caption text-accent hover:underline">
              Open in new tab ↗
            </a>
          </div>
          <iframe
            src={preview}
            title={`Preview of ${event.tool} output`}
            className="h-[380px] w-full rounded-md border border-edge bg-white"
            sandbox="allow-scripts allow-forms allow-popups"
          />
        </div>
      )}
    </div>
  );
}
