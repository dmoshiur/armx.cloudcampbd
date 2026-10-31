"use client";

import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import clsx from "clsx";

type Toast = { id: number; tone: "success" | "error" | "info"; message: string };
type Ctx = { push: (message: string, tone?: Toast["tone"]) => void };

const ToastContext = createContext<Ctx | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);

  const push = useCallback((message: string, tone: Toast["tone"] = "info") => {
    const id = Date.now() + Math.random();
    setItems((prev) => [...prev, { id, tone, message }]);
    setTimeout(() => setItems((prev) => prev.filter((t) => t.id !== id)), 5000);
  }, []);

  const value = useMemo(() => ({ push }), [push]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div
        aria-live="polite"
        aria-atomic="true"
        className="pointer-events-none fixed bottom-24 left-1/2 z-[60] flex w-full max-w-sm -translate-x-1/2 flex-col gap-2 px-4 md:bottom-6 md:left-auto md:right-6 md:translate-x-0"
      >
        {items.map((t) => (
          <div
            key={t.id}
            className={clsx(
              "animate-fade-up pointer-events-auto rounded-md border px-4 py-3 text-body shadow-lg shadow-black/30",
              t.tone === "success" && "border-success/40 bg-surface text-fg",
              t.tone === "error" && "border-danger/50 bg-surface text-fg",
              t.tone === "info" && "border-edge bg-surface text-fg",
            )}
          >
            <span className="mr-2 text-caption font-semibold uppercase tracking-wide text-fgmuted">{t.tone}</span>
            {t.message}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): Ctx {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used inside ToastProvider");
  return ctx;
}
