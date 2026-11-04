"use client";

import clsx from "clsx";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import { useAuth } from "@/lib/hooks/useAuth";
import { usePreferences } from "@/lib/preferences";
import type { HealthStatus } from "@/lib/types";
import { Badge, Button, StatusDot } from "@/components/ui/primitives";
import { ToastProvider } from "@/components/ui/toast";

interface NavItem {
  href: string;
  label: string;
  icon: string;
  group: string;
  admin?: boolean;
}

const ICONS = {
  assistant: "M4 5h16M4 12h10M4 19h7",
  conversations: "M21 12a8 8 0 01-8 8H7l-4 3v-6a8 8 0 1118-5z",
  builder: "M4 7l8-4 8 4v10l-8 4-8-4V7zM4 7l8 4 8-4M12 11v10",
  projects: "M3 7h6l2 2h10v10H3V7zM3 7V5h6l2 2",
  devices: "M7 3h10a2 2 0 012 2v14a2 2 0 01-2 2H7a2 2 0 01-2-2V5a2 2 0 012-2zM11 18h2",
  capabilities: "M9 3v4m6-4v4M6 7h12v6a6 6 0 11-12 0V7z",
  registry: "M4 5h16v4H4zM4 12h16v4H4zM7 19h10M7 2h10",
  automations: "M12 3v3m0 12v3M3 12h3m12 0h3M5.6 5.6l2.1 2.1m8.6 8.6l2.1 2.1M18.4 5.6l-2.1 2.1M7.7 16.3l-2.1 2.1M12 8a4 4 0 100 8 4 4 0 000-8z",
  memory: "M12 3a9 9 0 00-9 9v3a3 3 0 003 3h1v-8H5a7 7 0 0114 0h-2v8h1a3 3 0 003-3v-3a9 9 0 00-9-9z",
  activity: "M3 12h4l3-7 4 14 3-7h4",
  settings: "M12 15a3 3 0 100-6 3 3 0 000 6zM19 12a7 7 0 00-.1-1l2-1.5-2-3.4-2.3 1a7 7 0 00-1.7-1L14.5 3h-5l-.4 2.6a7 7 0 00-1.7 1l-2.3-1-2 3.4L5 11a7 7 0 000 2l-2 1.5 2 3.4 2.3-1a7 7 0 001.7 1l.4 2.6h5l.4-2.6a7 7 0 001.7-1l2.3 1 2-3.4L19 13c.06-.33.1-.66.1-1z",
  admin: "M12 3l8 4v5c0 5-3.4 8.2-8 9-4.6-.8-8-4-8-9V7l8-4zM9 12l2 2 4-4",
  menu: "M4 6h16M4 12h16M4 18h16",
  close: "M5 5l14 14M19 5L5 19",
  panel: "M4 4h16v16H4zM9 4v16",
} as const;

const NAV: NavItem[] = [
  { href: "/", label: "Assistant", icon: ICONS.assistant, group: "Workspace" },
  { href: "/conversations", label: "Conversations", icon: ICONS.conversations, group: "Workspace" },
  { href: "/builder", label: "Site Builder", icon: ICONS.builder, group: "Workspace" },
  { href: "/projects", label: "Projects", icon: ICONS.projects, group: "Workspace" },
  { href: "/devices", label: "Devices", icon: ICONS.devices, group: "Workspace" },
  { href: "/capabilities", label: "Capabilities", icon: ICONS.capabilities, group: "Intelligence" },
  { href: "/tools", label: "Tool Registry", icon: ICONS.registry, group: "Intelligence" },
  { href: "/automations", label: "Automations", icon: ICONS.automations, group: "Intelligence" },
  { href: "/memory", label: "Knowledge & Memory", icon: ICONS.memory, group: "Intelligence" },
  { href: "/activity", label: "Activity Logs", icon: ICONS.activity, group: "System" },
  { href: "/settings", label: "Settings", icon: ICONS.settings, group: "System" },
  { href: "/admin", label: "Admin Console", icon: ICONS.admin, group: "System", admin: true },
];

function Icon({ path, className }: { path: string; className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" className={className ?? "h-[18px] w-[18px]"} aria-hidden="true">
      <path d={path} />
    </svg>
  );
}

function ThemeToggle() {
  const { settings, update } = usePreferences();
  return (
    <button
      type="button"
      onClick={() => void update({ theme: settings.theme === "dark" ? "light" : "dark" })}
      aria-label={`Switch to ${settings.theme === "dark" ? "light" : "dark"} mode`}
      className="grid h-9 w-9 place-items-center rounded-md border border-edge/70 text-fgmuted transition hover:bg-white/5 hover:text-fg"
    >
      {settings.theme === "dark" ? (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" className="h-[18px] w-[18px]" aria-hidden="true">
          <circle cx="12" cy="12" r="4" />
          <path d="M12 2v2m0 16v2M4.9 4.9l1.4 1.4m11.4 11.4l1.4 1.4M2 12h2m16 0h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
        </svg>
      ) : (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" className="h-[18px] w-[18px]" aria-hidden="true">
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
  const tone = data.planner.ready ? "success" : data.planner.readiness === "degraded" ? "danger" : "warning";
  const label = data.planner.ready
    ? "AI route verified"
    : data.planner.readiness === "unverified"
      ? "Route configured — awaiting live verification"
      : data.planner.readiness === "degraded"
        ? "Route degraded — offline fallback available"
        : "Offline planner active";
  return (
    <div className={clsx("flex flex-none flex-wrap items-center gap-x-4 gap-y-1 border-b px-3 py-1.5 text-caption backdrop-blur-xl sm:px-5", engaged ? "border-danger/40 bg-danger/10 text-danger" : "border-edge/70 bg-surface/80 text-fgmuted")}>
      {engaged ? (
        <span className="font-semibold">Kill-switch engaged — every integration is halted.</span>
      ) : (
        <StatusDot tone={tone} label={label} />
      )}
      <span className="hidden font-mono text-[11px] sm:inline">route: <span className="text-fg">{data.planner.provider}/{data.planner.model}</span></span>
      <span className="ml-auto hidden md:inline">pipeline: {data.pipeline_mode}{data.pipeline_mode === "simulated" && " · deployments not confirmed"}</span>
    </div>
  );
}

function NavLinks({
  items,
  pathname,
  collapsed,
  onNavigate,
}: {
  items: NavItem[];
  pathname: string;
  collapsed: boolean;
  onNavigate?: () => void;
}) {
  const groups = ["Workspace", "Intelligence", "System"];
  return (
    <nav aria-label="Primary" className="flex flex-col gap-4">
      {groups.map((group) => (
        <div key={group} className="space-y-1">
          {!collapsed && (
            <p className="px-3 pb-1 text-[10px] font-bold uppercase tracking-[0.2em] text-accent/60">{group}</p>
          )}
          {items.filter((item) => item.group === group).map((item) => {
            const active = pathname === item.href || (item.href !== "/" && pathname.startsWith(item.href));
            return (
              <Link
                key={item.href}
                href={item.href}
                title={collapsed ? item.label : undefined}
                aria-current={active ? "page" : undefined}
                onClick={onNavigate}
                className={clsx(
                  "group flex min-h-touch items-center gap-3 rounded-md border px-3 text-body transition duration-150",
                  collapsed && "justify-center px-0",
                  active
                    ? "border-accent/25 bg-gradient-to-r from-accent/15 to-accent/5 font-semibold text-accent shadow-sm shadow-accent/5"
                    : "border-transparent text-fgmuted hover:border-edge/70 hover:bg-white/5 hover:text-fg",
                )}
              >
                <Icon path={item.icon} />
                {!collapsed && <span className="truncate">{item.label}</span>}
                {active && !collapsed && <span className="ml-auto h-1.5 w-1.5 rounded-full bg-accent" aria-hidden="true" />}
              </Link>
            );
          })}
        </div>
      ))}
    </nav>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { user, logout } = useAuth();
  const { settings, update } = usePreferences();
  const [mobileOpen, setMobileOpen] = useState(false);
  const collapsed = settings.sidebar_collapsed;
  const closeRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLButtonElement>(null);
  const items = NAV.filter((item) => !item.admin || user?.role === "admin");

  const closeMobile = useCallback(() => setMobileOpen(false), []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        closeMobile();
        return;
      }
      if (event.altKey && /^[1-9]$/.test(event.key) && items[Number(event.key) - 1]) {
        event.preventDefault();
        router.push(items[Number(event.key) - 1].href);
      }
      if (event.key === "[" && !event.altKey && !event.ctrlKey && !event.metaKey) {
        void update({ sidebar_collapsed: !collapsed });
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [closeMobile, collapsed, items, router, update]);

  useEffect(() => {
    if (mobileOpen) closeRef.current?.focus();
    else menuRef.current?.focus?.();
  }, [mobileOpen]);

  useEffect(() => {
    closeMobile();
  }, [pathname, closeMobile]);

  return (
    <ToastProvider>
      <div className="armx-root">
        <KillSwitchBanner />
        <div className="armx-frame">
          {/* Desktop sidebar */}
          <aside
            className={clsx(
              "hidden shrink-0 flex-col border-r border-edge/70 bg-surface/55 py-4 backdrop-blur-xl transition-[width] duration-200 lg:flex",
              collapsed ? "w-[72px] px-2" : "w-[260px] px-3",
            )}
          >
            <div className={clsx("mb-6 flex items-center gap-3 px-1", collapsed && "justify-center")}>
              <Link href="/" aria-label="A.R.M.X AI home" className="relative grid h-10 w-10 shrink-0 place-items-center rounded-lg border border-accent/40 bg-gradient-to-br from-accent to-emerald-500 font-black text-ink shadow-lg shadow-accent/20">
                A
                <span className="absolute -right-1 -top-1 h-2.5 w-2.5 rounded-full border-2 border-surface bg-accent" />
              </Link>
              {!collapsed && (
                <span className="min-w-0">
                  <span className="block truncate text-h3 font-bold tracking-tight">A.R.M.X AI</span>
                  <span className="block text-[9px] font-semibold uppercase tracking-[0.22em] text-accent/70">Control intelligence</span>
                </span>
              )}
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto">
              <NavLinks items={items} pathname={pathname} collapsed={collapsed} />
            </div>
            <div className="mt-3 space-y-2 border-t border-edge/70 pt-3">
              {!collapsed && user && (
                <div className="px-3">
                  <p className="truncate text-caption font-semibold text-fg">{user.display_name || user.email}</p>
                  <p className="truncate text-caption text-fgmuted">{user.role.toUpperCase()}</p>
                </div>
              )}
              <button
                type="button"
                onClick={() => void update({ sidebar_collapsed: !collapsed })}
                aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
                aria-pressed={collapsed}
                title="Toggle sidebar ([)"
                className={clsx("flex min-h-touch w-full items-center gap-3 rounded-md px-3 text-caption text-fgmuted transition hover:bg-white/5 hover:text-fg", collapsed && "justify-center px-0")}
              >
                <Icon path={ICONS.panel} />
                {!collapsed && "Collapse"}
              </button>
              <Button variant="ghost" size="sm" className={clsx("w-full", collapsed ? "justify-center px-0" : "justify-start")} onClick={logout}>
                {collapsed ? "↪" : "Sign out"}
              </Button>
            </div>
          </aside>

          <div className="armx-content">
            {/* Top bar */}
            <header className="flex flex-none items-center justify-between gap-3 border-b border-edge/70 bg-surface/55 px-3 py-2 backdrop-blur-xl sm:px-5">
              <div className="flex min-w-0 items-center gap-2">
                <button
                  ref={menuRef}
                  type="button"
                  onClick={() => setMobileOpen(true)}
                  aria-label="Open navigation"
                  aria-expanded={mobileOpen}
                  aria-controls="armx-mobile-nav"
                  className="grid h-9 w-9 place-items-center rounded-md border border-edge/70 text-fgmuted transition hover:bg-white/5 hover:text-fg lg:hidden"
                >
                  <Icon path={ICONS.menu} />
                </button>
                <Link href="/" className="flex items-center gap-2 lg:hidden">
                  <span className="grid h-8 w-8 place-items-center rounded-md bg-accent text-caption font-bold text-ink">A</span>
                  <span className="truncate text-body font-semibold">A.R.M.X AI</span>
                </Link>
                <span className="hidden truncate text-caption text-fgmuted lg:inline">
                  {items.find((item) => pathname === item.href || (item.href !== "/" && pathname.startsWith(item.href)))?.label ?? "Workspace"}
                </span>
              </div>
              <div className="flex items-center gap-2">
                {user?.role === "admin" && <Badge tone="accent">admin</Badge>}
                <ThemeToggle />
              </div>
            </header>

            <main id="armx-main" className="armx-main px-3 pb-6 pt-3 sm:px-4 md:px-6 xl:px-8">
              {children}
            </main>
          </div>
        </div>

        {/* Slide-in mobile navigation */}
        {mobileOpen && (
          <div className="fixed inset-0 z-[80] lg:hidden">
            <button type="button" aria-label="Close navigation" onClick={closeMobile} className="absolute inset-0 bg-black/65 backdrop-blur-sm" />
            <div id="armx-mobile-nav" role="dialog" aria-modal="true" aria-label="Navigation" className="animate-fade-up absolute inset-y-0 left-0 flex w-[86%] max-w-[320px] flex-col border-r border-edge bg-surface/95 px-3 py-4 shadow-2xl backdrop-blur-xl">
              <div className="mb-4 flex items-center justify-between gap-3 border-b border-edge/70 pb-3">
                <div className="flex items-center gap-2">
                  <span className="grid h-9 w-9 place-items-center rounded-md bg-accent font-bold text-ink">A</span>
                  <span className="text-body font-semibold">A.R.M.X AI</span>
                </div>
                <button ref={closeRef} type="button" onClick={closeMobile} aria-label="Close navigation" className="grid h-9 w-9 place-items-center rounded-md border border-edge text-fgmuted">
                  <Icon path={ICONS.close} />
                </button>
              </div>
              <div className="min-h-0 flex-1 overflow-y-auto">
                <NavLinks items={items} pathname={pathname} collapsed={false} onNavigate={closeMobile} />
              </div>
              <div className="mt-3 border-t border-edge/70 pt-3">
                <p className="px-3 text-caption text-fgmuted">Alt+1…9 jumps between sections · [ toggles the sidebar</p>
                <Button variant="ghost" size="sm" className="mt-2 w-full justify-start" onClick={logout}>Sign out</Button>
              </div>
            </div>
          </div>
        )}
      </div>
    </ToastProvider>
  );
}
