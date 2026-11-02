"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, ApiError } from "@/lib/api/client";
import { Badge, Button, Card, CardHeader, EmptyState, Input, Label, LoadingBlock, StatusDot } from "@/components/ui/primitives";
import { Switch } from "@/components/ui/switch";
import { useToast } from "@/components/ui/toast";

interface LlmModel {
  id: string;
  provider_id: string;
  model_id: string;
  display_name: string;
  enabled: boolean;
  priority: number;
  weight: number;
  max_tokens: number;
  status: string;
  consecutive_failures: number;
  circuit_open_until: string | null;
  last_error: string;
  last_success_at: string | null;
}

interface LlmProvider {
  id: string;
  name: string;
  display_name: string;
  kind: string;
  base_url: string;
  api_key_hint: string;
  enabled: boolean;
  source: string;
  status: string;
  last_error: string;
  models: LlmModel[];
}

interface LlmConfiguration {
  routing: {
    routing: string;
    enabled_models: number;
    healthy_models: number;
    provider: string;
    model: string;
  };
  providers: LlmProvider[];
}

const errorMessage = (error: unknown) => error instanceof ApiError ? error.message : "Request failed";

export function LlmRoutingAdmin() {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [provider, setProvider] = useState({
    name: "",
    display_name: "",
    kind: "openai_compatible",
    base_url: "https://",
    api_key: "",
  });
  const [model, setModel] = useState({ provider_id: "", model_id: "", display_name: "", priority: 100, weight: 100 });
  const [providerKeys, setProviderKeys] = useState<Record<string, string>>({});

  const config = useQuery({
    queryKey: ["admin", "llm"],
    queryFn: () => api.get<LlmConfiguration>("/admin/llm"),
  });
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["admin", "llm"] });

  const createProvider = useMutation({
    mutationFn: () => api.post("/admin/llm/providers", provider),
    onSuccess: () => {
      toast.push("Provider stored with encrypted credentials", "success");
      setProvider({ name: "", display_name: "", kind: "openai_compatible", base_url: "https://", api_key: "" });
      void refresh();
    },
    onError: (error) => toast.push(errorMessage(error), "error"),
  });
  const createModel = useMutation({
    mutationFn: () => api.post("/admin/llm/models", { ...model, display_name: model.display_name || model.model_id }),
    onSuccess: () => {
      toast.push("Model added to the active routing pool", "success");
      setModel((current) => ({ ...current, model_id: "", display_name: "" }));
      void refresh();
    },
    onError: (error) => toast.push(errorMessage(error), "error"),
  });
  const updateProvider = useMutation({
    mutationFn: ({ id, values }: { id: string; values: Record<string, unknown> }) => api.patch(`/admin/llm/providers/${id}`, values),
    onSuccess: (_, request) => {
      setProviderKeys((current) => ({ ...current, [request.id]: "" }));
      toast.push("Provider updated", "success");
      void refresh();
    },
    onError: (error) => toast.push(errorMessage(error), "error"),
  });
  const updateModel = useMutation({
    mutationFn: ({ id, values }: { id: string; values: Partial<LlmModel> }) => api.patch(`/admin/llm/models/${id}`, values),
    onSuccess: () => void refresh(),
    onError: (error) => toast.push(errorMessage(error), "error"),
  });
  const testModel = useMutation({
    mutationFn: (id: string) => api.post<{ ok: boolean; provider: string; model: string; error: string }>(`/admin/llm/models/${id}/test`),
    onSuccess: (result) => {
      toast.push(result.ok ? `${result.provider}/${result.model} is healthy` : result.error || "Model test failed", result.ok ? "success" : "error");
      void refresh();
    },
    onError: (error) => toast.push(errorMessage(error), "error"),
  });
  const deleteModel = useMutation({
    mutationFn: (id: string) => api.del(`/admin/llm/models/${id}`),
    onSuccess: () => { toast.push("Model removed", "success"); void refresh(); },
    onError: (error) => toast.push(errorMessage(error), "error"),
  });
  const deleteProvider = useMutation({
    mutationFn: (id: string) => api.del(`/admin/llm/providers/${id}`),
    onSuccess: () => { toast.push("Provider removed", "success"); void refresh(); },
    onError: (error) => toast.push(errorMessage(error), "error"),
  });

  if (config.isLoading) return <LoadingBlock />;
  if (!config.data) return <EmptyState title="Model routing unavailable" description={config.error?.message} />;

  const routing = config.data.routing;
  return (
    <div className="space-y-5">
      <div className="grid gap-3 sm:grid-cols-3">
        <Card className="p-4"><p className="text-caption text-fgmuted">Routing</p><p className="mt-1 text-h3 capitalize">{routing.routing}</p></Card>
        <Card className="p-4"><p className="text-caption text-fgmuted">Healthy routes</p><p className="mt-1 text-h3">{routing.healthy_models} / {routing.enabled_models}</p></Card>
        <Card className="p-4"><p className="text-caption text-fgmuted">Preferred route</p><p className="mt-1 truncate font-mono text-caption text-accent">{routing.provider}/{routing.model}</p></Card>
      </div>

      <Card>
        <CardHeader title="Add provider" description="OpenAI-compatible endpoints cover Groq, Together, Fireworks, OpenRouter and self-hosted compatible APIs. Private-network URLs are rejected." />
        <form className="grid gap-4 p-5 md:grid-cols-2" onSubmit={(event) => { event.preventDefault(); createProvider.mutate(); }}>
          <div><Label htmlFor="provider-name">Stable slug</Label><Input id="provider-name" placeholder="groq-secondary" required value={provider.name} onChange={(event) => setProvider({ ...provider, name: event.target.value.toLowerCase() })} /></div>
          <div><Label htmlFor="provider-label">Display name</Label><Input id="provider-label" placeholder="Groq secondary" required value={provider.display_name} onChange={(event) => setProvider({ ...provider, display_name: event.target.value })} /></div>
          <div><Label htmlFor="provider-kind">Protocol</Label><select id="provider-kind" className="min-h-touch w-full rounded-md border border-edge bg-bg px-3 text-body" value={provider.kind} onChange={(event) => setProvider({ ...provider, kind: event.target.value })}><option value="openai_compatible">OpenAI compatible</option><option value="anthropic">Anthropic Messages</option></select></div>
          <div><Label htmlFor="provider-url">HTTPS base URL</Label><Input id="provider-url" type="url" required value={provider.base_url} onChange={(event) => setProvider({ ...provider, base_url: event.target.value })} /></div>
          <div className="md:col-span-2"><Label htmlFor="provider-key">API key</Label><Input id="provider-key" type="password" autoComplete="off" required value={provider.api_key} onChange={(event) => setProvider({ ...provider, api_key: event.target.value })} /></div>
          <div className="md:col-span-2"><Button type="submit" loading={createProvider.isPending}>Encrypt and add provider</Button></div>
        </form>
      </Card>

      <Card>
        <CardHeader title="Add model" description="Models sharing a priority are load-balanced by weight. Higher numeric priority tiers are failover routes." />
        <form className="grid gap-4 p-5 md:grid-cols-2" onSubmit={(event) => { event.preventDefault(); createModel.mutate(); }}>
          <div><Label htmlFor="model-provider">Provider</Label><select id="model-provider" required className="min-h-touch w-full rounded-md border border-edge bg-bg px-3 text-body" value={model.provider_id} onChange={(event) => setModel({ ...model, provider_id: event.target.value })}><option value="">Select provider</option>{config.data.providers.map((item) => <option key={item.id} value={item.id}>{item.display_name}</option>)}</select></div>
          <div><Label htmlFor="model-id">Provider model ID</Label><Input id="model-id" placeholder="llama-3.3-70b-versatile" required value={model.model_id} onChange={(event) => setModel({ ...model, model_id: event.target.value })} /></div>
          <div><Label htmlFor="model-priority">Priority</Label><Input id="model-priority" type="number" min={1} max={1000} value={model.priority} onChange={(event) => setModel({ ...model, priority: Number(event.target.value) })} /></div>
          <div><Label htmlFor="model-weight">Weight</Label><Input id="model-weight" type="number" min={1} max={1000} value={model.weight} onChange={(event) => setModel({ ...model, weight: Number(event.target.value) })} /></div>
          <div className="md:col-span-2"><Button type="submit" loading={createModel.isPending}>Add active model</Button></div>
        </form>
      </Card>

      <div className="space-y-4">
        {config.data.providers.length === 0 && <EmptyState title="No live providers" description="Set GROQ_API_KEY in Render or add an HTTPS provider above. The labelled offline planner remains available." />}
        {config.data.providers.map((item) => (
          <Card key={item.id}>
            <div className="flex flex-wrap items-center gap-3 border-b border-edge p-4">
              <StatusDot tone={item.status === "healthy" ? "success" : item.status === "degraded" ? "danger" : "idle"} label={item.display_name} />
              <Badge>{item.kind}</Badge><Badge>{item.source}</Badge><code className="text-caption text-fgmuted">{item.api_key_hint}</code>
              <span className="ml-auto w-44"><Switch checked={item.enabled} onChange={(enabled) => updateProvider.mutate({ id: item.id, values: { enabled } })} label={item.enabled ? "Active" : "Disabled"} /></span>
              <p className="w-full break-all text-caption text-fgmuted">{item.base_url}</p>
              {item.last_error && <p className="w-full text-caption text-danger">{item.last_error}</p>}
              <form
                className="flex w-full flex-wrap items-end gap-2"
                onSubmit={(event) => {
                  event.preventDefault();
                  const apiKey = providerKeys[item.id] || "";
                  if (apiKey) updateProvider.mutate({ id: item.id, values: { api_key: apiKey } });
                }}
              >
                <div className="min-w-60 flex-1"><Label htmlFor={`rotate-${item.id}`}>Rotate API key</Label><Input id={`rotate-${item.id}`} type="password" autoComplete="off" placeholder="New key is encrypted on save" value={providerKeys[item.id] || ""} onChange={(event) => setProviderKeys((current) => ({ ...current, [item.id]: event.target.value }))} /></div>
                <Button type="submit" size="sm" variant="secondary" disabled={!providerKeys[item.id]} loading={updateProvider.isPending}>Save new key</Button>
                {item.source === "admin" && <Button type="button" size="sm" variant="danger" loading={deleteProvider.isPending && deleteProvider.variables === item.id} onClick={() => { if (window.confirm(`Delete ${item.display_name} and all of its model routes?`)) deleteProvider.mutate(item.id); }}>Delete provider</Button>}
              </form>
            </div>
            <div className="divide-y divide-edge">
              {item.models.map((route) => (
                <div key={route.id} className="grid gap-3 p-4 lg:grid-cols-[minmax(0,1fr)_100px_100px_150px_190px] lg:items-center">
                  <div className="min-w-0"><p className="truncate font-mono text-caption text-accent">{route.model_id}</p><p className="text-caption text-fgmuted">{route.status} · failures {route.consecutive_failures}{route.circuit_open_until ? " · circuit cooling down" : ""}</p>{route.last_error && <p className="mt-1 truncate text-caption text-danger">{route.last_error}</p>}</div>
                  <div><Label htmlFor={`priority-${route.id}`}>Priority</Label><Input key={`${route.id}-priority-${route.priority}`} id={`priority-${route.id}`} type="number" defaultValue={route.priority} onBlur={(event) => { const value = Number(event.target.value); if (value !== route.priority) updateModel.mutate({ id: route.id, values: { priority: value } }); }} /></div>
                  <div><Label htmlFor={`weight-${route.id}`}>Weight</Label><Input key={`${route.id}-weight-${route.weight}`} id={`weight-${route.id}`} type="number" defaultValue={route.weight} onBlur={(event) => { const value = Number(event.target.value); if (value !== route.weight) updateModel.mutate({ id: route.id, values: { weight: value } }); }} /></div>
                  <Switch checked={route.enabled} onChange={(enabled) => updateModel.mutate({ id: route.id, values: { enabled } })} label={route.enabled ? "Routable" : "Disabled"} />
                  <div className="flex gap-2"><Button size="sm" variant="secondary" loading={testModel.isPending && testModel.variables === route.id} onClick={() => testModel.mutate(route.id)}>Test</Button><Button size="sm" variant="danger" loading={deleteModel.isPending && deleteModel.variables === route.id} onClick={() => { if (window.confirm(`Remove model route ${route.model_id}?`)) deleteModel.mutate(route.id); }}>Remove</Button></div>
                </div>
              ))}
              {item.models.length === 0 && <p className="p-4 text-caption text-fgmuted">No model IDs configured for this provider.</p>}
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
}
