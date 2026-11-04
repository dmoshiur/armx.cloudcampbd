"use client";

import clsx from "clsx";
import { useCallback, useEffect, useRef, useState, type ChangeEvent, type DragEvent, type KeyboardEvent } from "react";
import { api, describeError } from "@/lib/api/client";
import type { UploadResult } from "@/lib/types";
import { useToast } from "@/components/ui/toast";

interface SpeechResultLike {
  results: ArrayLike<ArrayLike<{ transcript: string }>>;
}
interface SpeechRecognitionLike {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  start(): void;
  stop(): void;
  onresult: ((event: SpeechResultLike) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
}

const ACCEPTED = "image/*,.pdf,.txt,.md,.csv,.json,.log,.yaml,.yml";
const MAX_BYTES = 8 * 1024 * 1024;

export interface ComposerProps {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  onStop: () => void;
  busy: boolean;
  streaming: boolean;
  attachments: UploadResult[];
  onAttachmentsChange: (assets: UploadResult[]) => void;
  modelLabel?: string;
  disabled?: boolean;
}

export function Composer({
  value,
  onChange,
  onSend,
  onStop,
  busy,
  streaming,
  attachments,
  onAttachmentsChange,
  modelLabel,
  disabled = false,
}: ComposerProps) {
  const toast = useToast();
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [listening, setListening] = useState(false);

  const resize = useCallback(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(180, Math.max(48, el.scrollHeight))}px`;
  }, []);

  useEffect(() => resize(), [value, resize]);

  useEffect(() => () => recognitionRef.current?.stop(), []);

  const uploadFiles = useCallback(
    async (files: FileList | File[]) => {
      const list = Array.from(files);
      if (!list.length) return;
      const accepted = list.filter((file) => {
        if (file.size > MAX_BYTES) {
          toast.push(`${file.name} is larger than 8 MB and was not uploaded.`, "error");
          return false;
        }
        return true;
      });
      if (!accepted.length) return;
      setUploading(true);
      try {
        const uploaded: UploadResult[] = [];
        for (const file of accepted) {
          const asset = await api.upload<UploadResult>("/media/upload", file);
          uploaded.push(asset);
        }
        onAttachmentsChange([...attachments, ...uploaded]);
        toast.push(`${uploaded.length} attachment${uploaded.length === 1 ? "" : "s"} ready.`, "success");
      } catch (err) {
        toast.push(describeError(err, "upload a file"), "error");
      } finally {
        setUploading(false);
        if (fileRef.current) fileRef.current.value = "";
      }
    },
    [attachments, onAttachmentsChange, toast],
  );

  const toggleVoice = useCallback(() => {
    if (listening) {
      recognitionRef.current?.stop();
      setListening(false);
      return;
    }
    const scope = window as unknown as {
      SpeechRecognition?: new () => SpeechRecognitionLike;
      webkitSpeechRecognition?: new () => SpeechRecognitionLike;
    };
    const Ctor = scope.SpeechRecognition || scope.webkitSpeechRecognition;
    if (!Ctor) {
      toast.push("Voice dictation needs a browser with the Web Speech API (Chrome or Edge). You can still type.", "info");
      return;
    }
    const recognition = new Ctor();
    recognition.lang = "en-US";
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.onresult = (event) => {
      const first = event.results[0]?.[0]?.transcript;
      if (first) onChange(value ? `${value} ${first}` : first);
    };
    recognition.onerror = (event) => {
      setListening(false);
      toast.push(`Microphone stopped: ${event.error}. Nothing was recorded silently.`, "error");
    };
    recognition.onend = () => setListening(false);
    try {
      recognition.start();
      recognitionRef.current = recognition;
      setListening(true);
    } catch {
      toast.push("Microphone permission was not granted. Dictation was not started.", "error");
    }
  }, [listening, onChange, toast, value]);

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      if (!busy && (value.trim() || attachments.length)) onSend();
    }
  };

  const onDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragging(false);
    if (!disabled) void uploadFiles(event.dataTransfer.files);
  };

  return (
    <div
      className={clsx("armx-composer", dragging && "armx-drop-active")}
      onDragEnter={(event) => { event.preventDefault(); setDragging(true); }}
      onDragOver={(event) => event.preventDefault()}
      onDragLeave={(event) => { if (event.currentTarget === event.target) setDragging(false); }}
      onDrop={onDrop}
    >
      <div className="mx-auto w-full max-w-4xl px-3 py-2.5 sm:px-4">
        {attachments.length > 0 && (
          <div className="mb-2 flex flex-wrap gap-2" aria-label="Attachments">
            {attachments.map((asset) => (
              <span key={asset.asset_id} className="inline-flex max-w-[220px] items-center gap-2 rounded-md border border-edge bg-surface2/80 px-2 py-1 text-caption text-fgmuted">
                <span aria-hidden="true">{asset.kind === "image" ? "▣" : "▤"}</span>
                <span className="truncate">{asset.filename}</span>
                <button
                  type="button"
                  aria-label={`Remove ${asset.filename}`}
                  onClick={() => onAttachmentsChange(attachments.filter((a) => a.asset_id !== asset.asset_id))}
                  className="text-fgmuted hover:text-danger"
                >
                  ×
                </button>
              </span>
            ))}
          </div>
        )}

        <div className="rounded-xl border border-edge/80 bg-bg/65 p-2 shadow-inner transition focus-within:border-accent/50 focus-within:shadow-[0_0_0_3px_rgba(0,255,65,0.06)]">
          <textarea
            ref={textareaRef}
            value={value}
            rows={1}
            disabled={disabled}
            onChange={(event: ChangeEvent<HTMLTextAreaElement>) => onChange(event.target.value)}
            onKeyDown={onKeyDown}
            placeholder={disabled ? "Sign in to use the assistant" : "Message A.R.M.X AI…  (Enter to send · Shift+Enter for a new line)"}
            aria-label="Message A.R.M.X AI"
            className="max-h-[180px] w-full resize-none bg-transparent px-2 py-1.5 text-body leading-6 text-fg outline-none placeholder:text-fgmuted/70"
          />
          <div className="flex flex-wrap items-center gap-1.5 border-t border-edge/60 px-1 pt-2">
            <input ref={fileRef} type="file" multiple accept={ACCEPTED} className="hidden" onChange={(event) => event.target.files && void uploadFiles(event.target.files)} />
            <button
              type="button"
              onClick={() => fileRef.current?.click()}
              disabled={disabled || uploading}
              aria-label="Attach an image or document"
              title="Attach image or document"
              className="grid h-9 w-9 place-items-center rounded-md border border-edge/70 text-fgmuted transition hover:border-accent/40 hover:text-accent disabled:opacity-40"
            >
              {uploading ? <span className="h-3 w-3 animate-spin rounded-full border-2 border-accent border-t-transparent" /> : "＋"}
            </button>
            <button
              type="button"
              onClick={toggleVoice}
              disabled={disabled}
              aria-label={listening ? "Stop microphone dictation" : "Start microphone dictation"}
              aria-pressed={listening}
              title="Microphone starts only when you tap; a recording indicator appears while listening."
              className={clsx(
                "grid h-9 w-9 place-items-center rounded-md border transition disabled:opacity-40",
                listening ? "border-danger/60 bg-danger/10 text-danger" : "border-edge/70 text-fgmuted hover:border-accent/40 hover:text-accent",
              )}
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" className="h-4 w-4" aria-hidden="true">
                <rect x="9" y="3" width="6" height="11" rx="3" />
                <path d="M5 11a7 7 0 0014 0M12 18v3" />
              </svg>
            </button>
            {listening && <span className="flex items-center gap-1.5 text-caption text-danger"><span className="h-2 w-2 animate-pulse rounded-full bg-danger" /> Listening — microphone active</span>}
            {uploading && <span className="text-caption text-fgmuted">Uploading…</span>}
            <span className="ml-auto hidden items-center gap-2 text-caption text-fgmuted sm:flex">
              {busy && <span className="flex items-center gap-1.5"><span className="h-1.5 w-1.5 animate-pulse-soft rounded-full bg-accent" />{streaming ? "Streaming" : "Working"}</span>}
              {modelLabel && <span className="max-w-[220px] truncate font-mono text-[11px]">{modelLabel}</span>}
            </span>
            {busy ? (
              <button
                type="button"
                onClick={onStop}
                className="inline-flex h-9 items-center gap-2 rounded-md border border-danger/50 bg-danger/10 px-3 text-caption font-semibold text-danger transition hover:bg-danger/20"
              >
                <span className="h-2.5 w-2.5 rounded-[2px] bg-danger" /> Stop
              </button>
            ) : (
              <button
                type="button"
                onClick={onSend}
                disabled={disabled || (!value.trim() && !attachments.length)}
                aria-label="Send message"
                className="inline-flex h-9 items-center gap-2 rounded-md bg-accent px-3 text-caption font-bold text-ink shadow shadow-accent/20 transition hover:bg-accentbright disabled:cursor-not-allowed disabled:opacity-40"
              >
                Send <span aria-hidden="true">↗</span>
              </button>
            )}
          </div>
        </div>
        <p className="mt-1.5 flex flex-wrap gap-x-3 gap-y-0.5 px-1 text-[11px] text-fgmuted/70">
          <span>Enter sends · Shift+Enter adds a line</span>
          <span className="hidden sm:inline">Drop files here · images, PDF, TXT, MD, CSV, JSON · max 8 MB</span>
          <span className="hidden md:inline">AI responses can be wrong — verify high-risk actions.</span>
        </p>
      </div>
    </div>
  );
}
