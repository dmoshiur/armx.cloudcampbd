"use client";

import clsx from "clsx";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import { useAuth } from "@/lib/hooks/useAuth";
import type { HealthStatus } from "@/lib/types";
import { Badge, Button, StatusDot } from "@/components/ui/primitives";
import { ToastProvider } from "@/components/ui/toast";

const NAV = [
  { href: "/", label: "Assistant", icon: "M4 5h16M4 12h10M4 19h7" },
  { href: "/builder", label: "Site builder", icon: "M4 7l8-4 8 4v10l-8 4-8-4V7zM4 7l8 4 8-4M12 11v10" },
  { href: "/devices", label: "Devices", icon: "M7 3h10a2 2 0 012 2v14a2 2 0 01-2 2H7a2 2 0 01-2-2V5a2 2 0 012-2zM11 18h2" },
  { href: "/tools", label: "Capabilities", icon: "M9 3v4m6-4v4M6 7h12v6a6 6 0 11-12 0V7z" },
  { href: "/settings", label: "Settings", icon: "M12 15a3 3 0 100-6 3 3 0 000 6zM19 12a7 7 0 00-.1-1l2-1.5-2-3.4-2.3 1a7 7 0 00-1.7-1L14.5 3h-5l-.4 2.6a7 7 0 00-1.7 1l-2.3-1-2 3.4L5 11a7 7 0 000 2l-2 1.5 2 3.4 2.3-1a7 7 0 001.7 1l.4 2.6h5l.4-2.6a7 7 0 001.7-1l2.3 1 2-3.4L19 13c.06-.33.1-.66.1-1z" },
];

function Icon({ path, className }: { path: string; className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" className={className ?? "h-5 w-5"} aria-hidden="true">
      <path d={path} />
    </svg>
  );
}

function ThemeToggle() {
  const [theme, setTheme] = useState<"dark" | "light">("dark");

  useEffect(() => {
    const saved = (localStorage.getItem("armx.theme") as "dark" | "light" | null) ?? "dark";
    setTheme(saved);
  }, []);

  const apply = (next: "dark" | "light") => {
    setTheme(next);
    localStorage.setItem("armx.theme", next);
    const root = document.documentElement;
    root.classList.remove("dark", "light");
    root.classList.add(next);
  };

  return (
    <button
      type="button"
      onClick={() => apply(theme === "dark" ? "light" : "dark")}
      aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
      className="grid h-10 w-10 place-items-center rounded-md border border-edge text-fgmuted transition hover:bg-white/5 hover:text-fg"
    >
      {theme === "dark" ? (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" className="h-5 w-5" aria-hidden="true">
          <circle cx="12" cy="12" r="4" />
          <path d="M12 2v2m0 16v2M4.9 4.9l1.4 1.4m11.4 11.4l1.4 1.4M2 12h2m16 0h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
        </svg>
      ) : (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" className="h-5 w-5" aria-hidden="true">
          <path d="M21 12.8A9 9 0 1111.2 3a7 7 0 009.8 9.8z" />
        </svg>
      )}
    </button>
  );
}

function KillSwitchBanner() {
  const { data } = useQuery({
    queryKey: ["health"],
    queryFn: () => api.get<HealthStatus>("/health"),
    refetchInterval: 30_000,
  });

  if (!data) return null;
  const engaged = data.kill_switch === "on";

  return (
    <div
      className={clsx(
        "flex flex-wrap items-center gap-x-4 gap-y-2 border-b px-4 py-2 text-caption",
        engaged ? "border-danger/40 bg-danger/10 text-danger" : "border-edge bg-surface text-fgmuted",
      )}
    >
      {engaged ? (
        <span className="font-semibold">Kill-switch is engaged — every integration and tool is halted.</span>
      ) : (
        <StatusDot tone="success" label="All systems operational" />
      )}
      <span className="hidden sm:inline">
        Planner: <span className="text-fg">{data.planner.provider}</span>
        {!data.planner.live && " (offline planner — set ANTHROPIC_API_KEY for live Claude)"}
      </span>
      <span className="ml-auto hidden md:inline">
        Pipeline: {data.pipeline_mode}
        {data.pipeline_mode === "simulated" && " (deployments are simulated)"}
      </span>
    </div>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const { user, logout } = useAuth();
  const isAdmin = user?.role === "admin";

  const items = isAdmin ? [...NAV, { href: "/admin", label: "Admin", icon: "M12 3l8 4v5c0 5-3.4 8.2-8 9-4.6-.8-8-4-8-9V7l8-4z" }] : NAV;

  return (
    <ToastProvider>
      <div className="min-h-screen">
        <KillSwitchBanner />
        <div className="mx-auto flex max-w-content">
          {/* Sidebar: expanded */}
          <aside className="sticky top-0 hidden h-[calc(100vh-41px)] w-[264px] shrink-0 flex-col border-r border-edge px-3 py-5 lg:flex">
            <Link href="/" className="mb-6 flex items-center gap-2.5 px-2">
              <span className="grid h-9 w-9 place-items-center rounded-md bg-accent font-bold text-ink" aria-hidden="true">
                A
              </span>
              <span className="text-h3 tracking-tight">A.R.M.X AI</span>
            </Link>
            <nav aria-label="Primary" className="flex flex-1 flex-col gap-1">
              {items.map((item) => {
                const active = pathname === item.href || (item.href !== "/" && pathname.startsWith(item.href));
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    aria-current={active ? "page" : undefined}
                    className={clsx(
                      "flex min-h-touch items-center gap-3 rounded-md px-3 text-body transition",
                      active ? "bg-accent/10 font-semibold text-accent" : "text-fgmuted hover:bg-white/5 hover:text-fg",
                    )}
                  >
                    <Icon path={item.icon} />
                    {item.label}
                  </Link>
                );
              })}
            </nav>
            <div className="mt-4 space-y-2 border-t border-edge pt-4">
              {user && (
                <div className="px-3">
                  <p className="truncate text-caption font-semibold text-fg">{user.display_name || user.email}</p>
                  <p className="truncate text-caption text-fgmuted">{user.role.toUpperCase()}</p>
                </div>
              )}
              <Button variant="ghost" size="sm" className="w-full justify-start" onClick={logout}>
                Sign out
              </Button>
            </div>
          </aside>

          {/* Rail: medium */}
          <aside className="sticky top-0 hidden h-[calc(100vh-41px)] w-[84px] shrink-0 flex-col items-center gap-1 border-r border-edge py-5 md:flex lg:hidden">
            <Link href="/" aria-label="A.R.M.X AI home" className="mb-4 grid h-9 w-9 place-items-center rounded-md bg-accent font-bold text-ink">
              A
            </Link>
            {items.map((item) => {
              const active = pathname === item.href || (item.href !== "/" && pathname.startsWith(item.href));
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  aria-label={item.label}
                  aria-current={active ? "page" : undefined}
                  className={clsx(
                    "grid h-12 w-12 place-items-center rounded-md transition",
                    active ? "bg-accent/10 text-accent" : "text-fgmuted hover:bg-white/5 hover:text-fg",
                  )}
                >
                  <Icon path={item.icon} />
                </Link>
              );
            })}
          </aside>

          {/* Content */}
          <div className="flex min-h-[calc(100vh-41px)] w-full min-w-0 flex-col">
            <div className="flex items-center justify-between gap-3 border-b border-edge px-4 py-2 md:hidden">
              <Link href="/" className="flex items-center gap-2">
                <span className="grid h-8 w-8 place-items-center rounded-md bg-accent text-caption font-bold text-ink">A</span>
                <span className="text-body font-semibold">A.R.M.X AI</span>
              </Link>
              <div className="flex items-center gap-2">
                {isAdmin && <Badge tone="accent">admin</Badge>}
                <ThemeToggle />
              </div>
            </div>
            <div className="hidden justify-end gap-2 px-6 pt-4 md:flex">
              <ThemeToggle />
            </div>
            <main className="flex-1 px-4 pb-24 pt-4 md:px-6 md:pb-8">{children}</main>
          </div>
        </div>

        {/* Bottom nav: compact */}
        <nav aria-label="Primary" className="fixed inset-x-0 bottom-0 z-40 border-t border-edge bg-surface/95 backdrop-blur md:hidden">
          <div className="mx-auto flex max-w-content items-stretch">
            {items.slice(0, 5).map((item) => {
              const active = pathname === item.href || (item.href !== "/" && pathname.startsWith(item.href));
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  aria-current={active ? "page" : undefined}
                  className={clsx(
                    "flex min-h-[60px] flex-1 flex-col items-center justify-center gap-1 text-[11px] transition",
                    active ? "text-accent" : "text-fgmuted",
                  )}
                >
                  <Icon path={item.icon} />
                  <span>{item.label}</span>
                </Link>
              );
            })}
          </div>
        </nav>
      </div>
    </ToastProvider>
  );
}
