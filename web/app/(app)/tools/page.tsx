"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import type { IntegrationStatus, ToolInfo } from "@/lib/types";
import { Badge, Card, CardHeader, EmptyState, ErrorState, LoadingBlock, PageHeader, RiskBadge, StatusDot } from "@/components/ui/primitives";

const RISK_ORDER: Record<string, number> = { low: 0, medium: 1, high: 2 };

export default function ToolsPage() {
  const tools = useQuery({ queryKey: ["tools"], queryFn: () => api.get<ToolInfo[]>("/tools") });
  const integrations = useQuery({
    queryKey: ["integrations"],
    queryFn: () =>
      api.get<{ integrations: IntegrationStatus[]; planner: { provider: string; model: string; live: boolean }; kill_switch: string }>(
        "/integrations",
      ),
  });

  const grouped = (tools.data ?? [])
    .slice()
    .sort((a, b) => (RISK_ORDER[a.risk] ?? 9) - (RISK_ORDER[b.risk] ?? 9) || a.name.localeCompare(b.name));

  return (
    <div>
      <PageHeader
        title="Capabilities"
        description="Every capability is a small self-registering plugin. The model can only request one by name; the security gateway decides whether it runs."
      />

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
        <div>
          {tools.isLoading && <LoadingBlock label="Loading tools" />}
          {tools.isError && <ErrorState message={tools.error.message} onRetry={() => void tools.refetch()} />}
          {tools.data && grouped.length === 0 && <EmptyState title="No tools registered" />}

          <div className="space-y-3">
            {grouped.map((tool) => (
              <Card key={tool.name}>
                <div className="flex flex-wrap items-center gap-2 border-b border-edge px-4 py-3">
                  <code className="font-mono text-caption text-accent">{tool.name}</code>
                  <RiskBadge risk={tool.risk} />
                  <Badge>{tool.category}</Badge>
                  {tool.confirm && <Badge tone="warning">needs approval</Badge>}
                  {tool.dry_run_supported && <Badge>dry-run</Badge>}
                  <span className="ml-auto">
                    <StatusDot tone={tool.enabled ? "success" : "danger"} label={tool.enabled ? "enabled" : tool.reason || "disabled"} />
                  </span>
                </div>
                <p className="px-4 py-3 text-body text-fgmuted">{tool.description}</p>
              </Card>
            ))}
          </div>
        </div>

        <Card className="h-fit">
          <CardHeader
            title="Integrations"
            description={integrations.data ? `Kill-switch: ${integrations.data.kill_switch.toUpperCase()}` : "Checking…"}
          />
          <div className="divide-y divide-edge">
            {integrations.isLoading && (
              <div className="p-5">
                <LoadingBlock />
              </div>
            )}
            {integrations.data?.integrations.map((item) => (
              <div key={item.provider} className="flex items-start justify-between gap-3 px-4 py-3">
                <div>
                  <p className="text-body font-medium capitalize">{item.provider.replace(/_/g, " ")}</p>
                  <p className="text-caption text-fgmuted">{item.detail || item.mode}</p>
                </div>
                <Badge tone={item.simulated ? "warning" : item.configured ? "success" : "neutral"}>
                  {item.simulated ? "simulated" : item.configured ? item.mode : "not configured"}
                </Badge>
              </div>
            ))}
          </div>
          {integrations.data && (
            <p className="border-t border-edge px-4 py-3 text-caption text-fgmuted">
              Planner: <span className="text-fg">{integrations.data.planner.provider}</span> ·{" "}
              {integrations.data.planner.live ? "live model" : "offline planner — set ANTHROPIC_API_KEY for Claude"}
            </p>
          )}
        </Card>
      </div>
    </div>
  );
}
