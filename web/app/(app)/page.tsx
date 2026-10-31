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

    try {
      const data = await api.post<ChatResponse>("/assistant/chat", {
        message,
        conversation_id: activeId,
      });
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
      const msg = err instanceof ApiError ? err.message : "Could not reach the assistant";
      setError(msg);
      toast.push(msg, "error");
    } finally {
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
    <div className="lg:grid lg:grid-cols-[280px_1fr] lg:gap-6">
      {/* Conversation list: drawer on compact, column on expanded */}
      <div
        className={clsx(
          "mb-4 lg:mb-0",
          historyOpen ? "block" : "hidden lg:block",
        )}
      >
        <Card className="p-3">
          <div className="mb-2 flex items-center justify-between gap-2 px-1">
            <h2 className="text-caption font-semibold uppercase tracking-wide text-fgmuted">Conversations</h2>
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
      <div className="flex min-h-[calc(100vh-190px)] flex-col">
        <div className="mb-3 flex items-center justify-between gap-2">
          <div>
            <h1 className="text-h1">Assistant</h1>
            <p className="mt-1 text-caption text-fgmuted">
              Claude plans; the security gateway authorises. Medium- and high-risk actions pause for your approval.
            </p>
          </div>
          <Button variant="secondary" size="sm" className="lg:hidden" onClick={() => setHistoryOpen((v) => !v)}>
            {historyOpen ? "Hide chats" : "Chats"}
          </Button>
        </div>

        <div className="flex-1 space-y-4 overflow-y-auto pb-4">
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
                <div className="mt-2 flex flex-wrap justify-center gap-2">
                  {SUGGESTIONS.map((s) => (
                    <button
                      key={s}
                      type="button"
                      onClick={() => void send(s)}
                      className="min-h-[40px] rounded-full border border-edge px-3 text-caption text-fgmuted transition hover:border-accent/60 hover:text-fg"
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
                    "whitespace-pre-wrap rounded-lg px-4 py-3 text-body",
                    turn.role === "user" ? "bg-accent text-ink" : "border border-edge bg-surface text-fg",
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
        <div className="sticky bottom-16 border-t border-edge bg-bg pt-3 md:bottom-0">
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
      </div>

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
