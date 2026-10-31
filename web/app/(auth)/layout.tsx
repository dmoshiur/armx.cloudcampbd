import Link from "next/link";
import type { ReactNode } from "react";

export default function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <div className="mx-auto flex min-h-screen max-w-content flex-col px-4 py-6 lg:grid lg:grid-cols-2 lg:items-center lg:gap-16 lg:py-10">
      <section className="mb-8 lg:mb-0">
        <Link href="/" className="inline-flex items-center gap-3">
          <span className="grid h-10 w-10 place-items-center rounded-md bg-accent text-lg font-bold text-ink" aria-hidden="true">
            A
          </span>
          <span className="text-h2 tracking-tight">A.R.M.X AI</span>
        </Link>
        <h1 className="mt-8 text-display text-balance">An assistant that asks before it acts.</h1>
        <p className="mt-4 max-w-md text-body text-fgmuted">
          Claude plans. A security gateway decides. Every medium- and high-risk action waits for your explicit,
          single-use approval — and the kill-switch stops everything at once.
        </p>
        <ul className="mt-8 space-y-3 text-body text-fgmuted">
          {[
            "Describe a site, preview it, deploy it — with confirmation.",
            "Smart-home control through an entity allowlist.",
            "Linked devices you can always see and instantly unlink.",
            "A tamper-evident audit trail of every tool call.",
          ].map((line) => (
            <li key={line} className="flex gap-3">
              <span aria-hidden="true" className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-accent" />
              {line}
            </li>
          ))}
        </ul>
      </section>
      <section className="w-full rounded-xl border border-edge bg-surface p-6 sm:p-8">{children}</section>
    </div>
  );
}
