"use client";

import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { useState } from "react";
import { api } from "@/lib/api/client";
import { Badge, Button, Card, CardHeader, EmptyState, ErrorState, Input, PageHeader } from "@/components/ui/primitives";

interface ActivityItem {
  id: string;
  ts: string;
  source: "audit" | "llm";
  kind: string;
  status: string;
  tool?: string;
  risk?: string;
  actor?: string;
  provider?: string;
  model?: string;
  latency_ms?: number;
  tokens?: number;
  error_code?: string;
  detail: Record<string, unknown>;
}

interface ActivityResponse {
  items: ActivityItem[];
  total: number;
  viewer_role: string;
}

interface UsageResponse {
  days: number;
  total_requests: number;
  total_tokens: number;
  error_rate: number;
  models: { provider: string; model: string; requests: number; errors: number; tokens: number; avg_latency_ms: number }[];
}

export default function ActivityPage() {
  const [source, setSource] = useState<"all" | "audit" | "llm">("all");
  const [query, setQuery] = useState("");
  const [offset, setOffset] = useState(0);
  const limit = 50;
  const activityQuery = `/activity?limit=${limit}&offset=${offset}&source=${source}&q=${encodeURIComponent(query)}`;
  const activity = useQuery({ queryKey: ["activity", activityQuery], queryFn: () => api.get<ActivityResponse>(activityQuery) });
  const usage = useQuery({ queryKey: ["analytics", "usage"], queryFn: () => api.get<UsageResponse>("/analytics/usage?days=7") });

  return (
    <div className="space-y-5 pb-10">
      <PageHeader title="Activity Logs" description="Server-side audit and LLM request history with correlation IDs, provider/model, status and token accounting." />
      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader title="Filters" description={`Viewing ${activity.data?.total ?? 0} events as ${activity.data?.viewer_role || "user"}`} />
          <div className="flex flex-wrap gap-2 p-4">
            <Input value={query} onChange={(e) => { setQuery(e.target.value); setOffset(0); }} placeholder="Filter audit actions" className="max-w-xs" />
            {(["all", "audit", "llm"] as const).map((value) => (
              <Button key={value} size="sm" variant={source === value ? "primary" : "ghost"} onClick={() => { setSource(value); setOffset(0); }}>{value}</Button>
            ))}
          </div>
        </Card>
        <Card>
          <CardHeader title="7-day usage" description="Real request logs only." />
          <div className="space-y-2 p-5 pt-0 text-caption">
            <p className="text-fg">requests: {usage.data?.total_requests ?? 0} · tokens: {usage.data?.total_tokens ?? 0} · error rate: {usage.data?.error_rate ?? 0}</p>
            {(usage.data?.models || []).slice(0, 4).map((model) => (
              <p key={`${model.provider}-${model.model}`} className="truncate text-fgmuted">{model.provider}/{model.model}: {model.requests} req, {model.errors} errors, {model.avg_latency_ms}ms avg</p>
            ))}
          </div>
        </Card>
      </div>

      {activity.isLoading && <Card><div className="p-6 text-body text-fgmuted">Loading activity…</div></Card>}
      {activity.isError && <Card><div className="p-6"><ErrorState message={activity.error.message} onRetry={() => void activity.refetch()} /></div></Card>}
      {activity.data?.items.length === 0 && <EmptyState title="No activity found" description="Adjust filters or use the Assistant to generate audited events." />}
      <div className="space-y-2">
        {(activity.data?.items || []).map((item) => (
          <Card key={`${item.source}-${item.id}`}>
            <div className="flex flex-wrap items-start gap-3 p-3.5">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone={item.source === "audit" ? "accent" : "neutral"}>{item.source}</Badge>
                  <span className="font-mono text-caption font-semibold text-fg">{item.kind}</span>
                  <Badge tone={item.status === "ok" || item.status === "success" ? "success" : item.status === "error" || item.status === "denied" ? "danger" : "warning"}>{item.status}</Badge>
                  {item.tool && <Badge tone="neutral">{item.tool}</Badge>}
                  {item.provider && <Badge tone="neutral">{item.provider}/{item.model}</Badge>}
                  {item.risk && <Badge tone={item.risk === "high" ? "danger" : "warning"}>{item.risk}</Badge>}
                </div>
                <p className="mt-1 text-caption text-fgmuted">
                  {new Date(item.ts).toLocaleString()} · {item.actor || "system"}{item.latency_ms !== undefined ? ` · ${item.latency_ms}ms` : ""}{item.tokens !== undefined ? ` · ${item.tokens} tokens` : ""}
                </p>
                <details className="mt-2">
                  <summary className="cursor-pointer text-caption text-accent">Details</summary>
                  <pre className="mt-2 max-h-48 overflow-auto rounded-md border border-edge bg-bg/50 p-2 text-[11px] text-fgmuted">{JSON.stringify(item.detail, null, 2)}</pre>
                </details>
              </div>
            </div>
          </Card>
        ))}
      </div>
      <div className={clsx("flex gap-2", offset === 0 && "justify-end")}>
        {offset > 0 && <Button variant="secondary" onClick={() => setOffset(Math.max(0, offset - limit))}>Previous</Button>}
        {(activity.data?.total || 0) >= limit && <Button variant="secondary" onClick={() => setOffset(offset + limit)}>Next</Button>}
      </div>
    </div>
  );
}
