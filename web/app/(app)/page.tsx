"use client";

import clsx from "clsx";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "@/lib/api/client";
import type { ChatResponse, Conversation, ConversationDetail } from "@/lib/types";
import { Badge, Button, Card, EmptyState, ErrorState, Skeleton, Textarea } from "@/components/ui/primitives";
import { ConfirmActionDialog } from "@/components/ui/dialog";
import { useToast } from "@/components/ui/toast";
import { ToolEventCard } from "@/components/app/tool-event";

interface Turn {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  events?: ChatResponse["tool_events"];
  approval?: ChatResponse["approval"];
  runId?: string;
}

const SUGGESTIONS = [
  "Check system health",
  "Turn on the living room light",
  "Build a landing page for a bakery in Dhaka",
  "Search the web for today's Dhaka weather",
];

export default function AssistantPage() {
  const toast = useToast();
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [approval, setApproval] = useState<{ approval: NonNullable<ChatResponse["approval"]>; runId: string } | null>(null);
  const [listening, setListening] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const recognitionRef = useRef<{ stop: () => void } | null>(null);

  const scrollToBottom = useCallback(() => {
    requestAnimationFrame(() => bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" }));
  }, []);

  const loadConversations = useCallback(async () => {
    try {
      setConversations(await api.get<Conversation[]>("/assistant/conversations"));
    } catch {
      /* the list is best-effort */
    }
  }, []);

  useEffect(() => {
    void loadConversations();
  }, [loadConversations]);

  async function openConversation(id: string) {
    setActiveId(id);
    setHistoryOpen(false);
    setLoadingHistory(true);
    try {
      const detail = await api.get<ConversationDetail>(`/assistant/conversations/${id}`);
      setTurns(
        detail.messages.map((m) => ({
          id: m.id,
          role: m.role === "user" ? "user" : "assistant",
          content: m.content,
        })),
      );
      scrollToBottom();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load that conversation");
    } finally {
      setLoadingHistory(false);
    }
  }

  function startNew() {
    setActiveId(null);
    setTurns([]);
    setApproval(null);
    setError(null);
    setHistoryOpen(false);
  }

  async function send(message: string) {
    if (!message.trim() || busy) return;
    setBusy(true);
    setError(null);
    setInput("");
    const userTurn: Turn = { id: `u-${Date.now()}`, role: "user", content: message };
    setTurns((prev) => [...prev, userTurn]);
    scrollToBottom();

    const controller = new AbortController();
    // The API has a 50s deadline; this slightly longer browser guard also
    // covers proxy/network failures where no response arrives at all.
    const timeout = window.setTimeout(() => controller.abort(), 55_000);
    try {
      const data = await api.post<ChatResponse>(
        "/assistant/chat",
        {
          message,
          conversation_id: activeId,
        },
        { signal: controller.signal },
      );
      if (data.status === "complete" && !data.reply.trim() && !data.approval) {
        throw new ApiError(
          "The provider returned an empty response. Test the active model in LLM settings.",
          502,
          "empty_assistant_response",
          data,
          data.request_id,
        );
      }
      setActiveId(data.conversation_id);
      setTurns((prev) => [
        ...prev,
        {
          id: `a-${Date.now()}`,
          role: "assistant",
          content: data.reply || (data.approval ? "This action needs your approval before it runs." : ""),
          events: data.tool_events,
          approval: data.approval,
          runId: data.run_id,
        },
      ]);
      if (data.approval) setApproval({ approval: data.approval, runId: data.run_id });
      if (data.status === "error") setError(data.error ?? "The assistant hit an error");
      void loadConversations();
    } catch (err) {
      const aborted = err instanceof DOMException && err.name === "AbortError";
      const base = aborted
        ? "The assistant request timed out after 55 seconds. Check the audit log before retrying a tool command."
        : err instanceof ApiError
          ? err.message
          : "Could not reach the assistant";
      const requestId = err instanceof ApiError && err.requestId ? ` Request ID: ${err.requestId}.` : "";
      const msg = `${base}${requestId}`;
      setError(msg);
      toast.push(msg, "error");
    } finally {
      window.clearTimeout(timeout);
      setBusy(false);
      scrollToBottom();
    }
  }

  async function decide(decision: "approve" | "reject") {
    if (!approval) return;
    setBusy(true);
    try {
      const data = await api.post<ChatResponse>(`/assistant/runs/${approval.runId}/approve`, {
        approval_id: approval.approval.id,
        decision,
      });
      setTurns((prev) => [
        ...prev,
        {
          id: `a-${Date.now()}`,
          role: "assistant",
          content: data.reply || (decision === "reject" ? "Cancelled — nothing was executed." : "Done."),
          events: data.tool_events,
          runId: data.run_id,
        },
      ]);
      toast.push(decision === "reject" ? "Action cancelled" : "Action approved and executed", decision === "reject" ? "info" : "success");
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : "Could not complete that approval";
      setError(msg);
      toast.push(msg, "error");
    } finally {
      setApproval(null);
      setBusy(false);
      scrollToBottom();
    }
  }

  function toggleMic() {
    type SpeechCtor = new () => {
      lang: string;
      interimResults: boolean;
      continuous: boolean;
      onresult: (event: { results: { 0: { 0: { transcript: string } } } }) => void;
      onend: () => void;
      onerror: () => void;
      start: () => void;
      stop: () => void;
    };
    const w = window as unknown as { SpeechRecognition?: SpeechCtor; webkitSpeechRecognition?: SpeechCtor };
    const Ctor = w.SpeechRecognition ?? w.webkitSpeechRecognition;
    if (!Ctor) {
      toast.push("This browser has no speech recognition. Browsers only support push-to-talk, never wake words.", "error");
      return;
    }
    if (listening) {
      recognitionRef.current?.stop();
      setListening(false);
      return;
    }
    const recognition = new Ctor();
    recognition.lang = navigator.language || "en-US";
    recognition.interimResults = false;
    recognition.continuous = false;
    recognition.onresult = (event) => {
      const transcript = event.results[0][0].transcript;
      setInput((prev) => (prev ? `${prev} ${transcript}` : transcript));
    };
    recognition.onend = () => setListening(false);
    recognition.onerror = () => {
      setListening(false);
      toast.push("Microphone access was blocked or failed.", "error");
    };
    recognition.start();
    recognitionRef.current = recognition;
    setListening(true);
  }

  const showEmpty = turns.length === 0 && !loadingHistory;

  return (
    <div className="mx-auto w-full max-w-[1560px] lg:grid lg:grid-cols-[300px_minmax(0,1fr)] lg:gap-5 xl:gap-7">
      {/* Conversation list: drawer on compact, column on expanded */}
      <div
        className={clsx(
          "mb-4 lg:mb-0",
          historyOpen ? "block" : "hidden lg:block",
        )}
      >
        <Card className="overflow-hidden border-edge/70 bg-surface/75 p-3 shadow-2xl shadow-black/20 backdrop-blur-xl">
          <div className="mb-3 flex items-center justify-between gap-2 border-b border-edge/70 px-1 pb-3">
            <div>
              <p className="mb-1 text-[10px] font-bold uppercase tracking-[0.22em] text-accent/80">Workspace</p>
              <h2 className="text-caption font-semibold uppercase tracking-wide text-fgmuted">Conversations</h2>
            </div>
            <Button size="sm" variant="secondary" onClick={startNew}>
              New
            </Button>
          </div>
          <nav aria-label="Conversations" className="max-h-[40vh] space-y-1 overflow-y-auto lg:max-h-[calc(100vh-240px)]">
            {conversations.length === 0 && <p className="px-2 py-3 text-caption text-fgmuted">No conversations yet.</p>}
            {conversations.map((conversation) => (
              <button
                key={conversation.id}
                type="button"
                onClick={() => void openConversation(conversation.id)}
                className={clsx(
                  "block w-full truncate rounded-md px-2.5 py-2 text-left text-caption transition",
                  activeId === conversation.id ? "bg-accent/10 font-semibold text-accent" : "text-fgmuted hover:bg-white/5 hover:text-fg",
                )}
              >
                {conversation.title || "Untitled"}
              </button>
            ))}
          </nav>
        </Card>
      </div>

      {/* Thread */}
      <section className="relative flex min-h-[calc(100vh-150px)] flex-col overflow-hidden rounded-xl border border-edge/70 bg-bg/75 shadow-2xl shadow-black/30 backdrop-blur-xl">
        <div className="pointer-events-none absolute inset-x-0 top-0 h-28 bg-gradient-to-b from-accent/5 to-transparent" />
        <div className="relative flex items-start justify-between gap-4 border-b border-edge/60 px-4 py-4 sm:px-6">
          <div>
            <p className="mb-1.5 text-[10px] font-bold uppercase tracking-[0.24em] text-accent">Secure intelligence console</p>
            <div className="flex flex-wrap items-center gap-3">
              <h1 className="text-h1">A.R.M.X Assistant</h1>
              <Badge tone="success">Gateway protected</Badge>
            </div>
            <p className="mt-1.5 max-w-3xl text-caption text-fgmuted">
              Live models plan; the security gateway authorises. Sensitive actions always pause for your explicit approval.
            </p>
          </div>
          <Button variant="secondary" size="sm" className="lg:hidden" onClick={() => setHistoryOpen((v) => !v)}>
            {historyOpen ? "Hide chats" : "Chats"}
          </Button>
        </div>

        <div className="relative min-h-0 flex-1 space-y-5 overflow-y-auto px-4 py-6 sm:px-6">
          {loadingHistory && (
            <div className="space-y-3">
              <Skeleton className="h-16 w-2/3" />
              <Skeleton className="h-24 w-5/6" />
            </div>
          )}

          {showEmpty && (
            <EmptyState
              icon="✦"
              title="Ask for something real"
              description="Try one of these. Anything that touches a device, a repository or another person will ask you first."
              action={
                <div className="mt-4 grid w-full gap-2 sm:grid-cols-2">
                  {SUGGESTIONS.map((s) => (
                    <button
                      key={s}
                      type="button"
                      onClick={() => void send(s)}
                      className="min-h-[48px] rounded-md border border-edge/70 bg-surface/55 px-4 py-2 text-left text-caption text-fgmuted transition hover:-translate-y-0.5 hover:border-accent/60 hover:bg-accent/5 hover:text-fg"
                    >
                      {s}
                    </button>
                  ))}
                </div>
              }
            />
          )}

          {turns.map((turn) => (
            <div key={turn.id} className={clsx("flex", turn.role === "user" ? "justify-end" : "justify-start")}>
              <div className={clsx("max-w-full space-y-3 sm:max-w-[86%]", turn.role === "user" && "sm:max-w-[70%]")}>
                <div
                  className={clsx(
                    "whitespace-pre-wrap rounded-lg px-4 py-3 text-body shadow-lg",
                    turn.role === "user"
                      ? "rounded-br-sm bg-gradient-to-br from-accent to-emerald-400 text-ink shadow-accent/10"
                      : "rounded-bl-sm border border-edge/70 bg-surface/85 text-fg shadow-black/20 backdrop-blur",
                  )}
                >
                  {turn.content}
                </div>
                {turn.events?.map((event, index) => <ToolEventCard key={`${turn.id}-${index}`} event={event} />)}
                {turn.approval && !approval && (
                  <p className="text-caption text-fgmuted">
                    Approval request expired or dismissed — ask again to retry the action.
                  </p>
                )}
              </div>
            </div>
          ))}

          {busy && (
            <div className="flex items-center gap-2 text-caption text-fgmuted">
              <span className="h-2 w-2 animate-pulse rounded-full bg-accent" aria-hidden="true" />
              Working…
            </div>
          )}

          {error && <ErrorState message={error} onRetry={() => setError(null)} />}
          <div ref={bottomRef} />
        </div>

        {/* Composer */}
        <div className="relative border-t border-edge/60 bg-surface/75 p-3 backdrop-blur-xl sm:p-4">
          <form
            onSubmit={(event) => {
              event.preventDefault();
              void send(input);
            }}
            className="space-y-2"
          >
            <label htmlFor="composer" className="sr-only">
              Message the assistant
            </label>
            <Textarea
              id="composer"
              rows={2}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  void send(input);
                }
              }}
              placeholder="Ask A.R.M.X anything…"
              aria-describedby="composer-hint"
              className="min-h-[68px] resize-none border-edge/70 bg-bg/70 px-4 py-3 shadow-inner"
            />
            <div className="flex items-center justify-between gap-2">
              <p id="composer-hint" className="text-caption text-fgmuted">
                Web uses push-to-talk only — no wake word, no background listening in a browser.
              </p>
              <div className="flex items-center gap-2">
                <Button type="button" variant="secondary" size="sm" onClick={toggleMic} aria-pressed={listening}>
                  {listening ? "Stop" : "Speak"}
                </Button>
                <Button type="submit" size="sm" loading={busy} disabled={!input.trim()}>
                  Send
                </Button>
              </div>
            </div>
          </form>
        </div>
      </section>

      {approval && (
        <ConfirmActionDialog
          open
          busy={busy}
          tool={approval.approval.tool}
          risk={approval.approval.risk}
          args={approval.approval.args}
          consequences={
            approval.approval.tool === "web_deploy"
              ? [
                  "Files will be pushed to an allowlisted GitHub repository.",
                  "A Vercel production deployment will start and the site will be public.",
                  "You can re-prompt changes and deploy again afterwards.",
                ]
              : approval.approval.tool === "web_generate"
                ? ["A site will be generated in the sandbox and a preview rendered.", "Nothing is pushed or published yet."]
                : [approval.approval.description]
          }
          onCancel={() => void decide("reject")}
          onConfirm={() => void decide("approve")}
        />
      )}
    </div>
  );
}
