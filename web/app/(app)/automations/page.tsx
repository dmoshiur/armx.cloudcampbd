"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, describeError } from "@/lib/api/client";
import { Badge, Button, Card, CardHeader, EmptyState, ErrorState, Input, Label, PageHeader } from "@/components/ui/primitives";
import { Switch } from "@/components/ui/switch";
import { useToast } from "@/components/ui/toast";

interface Automation {
  id: string;
  name: string;
  trigger: string;
  action: string;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

interface RunResult {
  ok: boolean;
  message: string;
  detail: Record<string, unknown>;
}

export default function AutomationsPage() {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [form, setForm] = useState({ name: "", trigger: "manual", action: "health_check", enabled: true });
  const [lastRun, setLastRun] = useState<RunResult | null>(null);
  const list = useQuery({ queryKey: ["automations"], queryFn: () => api.get<Automation[]>("/automations") });
  const invalidate = () => void queryClient.invalidateQueries({ queryKey: ["automations"] });

  const create = useMutation({
    mutationFn: () => api.post<Automation>("/automations", form),
    onSuccess: () => {
      setForm({ name: "", trigger: "manual", action: "health_check", enabled: true });
      toast.push("Automation created.", "success");
      invalidate();
    },
    onError: (err) => toast.push(describeError(err, "create this automation"), "error"),
  });

  const patch = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Record<string, unknown> }) => api.patch(`/automations/${id}`, body),
    onSuccess: invalidate,
    onError: (err) => toast.push(describeError(err, "update this automation"), "error"),
  });

  const remove = useMutation({
    mutationFn: (id: string) => api.del(`/automations/${id}`),
    onSuccess: invalidate,
    onError: (err) => toast.push(describeError(err, "delete this automation"), "error"),
  });

  const run = useMutation({
    mutationFn: (id: string) => api.post<RunResult>(`/automations/${id}/run`, {}),
    onSuccess: (result) => {
      setLastRun(result);
      toast.push(result.message, result.ok ? "success" : "info");
      void queryClient.invalidateQueries({ queryKey: ["activity"] });
    },
    onError: (err) => toast.push(describeError(err, "run this automation"), "error"),
  });

  return (
    <div className="space-y-5 pb-10">
      <PageHeader title="Automations" description="Allowlisted manual, time and device-event actions. Execution results are honest and audited." />
      <Card>
        <CardHeader title="Create automation" description="Supported triggers: manual, time:HH:MM, event:device_offline. Actions: alarm, health_check, notify." />
        <div className="grid gap-3 p-4 md:grid-cols-4">
          <div>
            <Label htmlFor="automation-name">Name</Label>
            <Input id="automation-name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Morning health check" />
          </div>
          <div>
            <Label htmlFor="automation-trigger">Trigger</Label>
            <select id="automation-trigger" value={form.trigger} onChange={(e) => setForm({ ...form, trigger: e.target.value })} className="h-touch w-full rounded-md border border-edge bg-bg px-3 text-caption text-fg">
              <option value="manual">manual</option>
              <option value="time:08:00">time:08:00</option>
              <option value="event:device_offline">event:device_offline</option>
            </select>
          </div>
          <div>
            <Label htmlFor="automation-action">Action</Label>
            <select id="automation-action" value={form.action} onChange={(e) => setForm({ ...form, action: e.target.value })} className="h-touch w-full rounded-md border border-edge bg-bg px-3 text-caption text-fg">
              <option value="health_check">health_check</option>
              <option value="alarm">alarm</option>
              <option value="notify">notify</option>
            </select>
          </div>
          <div className="flex items-end">
            <Button className="w-full" onClick={() => create.mutate()} loading={create.isPending} disabled={form.name.trim().length < 2}>Create</Button>
          </div>
        </div>
      </Card>

      {list.isLoading && <Card><div className="p-6 text-body text-fgmuted">Loading automations…</div></Card>}
      {list.isError && <Card><div className="p-6"><ErrorState message={list.error.message} onRetry={() => void list.refetch()} /></div></Card>}
      {list.data?.length === 0 && <EmptyState title="No automations" description="Create a rule above; only allowlisted actions can run." />}

      <div className="space-y-3">
        {(list.data || []).map((rule) => (
          <Card key={rule.id}>
            <div className="flex flex-wrap items-start gap-4 p-4">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <h3 className="text-body font-semibold text-fg">{rule.name}</h3>
                  <Badge tone={rule.enabled ? "success" : "warning"}>{rule.enabled ? "enabled" : "disabled"}</Badge>
                  <Badge tone="accent">{rule.trigger}</Badge>
                  <Badge tone="neutral">{rule.action}</Badge>
                </div>
                <p className="mt-1 text-caption text-fgmuted">updated {new Date(rule.updated_at).toLocaleString()}</p>
              </div>
              <div className="w-full sm:w-56">
                <Switch label="Enabled" checked={rule.enabled} onChange={(enabled) => patch.mutate({ id: rule.id, body: { enabled } })} />
              </div>
              <div className="flex gap-2">
                <Button size="sm" variant="secondary" onClick={() => run.mutate(rule.id)} loading={run.isPending}>Run now</Button>
                <Button size="sm" variant="danger" onClick={() => window.confirm("Delete this automation?") && remove.mutate(rule.id)}>Delete</Button>
              </div>
            </div>
          </Card>
        ))}
      </div>

      {lastRun && (
        <Card>
          <CardHeader title="Last execution" description={lastRun.message} action={<Badge tone={lastRun.ok ? "success" : "warning"}>{lastRun.ok ? "ok" : "not completed"}</Badge>} />
          <pre className="max-h-64 overflow-auto p-5 pt-0 text-[11px] text-fgmuted">{JSON.stringify(lastRun.detail, null, 2)}</pre>
        </Card>
      )}
    </div>
  );
}
