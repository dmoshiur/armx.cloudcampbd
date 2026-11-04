"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { api, describeError } from "@/lib/api/client";
import type { Conversation } from "@/lib/types";
import { Badge, Button, Card, CardHeader, EmptyState, ErrorState, Input, PageHeader } from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";

interface ConversationList {
  items: Conversation[];
  total: number;
  has_more: boolean;
}

export default function ConversationsPage() {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [includeArchived, setIncludeArchived] = useState(false);
  const [pinnedOnly, setPinnedOnly] = useState(false);
  const [offset, setOffset] = useState(0);
  const [newTitle, setNewTitle] = useState("");
  const [renaming, setRenaming] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const limit = 30;

  const query = `/assistant/conversations?limit=${limit}&offset=${offset}&include_archived=${includeArchived}&pinned_only=${pinnedOnly}&q=${encodeURIComponent(search)}`;
  const list = useQuery({ queryKey: ["conversations", query], queryFn: () => api.get<ConversationList>(query) });
  const invalidate = () => void queryClient.invalidateQueries({ queryKey: ["conversations"] });

  const create = useMutation({
    mutationFn: () => api.post<Conversation>("/assistant/conversations", { title: newTitle || "New chat" }),
    onSuccess: (convo) => {
      setNewTitle("");
      toast.push("Conversation created.", "success");
      invalidate();
      window.location.href = `/?c=${convo.id}`;
    },
    onError: (err) => toast.push(describeError(err, "create a conversation"), "error"),
  });

  const patch = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Record<string, unknown> }) => api.patch(`/assistant/conversations/${id}`, body),
    onSuccess: () => {
      setRenaming(null);
      invalidate();
    },
    onError: (err) => toast.push(describeError(err, "update this conversation"), "error"),
  });

  const remove = useMutation({
    mutationFn: (id: string) => api.del(`/assistant/conversations/${id}`),
    onSuccess: () => {
      toast.push("Conversation deleted.", "success");
      invalidate();
    },
    onError: (err) => toast.push(describeError(err, "delete this conversation"), "error"),
  });

  const exportConversation = async (id: string) => {
    try {
      const blob = await api.blob(`/assistant/conversations/${id}/export?format=markdown`);
      if (!blob) return;
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `armx-${id.slice(0, 8)}.md`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      toast.push(describeError(err, "export this conversation"), "error");
    }
  };

  return (
    <div className="space-y-5 pb-10">
      <PageHeader title="Conversations" description="Durable, database-backed history with search, pin, archive, restore, export and pagination." />
      <Card>
        <CardHeader title="Create & filter" description="The Assistant restores any selected conversation after refresh, login or deployment." />
        <div className="grid gap-3 p-4 md:grid-cols-[1fr_180px_auto_auto]">
          <Input value={newTitle} onChange={(e) => setNewTitle(e.target.value)} placeholder="New conversation title" />
          <Input value={search} onChange={(e) => { setSearch(e.target.value); setOffset(0); }} placeholder="Search titles & summaries" />
          <Button variant="secondary" onClick={() => create.mutate()} loading={create.isPending}>New conversation</Button>
          <div className="flex gap-2">
            <Button size="sm" variant={includeArchived ? "primary" : "ghost"} onClick={() => { setIncludeArchived((v) => !v); setOffset(0); }}>Archived</Button>
            <Button size="sm" variant={pinnedOnly ? "primary" : "ghost"} onClick={() => { setPinnedOnly((v) => !v); setOffset(0); }}>Pinned</Button>
          </div>
        </div>
      </Card>

      {list.isLoading && <Card><div className="p-6 text-body text-fgmuted">Loading conversations…</div></Card>}
      {list.isError && <Card><div className="p-6"><ErrorState message={list.error.message} onRetry={() => void list.refetch()} /></div></Card>}
      {list.data?.items.length === 0 && <EmptyState title="No conversations found" description="Adjust the filters or start a new conversation." />}

      <div className="space-y-3">
        {(list.data?.items || []).map((convo) => (
          <Card key={convo.id}>
            <div className="flex flex-wrap items-start gap-3 p-4">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  {renaming === convo.id ? (
                    <Input value={renameValue} onChange={(e) => setRenameValue(e.target.value)} aria-label="New title" />
                  ) : (
                    <h3 className="truncate text-body font-semibold text-fg">{convo.title}</h3>
                  )}
                  {convo.pinned && <Badge tone="warning">pinned</Badge>}
                  {convo.archived && <Badge tone="neutral">archived</Badge>}
                  <Badge tone="accent">{convo.message_count} messages</Badge>
                </div>
                <p className="mt-1 truncate text-caption text-fgmuted">{convo.summary || "No context summary yet."}</p>
                <p className="mt-1 text-caption text-fgmuted">
                  updated {new Date(convo.updated_at).toLocaleString()} · model {convo.model || "auto"} · {convo.token_usage} tokens
                </p>
              </div>
              <div className="flex flex-wrap gap-1.5">
                <Link href={`/?c=${convo.id}`} className="inline-flex min-h-touch items-center rounded-md border border-accent/40 bg-accent/10 px-3 text-caption font-semibold text-accent hover:bg-accent/20">Continue</Link>
                {renaming === convo.id ? (
                  <Button size="sm" variant="secondary" onClick={() => patch.mutate({ id: convo.id, body: { title: renameValue || convo.title } })}>Save</Button>
                ) : (
                  <Button size="sm" variant="ghost" onClick={() => { setRenaming(convo.id); setRenameValue(convo.title); }}>Rename</Button>
                )}
                <Button size="sm" variant="ghost" onClick={() => patch.mutate({ id: convo.id, body: { pinned: !convo.pinned } })}>{convo.pinned ? "Unpin" : "Pin"}</Button>
                <Button size="sm" variant="ghost" onClick={() => patch.mutate({ id: convo.id, body: { archived: !convo.archived } })}>{convo.archived ? "Restore" : "Archive"}</Button>
                <Button size="sm" variant="ghost" onClick={() => void exportConversation(convo.id)}>Export</Button>
                <Button size="sm" variant="danger" onClick={() => window.confirm("Delete this conversation permanently?") && remove.mutate(convo.id)}>Delete</Button>
              </div>
            </div>
          </Card>
        ))}
      </div>

      {list.data?.has_more && (
        <Button variant="secondary" onClick={() => setOffset((value) => value + limit)}>Load more ({list.data.total} total)</Button>
      )}
    </div>
  );
}
