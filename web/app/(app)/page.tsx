"use client";

import clsx from "clsx";
import { useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, describeError } from "@/lib/api/client";
import { usePreferences } from "@/lib/preferences";
import type {
  Approval,
  ChatMessage,
  ChatResponse,
  Conversation,
  ConversationDetail,
  StreamEvent,
  ToolEvent,
  UploadResult,
} from "@/lib/types";
import { Badge, Button, Spinner } from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { Markdown } from "@/components/chat/markdown";
import { Composer } from "@/components/chat/composer";
import { ApprovalCard } from "@/components/chat/approval-card";

interface ModelOption {
  id: string;
  display_name: string;
  provider: string;
  provider_display_name: string;
  status: string;
  last_error: string;
  supports_tools: boolean;
  max_tokens: number;
}

interface ErrorState {
  message: string;
  code: string;
  requestId?: string;
  hint?: string;
  canRetry: boolean;
}

interface RunSummary {
  runId: string;
  events: ToolEvent[];
  status: string;
  provider: string;
  model: string;
  fallbackReason: string;
  steps: number;
}

interface ChatPayload {
  message: string;
  conversation_id: string | null;
  model?: string;
  attachments: string[];
}

const CATEGORIES = [
  ["user_preference", "User preference"],
  ["project_context", "Project context"],
  ["important_decision", "Important decision"],
  ["technical_environment", "Technical environment"],
  ["frequently_used_tool", "Frequent tool"],
  ["explicit_instruction", "Explicit instruction"],
  ["knowledge_summary", "Knowledge summary"],
] as const;

function toError(err: unknown): ErrorState | null {
  if (err instanceof DOMException && err.name === "AbortError") return null;
  if (err instanceof ApiError) {
    return {
      message: err.message,
      code: err.code,
      requestId: err.requestId,
      hint: err.hint,
      canRetry: err.retryable || err.canRetry,
    };
  }
  return {
    message: describeError(err, "send a message"),
    code: "client_error",
    canRetry: true,
  };
}

function eventToError(event: StreamEvent): ErrorState {
  return {
    message: event.error || "The assistant stream failed without a structured reason.",
    code: event.code || "assistant_unavailable",
    requestId: event.request_id,
    hint: event.hint,
    canRetry: Boolean(event.retryable || event.can_retry || event.code?.includes("timeout") || event.code?.includes("unavailable")),
  };
}

function timeLabel(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function AssistantWorkspace() {
  const { settings } = usePreferences();
  const params = useSearchParams();
  const toast = useToast();
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState<string | null>(() => {
    if (typeof window === "undefined") return null;
    return localStorage.getItem("armx.activeConversation");
  });
  const activeIdRef = useRef<string | null>(activeId);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loadingConversation, setLoadingConversation] = useState(false);
  const [draft, setDraft] = useState("");
  const [attachments, setAttachments] = useState<UploadResult[]>([]);
  const [busy, setBusy] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [runId, setRunId] = useState<string | null>(null);
  const runIdRef = useRef<string | null>(null);
  const [stage, setStage] = useState("");
  const [approval, setApproval] = useState<Approval | null>(null);
  const [pendingApprovals, setPendingApprovals] = useState<Approval[]>([]);
  const [error, setError] = useState<ErrorState | null>(null);
  const [lastRun, setLastRun] = useState<RunSummary | null>(null);
  const [models, setModels] = useState<ModelOption[]>([]);
  const [model, setModel] = useState("");
  const modelTouched = useRef(false);
  const [actualRoute, setActualRoute] = useState("");
  const [query, setQuery] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const [editValue, setEditValue] = useState("");
  const [feedback, setFeedback] = useState<Record<string, "up" | "down">>({});
  const [speakingId, setSpeakingId] = useState<string | null>(null);
  const [memoryFor, setMemoryFor] = useState<string | null>(null);
  const [memoryCategory, setMemoryCategory] = useState<string>("knowledge_summary");
  const [renaming, setRenaming] = useState(false);
  const [titleDraft, setTitleDraft] = useState("");
  const [showJump, setShowJump] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const autoScrollRef = useRef(true);
  const lastPayloadRef = useRef<ChatPayload | null>(null);

  useEffect(() => {
    activeIdRef.current = activeId;
    if (activeId) localStorage.setItem("armx.activeConversation", activeId);
    else localStorage.removeItem("armx.activeConversation");
  }, [activeId]);

  useEffect(() => {
    if (!modelTouched.current && settings.default_model) setModel(settings.default_model);
  }, [settings.default_model]);

  const loadConversations = useCallback(async () => {
    try {
      const data = await api.get<{ items: Conversation[] }>("/assistant/conversations?limit=50");
      setConversations(data.items);
    } catch (err) {
      toast.push(describeError(err, "load conversations"), "error");
    }
  }, [toast]);

  const loadConversation = useCallback(
    async (id: string) => {
      setLoadingConversation(true);
      try {
        const detail = await api.get<ConversationDetail>(`/assistant/conversations/${id}?limit=500`);
        setMessages(detail.messages);
        setTitleDraft(detail.title);
        setActualRoute(detail.model || "");
      } catch (err) {
        toast.push(describeError(err, "load this conversation"), "error");
      } finally {
        setLoadingConversation(false);
      }
    },
    [toast],
  );

  const refreshApprovals = useCallback(
    async (preferredId?: string, select = false) => {
      try {
        const items = await api.get<Approval[]>("/assistant/approvals");
        setPendingApprovals(items);
        if (select) {
          const chosen = items.find((item) => item.id === preferredId) || items[0] || null;
          setApproval(chosen);
        }
      } catch {
        // A failed approval poll must not hide the rest of the conversation.
      }
    },
    [],
  );

  useEffect(() => {
    void loadConversations();
    void refreshApprovals();
    void api
      .get<{ items: ModelOption[] }>("/models")
      .then((data) => setModels(data.items))
      .catch(() => undefined);
    if (activeId) void loadConversation(activeId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (autoScrollRef.current && scrollRef.current) {
      requestAnimationFrame(() => {
        const el = scrollRef.current;
        if (el) el.scrollTo({ top: el.scrollHeight, behavior: streaming ? "auto" : "smooth" });
      });
    }
  }, [messages, streaming, query]);

  useEffect(() => () => {
    abortRef.current?.abort();
    if (typeof window !== "undefined") window.speechSynthesis?.cancel();
  }, []);

  const setCurrentRun = (value: string | null) => {
    setRunId(value);
    runIdRef.current = value;
  };

  const applyOutcome = useCallback(
    (outcome: ChatResponse) => {
      const conversationId = outcome.conversation_id || activeIdRef.current;
      if (conversationId && conversationId !== activeIdRef.current) setActiveId(conversationId);
      if (outcome.run_id) setCurrentRun(outcome.run_id);
      const route = [outcome.provider, outcome.model].filter(Boolean).join("/");
      if (route) setActualRoute(route);
      setLastRun({
        runId: outcome.run_id || runIdRef.current || "",
        events: outcome.tool_events || [],
        status: outcome.status,
        provider: outcome.provider || "",
        model: outcome.model || "",
        fallbackReason: outcome.fallback_reason || "",
        steps: outcome.steps || 0,
      });
      if (outcome.fallback_reason) {
        toast.push(`Route changed to ${route || "offline planner"}: ${outcome.fallback_reason}`, "info");
      }
      if (outcome.approval) {
        const merged: Approval = { ...outcome.approval, run_id: outcome.approval.run_id || outcome.run_id };
        setApproval(merged);
        void refreshApprovals();
      } else if (outcome.status !== "awaiting_approval") {
        setApproval(null);
      }
      if (outcome.status === "error") {
        setError({
          message: outcome.error || "The assistant could not complete this request.",
          code: outcome.error_code || "assistant_error",
          requestId: outcome.request_id,
          hint: outcome.hint || undefined,
          canRetry: true,
        });
      }
      if (outcome.status === "awaiting_approval" && outcome.reply) {
        const placeholderId = `pending-${outcome.run_id}`;
        setMessages((prev) =>
          prev.some((m) => m.id === placeholderId)
            ? prev
            : [
                ...prev,
                {
                  id: placeholderId,
                  role: "assistant",
                  content: outcome.reply,
                  created_at: new Date().toISOString(),
                  model: outcome.model,
                  provider: outcome.provider,
                  status: "awaiting_approval",
                },
              ],
        );
      }
      if (conversationId) {
        void loadConversation(conversationId);
      }
      void loadConversations();
    },
    [loadConversation, loadConversations, refreshApprovals, toast],
  );

  const send = useCallback(
    async (payload: ChatPayload, useStreaming: boolean) => {
      if (busy) return;
      lastPayloadRef.current = payload;
      setError(null);
      setApproval(null);
      setStage("Starting…");
      setLastRun(null);
      setBusy(true);
      setStreaming(useStreaming);
      const localId = `local-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
      setMessages((prev) => [
        ...prev,
        { id: localId, role: "user", content: payload.message, created_at: new Date().toISOString() },
      ]);
      setDraft("");
      setAttachments([]);
      setQuery("");
      autoScrollRef.current = true;

      if (!useStreaming) {
        try {
          const outcome = await api.post<ChatResponse>("/assistant/chat", payload);
          applyOutcome(outcome);
        } catch (err) {
          const parsed = toError(err);
          if (parsed) setError(parsed);
        } finally {
          setBusy(false);
          setStreaming(false);
          setStage("");
        }
        return;
      }

      const controller = new AbortController();
      abortRef.current = controller;
      try {
        for await (const event of api.stream<StreamEvent>("/assistant/chat/stream", payload, controller.signal)) {
          if (event.type === "open") {
            if (event.conversation_id) {
              setActiveId(event.conversation_id);
              if (lastPayloadRef.current) lastPayloadRef.current.conversation_id = event.conversation_id;
            }
          } else if (event.type === "start") {
            if (event.run_id) setCurrentRun(event.run_id);
            const placeholderId = `stream-${event.run_id || "live"}`;
            setMessages((prev) =>
              prev.some((m) => m.id === placeholderId)
                ? prev
                : [
                    ...prev,
                    {
                      id: placeholderId,
                      role: "assistant",
                      content: "",
                      created_at: new Date().toISOString(),
                      model: event.model,
                      provider: event.provider,
                      status: "streaming",
                    },
                  ],
            );
          } else if (event.type === "status") {
            setStage(`${event.stage || "working"}${event.step ? ` · step ${event.step}` : ""}`);
            if (event.model) setActualRoute([event.provider, event.model].filter(Boolean).join("/"));
          } else if (event.type === "delta") {
            const placeholderId = `stream-${runIdRef.current || "live"}`;
            setMessages((prev) => {
              const index = prev.findIndex((m) => m.id === placeholderId);
              if (index === -1) {
                return [
                  ...prev,
                  {
                    id: placeholderId,
                    role: "assistant",
                    content: event.text || "",
                    created_at: new Date().toISOString(),
                    status: "streaming",
                  },
                ];
              }
              return prev.map((m, i) => (i === index ? { ...m, content: m.content + (event.text || "") } : m));
            });
          } else if (event.type === "tool" && event.event) {
            setLastRun((prev) => ({
              runId: prev?.runId || runIdRef.current || "",
              events: [...(prev?.events || []), event.event!],
              status: prev?.status || "running",
              provider: prev?.provider || "",
              model: prev?.model || "",
              fallbackReason: prev?.fallbackReason || "",
              steps: prev?.steps || 0,
            }));
          } else if (event.type === "approval" && event.approval) {
            setApproval({ ...event.approval, run_id: event.approval.run_id || runIdRef.current || undefined });
            void refreshApprovals();
          } else if (event.type === "result" && event.outcome) {
            applyOutcome(event.outcome);
          } else if (event.type === "error") {
            setError(eventToError(event));
          } else if (event.type === "stopped") {
            setStage("Stopped");
          }
        }
      } catch (err) {
        const parsed = toError(err);
        if (parsed) setError(parsed);
      } finally {
        abortRef.current = null;
        setBusy(false);
        setStreaming(false);
        setStage("");
        if (activeIdRef.current) void loadConversation(activeIdRef.current);
        void refreshApprovals();
      }
    },
    [applyOutcome, busy, loadConversation, refreshApprovals],
  );

  const onSend = () => {
    const text = draft.trim() || (attachments.length ? "Please review the attached file." : "");
    if (!text) return;
    void send(
      {
        message: text,
        conversation_id: activeIdRef.current,
        model: model || undefined,
        attachments: attachments.map((asset) => asset.asset_id),
      },
      settings.streaming,
    );
  };

  const onStop = async () => {
    const current = runIdRef.current;
    if (current) {
      try {
        const result = await api.post<{ stopped: boolean; detail: string }>(`/assistant/runs/${current}/stop`, {});
        toast.push(result.detail, result.stopped ? "info" : "info");
      } catch (err) {
        toast.push(describeError(err, "stop generation"), "error");
      }
    }
    abortRef.current?.abort();
    setStage("Stopped");
  };

  const decideApproval = async (approvalId: string, decision: "approve" | "reject") => {
    const current = approval?.run_id || runIdRef.current || pendingApprovals.find((a) => a.id === approvalId)?.run_id;
    if (!current) {
      toast.push("No run is attached to this approval. Ask again to create a fresh approval.", "error");
      return;
    }
    setBusy(true);
    try {
      const outcome = await api.post<ChatResponse>(`/assistant/runs/${current}/approve`, {
        approval_id: approvalId,
        decision,
      });
      setError(null);
      setApproval(null);
      applyOutcome(outcome);
      toast.push(decision === "approve" ? "Approved — the action was executed." : "Rejected — nothing was executed.", "success");
      await refreshApprovals();
    } catch (err) {
      const parsed = toError(err);
      if (parsed) setError(parsed);
      setApproval((prev) => (prev ? { ...prev, status: "expired", seconds_remaining: 0, can_retry: true } : prev));
    } finally {
      setBusy(false);
    }
  };

  const retryApproval = async (targetRunId: string) => {
    setBusy(true);
    try {
      const result = await api.post<{ approval_id: string }>(`/assistant/runs/${targetRunId}/retry`, {});
      setError(null);
      await refreshApprovals(result.approval_id, true);
      toast.push("A new approval was issued. The expired one cannot be reused.", "success");
    } catch (err) {
      const parsed = toError(err);
      if (parsed) setError(parsed);
    } finally {
      setBusy(false);
    }
  };

  const newChat = () => {
    setActiveId(null);
    setMessages([]);
    setApproval(null);
    setError(null);
    setLastRun(null);
    setActualRoute("");
    setDraft("");
    setAttachments([]);
    setQuery("");
    setEditing(null);
    setRenaming(false);
    setCurrentRun(null);
  };

  const switchConversation = (id: string) => {
    if (!id) {
      newChat();
      return;
    }
    setActiveId(id);
    setApproval(null);
    setError(null);
    setLastRun(null);
    void loadConversation(id);
  };

  useEffect(() => {
    const requested = params.get("c");
    if (requested && requested !== activeIdRef.current) switchConversation(requested);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params]);

  const renameConversation = async () => {
    if (!activeId || !titleDraft.trim()) return;
    try {
      await api.patch(`/assistant/conversations/${activeId}`, { title: titleDraft.trim() });
      setRenaming(false);
      await loadConversations();
      toast.push("Conversation renamed.", "success");
    } catch (err) {
      toast.push(describeError(err, "rename this conversation"), "error");
    }
  };

  const deleteConversation = async () => {
    if (!activeId || !window.confirm("Delete this conversation and its messages permanently?")) return;
    try {
      await api.del(`/assistant/conversations/${activeId}`);
      newChat();
      await loadConversations();
      toast.push("Conversation deleted.", "success");
    } catch (err) {
      toast.push(describeError(err, "delete this conversation"), "error");
    }
  };

  const exportConversation = async () => {
    if (!activeId) return;
    try {
      const blob = await api.blob(`/assistant/conversations/${activeId}/export?format=markdown`);
      if (!blob) return;
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `armx-${activeId.slice(0, 8)}.md`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      toast.push(describeError(err, "export this conversation"), "error");
    }
  };

  const regenerate = async () => {
    if (!activeId || busy) return;
    setBusy(true);
    try {
      const outcome = await api.post<ChatResponse>(`/assistant/conversations/${activeId}/regenerate`, { model: model || undefined });
      setError(null);
      applyOutcome(outcome);
    } catch (err) {
      const parsed = toError(err);
      if (parsed) setError(parsed);
    } finally {
      setBusy(false);
    }
  };

  const saveEdit = async (messageId: string) => {
    if (!editValue.trim()) return;
    setBusy(true);
    try {
      const outcome = await api.post<ChatResponse>(`/assistant/messages/${messageId}/edit-and-resend`, {
        content: editValue.trim(),
        model: model || undefined,
      });
      setEditing(null);
      setError(null);
      applyOutcome(outcome);
    } catch (err) {
      const parsed = toError(err);
      if (parsed) setError(parsed);
    } finally {
      setBusy(false);
    }
  };

  const sendFeedback = async (messageId: string, rating: "up" | "down") => {
    try {
      await api.post(`/assistant/messages/${messageId}/feedback`, { rating, comment: "" });
      setFeedback((prev) => ({ ...prev, [messageId]: rating }));
      toast.push("Feedback recorded. Thank you.", "success");
    } catch (err) {
      toast.push(describeError(err, "save feedback"), "error");
    }
  };

  const copyText = async (text: string, label: string) => {
    try {
      await navigator.clipboard.writeText(text);
      toast.push(`${label} copied.`, "success");
    } catch {
      toast.push("Clipboard access was denied by the browser.", "error");
    }
  };

  const readAloud = (message: ChatMessage) => {
    if (!("speechSynthesis" in window)) {
      toast.push("This browser does not support speech output.", "info");
      return;
    }
    if (speakingId === message.id) {
      window.speechSynthesis.cancel();
      setSpeakingId(null);
      return;
    }
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(message.content.slice(0, 4000));
    utterance.rate = 1;
    utterance.onend = () => setSpeakingId(null);
    window.speechSynthesis.speak(utterance);
    setSpeakingId(message.id);
  };

  const saveToMemory = async (messageId: string) => {
    try {
      const result = await api.post<{ created: boolean }>(`/memory/capture/${messageId}`, {
        category: memoryCategory,
        importance: 3,
      });
      setMemoryFor(null);
      toast.push(result.created ? "Saved to long-term memory." : "This memory already existed and was reused.", "success");
    } catch (err) {
      toast.push(describeError(err, "save this to memory"), "error");
    }
  };

  const onScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 90;
    autoScrollRef.current = atBottom;
    setShowJump(!atBottom);
  };

  const visibleMessages = query.trim()
    ? messages.filter((message) => message.content.toLowerCase().includes(query.trim().toLowerCase()))
    : messages;
  const activeConversation = conversations.find((item) => item.id === activeId);
  const title = activeConversation?.title || (messages.length ? titleDraft || "New chat" : "New conversation");
  const isApprovalError = Boolean(error && /approval_(expired|wrong_session)|approval/i.test(error.code));

  return (
    <section className="flex h-full min-h-0 flex-col" aria-label="Assistant">
      {/* Conversation header */}
      <header className="flex flex-none flex-wrap items-center gap-2 border-b border-edge/70 bg-surface/55 px-3 py-2 backdrop-blur-xl sm:px-4">
        <div className="flex min-w-0 items-center gap-2">
          <span className="hidden text-caption font-semibold uppercase tracking-wider text-accent/70 sm:inline">Assistant</span>
          {renaming && activeId ? (
            <input
              value={titleDraft}
              onChange={(event) => setTitleDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") void renameConversation();
                if (event.key === "Escape") setRenaming(false);
              }}
              aria-label="Conversation title"
              className="min-w-0 max-w-[220px] rounded border border-edge bg-bg px-2 py-1 text-caption text-fg"
            />
          ) : (
            <h1 className="max-w-[180px] truncate text-body font-semibold sm:max-w-[280px]" title={title}>{title}</h1>
          )}
          {activeConversation?.pinned && <Badge tone="warning">pinned</Badge>}
          {activeConversation?.archived && <Badge tone="neutral">archived</Badge>}
        </div>

        <select
          aria-label="Open a saved conversation"
          value={activeId || ""}
          onChange={(event) => switchConversation(event.target.value)}
          className="max-w-[180px] rounded-md border border-edge bg-bg px-2 py-1.5 text-caption text-fg sm:max-w-[240px]"
        >
          <option value="">+ New conversation</option>
          {conversations.map((item) => (
            <option key={item.id} value={item.id}>{item.pinned ? "★ " : ""}{item.title}</option>
          ))}
        </select>

        <div className="flex items-center gap-1">
          {renaming ? (
            <Button size="sm" variant="secondary" onClick={() => void renameConversation()}>Save</Button>
          ) : (
            <Button size="sm" variant="ghost" onClick={() => { setTitleDraft(title); setRenaming(Boolean(activeId)); }} disabled={!activeId} title="Rename conversation">Rename</Button>
          )}
          <Button size="sm" variant="ghost" onClick={() => void exportConversation()} disabled={!activeId} title="Export Markdown">Export</Button>
          <Button size="sm" variant="ghost" onClick={() => void deleteConversation()} disabled={!activeId} title="Delete conversation">Delete</Button>
          <Button size="sm" variant="primary" onClick={newChat}>New chat</Button>
        </div>

        <div className="ml-auto flex flex-wrap items-center gap-2">
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search this chat…"
            aria-label="Search messages in this conversation"
            className="w-[130px] rounded-md border border-edge bg-bg px-2 py-1.5 text-caption text-fg sm:w-[180px]"
          />
          <select
            value={model}
            onChange={(event) => { modelTouched.current = true; setModel(event.target.value); }}
            aria-label="Select AI model"
            className="max-w-[190px] rounded-md border border-edge bg-bg px-2 py-1.5 text-caption text-fg"
          >
            <option value="">Auto route</option>
            {models.map((option) => (
              <option key={`${option.provider}-${option.id}`} value={option.id}>
                {option.provider_display_name} / {option.display_name}{option.status !== "healthy" ? ` (${option.status})` : ""}
              </option>
            ))}
          </select>
          <Badge tone={actualRoute ? "accent" : "neutral"} className="hidden font-mono md:inline-flex">
            {actualRoute || (model ? `selected: ${model}` : "auto route")}
          </Badge>
        </div>
      </header>

      {/* Secondary status strip */}
      <div className="flex flex-none flex-wrap items-center gap-2 border-b border-edge/50 bg-surface/30 px-3 py-1.5 text-caption text-fgmuted sm:px-4">
        {busy ? (
          <span className="flex items-center gap-2 text-accent"><Spinner />{streaming ? `Streaming · ${stage || "working"}` : "Working…"}</span>
        ) : (
          <span>{activeConversation ? `${activeConversation.message_count} messages · ${activeConversation.token_usage} tokens` : "Durable conversation · stored in the database"}</span>
        )}
        {activeConversation?.summary && <span className="hidden truncate lg:inline" title={activeConversation.summary}>Context summary: {activeConversation.summary}</span>}
        {query.trim() && <span>Showing {visibleMessages.length} of {messages.length} messages for “{query.trim()}”</span>}
        {pendingApprovals.length > 0 && !approval && (
          <button
            type="button"
            onClick={() => setApproval(pendingApprovals[0])}
            className="ml-auto rounded border border-warning/50 px-2 py-0.5 text-warning hover:bg-warning/10"
          >
            {pendingApprovals.length} pending approval{pendingApprovals.length === 1 ? "" : "s"} — review
          </button>
        )}
        {lastRun?.fallbackReason && <span className="ml-auto text-warning">Fallback: {lastRun.fallbackReason}</span>}
      </div>

      {/* Messages scroll independently from the fixed composer */}
      <div
        ref={scrollRef}
        onScroll={onScroll}
        className="relative min-h-0 flex-1 overflow-y-auto overscroll-contain px-3 pb-24 pt-4 sm:px-5"
        aria-live="polite"
        aria-busy={busy}
      >
        <div className="mx-auto w-full max-w-4xl space-y-5">
          {loadingConversation && <div className="flex items-center gap-2 text-caption text-fgmuted"><Spinner />Loading conversation…</div>}
          {!loadingConversation && messages.length === 0 && (
            <div className="rounded-xl border border-edge/70 bg-surface/50 p-6 text-center">
              <p className="text-h3 font-semibold text-fg">A.R.M.X AI</p>
              <p className="mx-auto mt-2 max-w-lg text-body text-fgmuted">
                Ask about a project, request a tool, or attach a file. Real provider/model and tool results are shown; nothing is simulated as success.
              </p>
              <div className="mt-4 flex flex-wrap justify-center gap-2">
                {[
                  "Summarise this project and remember the key decisions.",
                  "Check provider health and explain any routing problem.",
                  "Generate a responsive landing page and show the files.",
                ].map((suggestion) => (
                  <button
                    key={suggestion}
                    type="button"
                    onClick={() => setDraft(suggestion)}
                    className="rounded-md border border-edge bg-bg/70 px-3 py-2 text-caption text-fgmuted transition hover:border-accent/50 hover:text-accent"
                  >
                    {suggestion}
                  </button>
                ))}
              </div>
            </div>
          )}

          {visibleMessages.map((message) => {
            const isUser = message.role === "user";
            const isStreamingPlaceholder = message.status === "streaming" || message.id.startsWith("stream-");
            return (
              <article
                key={message.id}
                className={clsx("group animate-fade-up flex gap-3", isUser && "flex-row-reverse")}
                data-message-id={message.id}
              >
                <div className={clsx("grid h-8 w-8 shrink-0 place-items-center rounded-md border text-caption font-bold", isUser ? "border-accent/30 bg-accent/10 text-accent" : "border-edge bg-surface2 text-fgmuted")}>
                  {isUser ? "YOU" : "A"}
                </div>
                <div className={clsx("min-w-0 max-w-[min(100%,46rem)] flex-1 rounded-xl border px-4 py-3", isUser ? "border-accent/20 bg-accent/5" : "border-edge/70 bg-surface/65")}>
                  <div className="mb-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-fgmuted">
                    <span className="font-semibold uppercase tracking-wider">{isUser ? "You" : "A.R.M.X"}</span>
                    <time dateTime={message.created_at}>{timeLabel(message.created_at)}</time>
                    {message.model && <span className="font-mono">{message.provider ? `${message.provider}/` : ""}{message.model}</span>}
                    {message.edited_at && <span>edited</span>}
                    {message.status === "stopped" && <Badge tone="warning">stopped</Badge>}
                    {message.status === "awaiting_approval" && <Badge tone="warning">awaiting approval</Badge>}
                    {isStreamingPlaceholder && <span className="flex items-center gap-1 text-accent"><span className="h-1.5 w-1.5 animate-pulse-soft rounded-full bg-accent" />live</span>}
                  </div>

                  {editing === message.id ? (
                    <div className="space-y-2">
                      <textarea
                        value={editValue}
                        onChange={(event) => setEditValue(event.target.value)}
                        rows={3}
                        className="w-full rounded-md border border-edge bg-bg p-2 text-body text-fg"
                      />
                      <div className="flex gap-2">
                        <Button size="sm" variant="primary" onClick={() => void saveEdit(message.id)} disabled={busy}>Save & resend</Button>
                        <Button size="sm" variant="ghost" onClick={() => setEditing(null)}>Cancel</Button>
                      </div>
                    </div>
                  ) : isUser ? (
                    <p className="whitespace-pre-wrap break-words text-body text-fg">{message.content}</p>
                  ) : (
                    <Markdown content={message.content || "…"} />
                  )}

                  {!editing && !isStreamingPlaceholder && (
                    <div className="mt-3 flex flex-wrap items-center gap-1.5 border-t border-edge/50 pt-2 text-[11px]">
                      <button type="button" onClick={() => void copyText(message.content, isUser ? "Message" : "Response")} className="rounded px-2 py-1 text-fgmuted hover:bg-white/5 hover:text-accent">Copy</button>
                      {isUser && (
                        <button type="button" onClick={() => { setEditing(message.id); setEditValue(message.content); }} className="rounded px-2 py-1 text-fgmuted hover:bg-white/5 hover:text-accent">Edit & resend</button>
                      )}
                      {!isUser && (
                        <>
                          <button type="button" onClick={() => void readAloud(message)} className="rounded px-2 py-1 text-fgmuted hover:bg-white/5 hover:text-accent">{speakingId === message.id ? "Stop reading" : "Read aloud"}</button>
                          <button type="button" onClick={() => { setMemoryFor(message.id === memoryFor ? null : message.id); setMemoryCategory("knowledge_summary"); }} className="rounded px-2 py-1 text-fgmuted hover:bg-white/5 hover:text-accent">Save to memory</button>
                          <button type="button" onClick={() => void sendFeedback(message.id, "up")} aria-label="Good response" className={clsx("rounded px-2 py-1 hover:bg-white/5", feedback[message.id] === "up" ? "text-success" : "text-fgmuted")}>👍</button>
                          <button type="button" onClick={() => void sendFeedback(message.id, "down")} aria-label="Bad response" className={clsx("rounded px-2 py-1 hover:bg-white/5", feedback[message.id] === "down" ? "text-danger" : "text-fgmuted")}>👎</button>
                        </>
                      )}
                    </div>
                  )}

                  {memoryFor === message.id && (
                    <div className="mt-2 flex flex-wrap items-center gap-2 rounded-md border border-edge bg-bg/60 p-2">
                      <select value={memoryCategory} onChange={(event) => setMemoryCategory(event.target.value)} aria-label="Memory category" className="rounded border border-edge bg-bg px-2 py-1 text-caption text-fg">
                        {CATEGORIES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                      </select>
                      <Button size="sm" variant="secondary" onClick={() => void saveToMemory(message.id)}>Save</Button>
                      <span className="text-[11px] text-fgmuted">Only this message becomes long-term memory.</span>
                    </div>
                  )}
                </div>
              </article>
            );
          })}

          {lastRun && lastRun.events.length > 0 && (
            <details className="mx-auto w-full max-w-4xl rounded-lg border border-edge/70 bg-surface/50 p-3">
              <summary className="cursor-pointer text-caption text-fgmuted">
                Tool activity · {lastRun.events.length} event{lastRun.events.length === 1 ? "" : "s"} · {lastRun.provider}/{lastRun.model || "offline"}
              </summary>
              <ul className="mt-3 space-y-2">
                {lastRun.events.map((event, index) => (
                  <li key={`${event.tool}-${index}`} className="rounded-md border border-edge/60 bg-bg/50 p-2 text-caption">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-mono text-accent">{event.tool}</span>
                      <Badge tone={event.ok ? "success" : "danger"}>{event.ok ? "ok" : "failed"}</Badge>
                      <span className="text-fgmuted">{event.risk} risk</span>
                    </div>
                    <pre className="mt-1 overflow-x-auto whitespace-pre-wrap break-words text-[11px] text-fgmuted">
                      {JSON.stringify(event.result || { blocked: event.blocked, error: event.error }, null, 2)}
                    </pre>
                  </li>
                ))}
              </ul>
            </details>
          )}

          {approval && (
            <div className="mx-auto w-full max-w-4xl">
              <ApprovalCard
                approval={approval}
                busy={busy}
                onApprove={(id) => void decideApproval(id, "approve")}
                onReject={(id) => void decideApproval(id, "reject")}
                onRetry={(id) => void retryApproval(id)}
              />
            </div>
          )}

          {error && (
            <div className="mx-auto w-full max-w-4xl rounded-xl border border-danger/50 bg-danger/5 p-4" role="alert">
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone="danger">Error</Badge>
                <span className="font-mono text-caption text-fgmuted">{error.code}</span>
                {error.requestId && <span className="font-mono text-caption text-fgmuted">request {error.requestId}</span>}
                {!error.requestId && <span className="text-caption text-fgmuted">No server request ID was returned.</span>}
              </div>
              <p className="mt-2 text-body text-fg">{error.message}</p>
              {error.hint && <p className="mt-1 text-caption text-fgmuted">{error.hint}</p>}
              <div className="mt-3 flex flex-wrap gap-2">
                {error.canRetry && lastPayloadRef.current && (
                  <Button size="sm" variant="secondary" onClick={() => lastPayloadRef.current && void send(lastPayloadRef.current, false)}>Retry without streaming</Button>
                )}
                {isApprovalError && (approval?.run_id || runId) && (
                  <Button size="sm" variant="primary" onClick={() => void retryApproval(approval?.run_id || runId || "")}>Ask again — new approval</Button>
                )}
                <Button size="sm" variant="ghost" onClick={() => setError(null)}>Dismiss</Button>
              </div>
            </div>
          )}

          {!query.trim() && !busy && messages.length > 0 && messages[messages.length - 1]?.role === "assistant" && (
            <div className="mx-auto flex max-w-4xl justify-end">
              <Button size="sm" variant="ghost" onClick={() => void regenerate()} disabled={!activeId}>Regenerate last answer</Button>
            </div>
          )}

          <div className="armx-scroll-anchor" aria-hidden="true" />
        </div>

        {showJump && (
          <button
            type="button"
            onClick={() => { autoScrollRef.current = true; scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" }); setShowJump(false); }}
            className="sticky bottom-4 left-full z-10 rounded-full border border-accent/50 bg-surface/90 px-3 py-1.5 text-caption text-accent shadow-lg"
          >
            ↓ Jump to latest
          </button>
        )}
      </div>

      <Composer
        value={draft}
        onChange={setDraft}
        onSend={onSend}
        onStop={() => void onStop()}
        busy={busy}
        streaming={streaming}
        attachments={attachments}
        onAttachmentsChange={setAttachments}
        modelLabel={actualRoute || (model ? `selected: ${model}` : "auto route")}
      />
    </section>
  );
}

export default function AssistantPage() {
  return (
    <Suspense fallback={<div className="flex h-full items-center justify-center text-body text-fgmuted">Loading assistant…</div>}>
      <AssistantWorkspace />
    </Suspense>
  );
}
