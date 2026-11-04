"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, describeError } from "@/lib/api/client";
import { Badge, Button, Card, CardHeader, EmptyState, ErrorState, Input, Label, PageHeader, Textarea } from "@/components/ui/primitives";
import { Switch } from "@/components/ui/switch";
import { useToast } from "@/components/ui/toast";

interface MemoryItem {
  id: string;
  category: string;
  content: string;
  source: string;
  importance: number;
  keywords: string[];
  use_count: number;
  last_used_at: string | null;
  active: boolean;
  pinned: boolean;
  created_at: string;
  updated_at: string;
  score?: number;
}

interface MemoryList {
  items: MemoryItem[];
  categories: string[];
}

interface SearchResult {
  query: string;
  items: MemoryItem[];
}

export default function MemoryPage() {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [includeInactive, setIncludeInactive] = useState(false);
  const [form, setForm] = useState({ content: "", category: "explicit_instruction", importance: 3, pinned: false });
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState<SearchResult | null>(null);
  const list = useQuery({
    queryKey: ["memory", includeInactive],
    queryFn: () => api.get<MemoryList>(`/memory?include_inactive=${includeInactive}`),
  });
  const invalidate = () => void queryClient.invalidateQueries({ queryKey: ["memory"] });

  const create = useMutation({
    mutationFn: () => api.post<MemoryItem & { created: boolean }>("/memory", form),
    onSuccess: (item) => {
      setForm({ content: "", category: "explicit_instruction", importance: 3, pinned: false });
      toast.push(item.created ? "Memory saved." : "Similar memory deduplicated and reused.", "success");
      invalidate();
    },
    onError: (err) => toast.push(describeError(err, "save this memory"), "error"),
  });

  const patch = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Record<string, unknown> }) => api.patch(`/memory/${id}`, body),
    onSuccess: invalidate,
    onError: (err) => toast.push(describeError(err, "update this memory"), "error"),
  });

  const remove = useMutation({
    mutationFn: (id: string) => api.del(`/memory/${id}`),
    onSuccess: invalidate,
    onError: (err) => toast.push(describeError(err, "delete this memory"), "error"),
  });

  const searchMemory = useMutation({
    mutationFn: () => api.post<SearchResult>("/memory/search", { query, limit: 10 }),
    onSuccess: setSearch,
    onError: (err) => toast.push(describeError(err, "search memory"), "error"),
  });

  const items = search?.items || list.data?.items || [];
  const categories = list.data?.categories || ["explicit_instruction", "knowledge_summary", "preference", "fact", "correction"];

  return (
    <div className="space-y-5 pb-10">
      <PageHeader title="Memory" description="Ranked, deduplicated, database-backed memory. Chat history is separate; explicit save/capture controls are user-driven." />
      <div className="grid gap-5 lg:grid-cols-2">
        <Card>
          <CardHeader title="Save an explicit memory" description="Only content you intentionally save becomes long-term memory." />
          <div className="space-y-3 p-4">
            <div>
              <Label htmlFor="memory-content">Content</Label>
              <Textarea id="memory-content" rows={4} value={form.content} onChange={(e) => setForm({ ...form, content: e.target.value })} placeholder="Always prefer concise, source-backed explanations." />
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <div>
                <Label htmlFor="memory-category">Category</Label>
                <select id="memory-category" value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} className="h-10 w-full rounded-md border border-edge bg-bg px-3 text-caption text-fg">
                  {categories.map((category) => <option key={category} value={category}>{category}</option>)}
                </select>
              </div>
              <div>
                <Label htmlFor="memory-importance">Importance · {form.importance}/5</Label>
                <input id="memory-importance" type="range" min={1} max={5} value={form.importance} onChange={(e) => setForm({ ...form, importance: Number(e.target.value) })} className="w-full accent-accent" />
              </div>
            </div>
            <Switch label="Pin to top" checked={form.pinned} onChange={(pinned) => setForm({ ...form, pinned })} />
            <Button onClick={() => create.mutate()} loading={create.isPending} disabled={form.content.trim().length < 8}>Save memory</Button>
          </div>
        </Card>
        <Card>
          <CardHeader title="Ranked search" description="Keyword overlap plus importance; retrieval increments use count." />
          <div className="space-y-3 p-4">
            <div className="flex gap-2">
              <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="What do you remember about…" />
              <Button variant="secondary" onClick={() => searchMemory.mutate()} loading={searchMemory.isPending} disabled={query.trim().length < 1}>Search</Button>
              <Button variant="ghost" onClick={() => setSearch(null)} disabled={!search}>Clear</Button>
            </div>
            {search && <p className="text-caption text-fgmuted">{search.items.length} ranked result(s) for “{search.query}”</p>}
            {search?.items.slice(0, 5).map((item) => (
              <div key={item.id} className="rounded-md border border-edge bg-bg/40 p-2.5 text-caption">
                <div className="flex items-center gap-2"><Badge tone="accent">score {item.score}</Badge><span className="font-mono text-fgmuted">{item.category}</span></div>
                <p className="mt-1 text-fg">{item.content.slice(0, 180)}</p>
              </div>
            ))}
          </div>
        </Card>
      </div>

      <Card>
        <div className="flex flex-wrap items-center gap-3 p-4">
          <h2 className="text-body font-semibold text-fg">Stored memories ({items.length})</h2>
          <Button size="sm" variant={includeInactive ? "primary" : "ghost"} onClick={() => setIncludeInactive((v) => !v)}>{includeInactive ? "Showing inactive" : "Show inactive"}</Button>
        </div>
      </Card>
      {list.isError && <Card><div className="p-6"><ErrorState message={list.error.message} onRetry={() => void list.refetch()} /></div></Card>}
      {items.length === 0 && list.data && <EmptyState title="No memories" description="Save an explicit instruction or capture a chat message from the Assistant." />}
      <div className="space-y-3">
        {items.map((item) => (
          <Card key={item.id}>
            <div className="flex flex-wrap items-start gap-4 p-4">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone="accent">{item.category}</Badge>
                  <Badge tone="neutral">{item.source}</Badge>
                  {item.pinned && <Badge tone="warning">pinned</Badge>}
                  {!item.active && <Badge tone="danger">inactive</Badge>}
                  <span className="text-caption text-fgmuted">importance {item.importance}/5 · used {item.use_count}×</span>
                </div>
                <p className="mt-2 whitespace-pre-wrap text-body text-fg">{item.content}</p>
                <p className="mt-1 text-caption text-fgmuted">keywords: {item.keywords.slice(0, 8).join(", ") || "none"} · updated {new Date(item.updated_at).toLocaleString()}</p>
              </div>
              <div className="w-full space-y-2 sm:w-48">
                <Switch label="Active" checked={item.active} onChange={(active) => patch.mutate({ id: item.id, body: { active } })} />
                <Switch label="Pinned" checked={item.pinned} onChange={(pinned) => patch.mutate({ id: item.id, body: { pinned } })} />
                <Button size="sm" variant="danger" onClick={() => window.confirm("Delete this memory?") && remove.mutate(item.id)}>Delete</Button>
              </div>
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
}
