"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, ApiError } from "@/lib/api/client";
import { useAuth } from "@/lib/hooks/useAuth";
import type { AdminOverview, AuditEntry, ToolInfo } from "@/lib/types";
import {Badge, Button, Card, CardHeader, EmptyState, ErrorState, Input, LoadingBlock, PageHeader, RiskBadge, StatusDot} from "@/components/ui/primitives";
import { Switch } from "@/components/ui/switch";
import { ConfirmActionDialog } from "@/components/ui/dialog";
import { useToast } from "@/components/ui/toast";

interface AdminUser {
  id: string;
  email: string;
  display_name: string;
  role: string;
  is_active: boolean;
  is_verified: boolean;
  created_at: string;
  last_login_at: string | null;
  locked: boolean;
}

interface AdminDevice {
  id: string;
  name: string;
  platform: string;
  status: string;
  owner_email: string;
  capabilities: string[];
  last_seen_at: string | null;
}

const TABS = ["Overview", "Users", "Tools", "Audit", "Devices"] as const;
type Tab = (typeof TABS)[number];

export default function AdminPage() {
  const { user } = useAuth();
  const toast = useToast();
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<Tab>("Overview");
  const [search, setSearch] = useState("");
  const [killDialog, setKillDialog] = useState(false);

  const overview = useQuery({ queryKey: ["admin", "overview"], queryFn: () => api.get<AdminOverview>("/admin/overview") });
  const users = useQuery({
    queryKey: ["admin", "users", search],
    queryFn: () => api.get<{ total: number; items: AdminUser[] }>(`/admin/users?q=${encodeURIComponent(search)}`),
    enabled: tab === "Users",
  });
  const tools = useQuery({ queryKey: ["admin", "tools"], queryFn: () => api.get<ToolInfo[]>("/admin/tools"), enabled: tab === "Tools" });
  const audit = useQuery({
    queryKey: ["admin", "audit"],
    queryFn: () => api.get<{ total: number; items: AuditEntry[] }>("/admin/audit?limit=80"),
    enabled: tab === "Audit",
  });
  const devices = useQuery({ queryKey: ["admin", "devices"], queryFn: () => api.get<AdminDevice[]>("/admin/devices"), enabled: tab === "Devices" });
  const chain = useQuery({
    queryKey: ["admin", "chain"],
    queryFn: () => api.get<{ ok: boolean; checked: number; broken_at?: number }>("/admin/audit/verify"),
    enabled: tab === "Audit",
  });

  const setRole = useMutation({
    mutationFn: ({ id, role }: { id: string; role: string }) => api.patch(`/admin/users/${id}`, { role }),
    onSuccess: () => {
      toast.push("Role updated", "success");
      void queryClient.invalidateQueries({ queryKey: ["admin"] });
    },
    onError: (error) => toast.push(error instanceof ApiError ? error.message : "Update failed", "error"),
  });

  const setActive = useMutation({
    mutationFn: ({ id, is_active }: { id: string; is_active: boolean }) => api.patch(`/admin/users/${id}`, { is_active }),
    onSuccess: () => {
      toast.push("Account updated", "success");
      void queryClient.invalidateQueries({ queryKey: ["admin"] });
    },
    onError: (error) => toast.push(error instanceof ApiError ? error.message : "Update failed", "error"),
  });

  const toggleTool = useMutation({
    mutationFn: ({ name, enabled }: { name: string; enabled: boolean }) => api.patch("/admin/tools", { name, enabled }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["admin", "tools"] });
      void queryClient.invalidateQueries({ queryKey: ["tools"] });
    },
    onError: (error) => toast.push(error instanceof ApiError ? error.message : "Toggle failed", "error"),
  });

  const killSwitch = useMutation({
    mutationFn: (engaged: boolean) => api.post("/admin/kill-switch", { engaged }),
    onSuccess: (_data, engaged) => {
      toast.push(engaged ? "Kill-switch engaged: every tool is halted." : "Kill-switch released.", engaged ? "error" : "success");
      setKillDialog(false);
      void queryClient.invalidateQueries({ queryKey: ["admin"] });
      void queryClient.invalidateQueries({ queryKey: ["health"] });
    },
  });

  if (user?.role !== "admin") {
    return <ErrorState title="Administrator only" message="This area is restricted to the platform administrator." />;
  }

  return (
    <div>
      <PageHeader
        title="Administration"
        description="Users, tool toggles, the audit trail and the kill-switch. Device control stays read-only here: only the device owner can unlink."
        action={
          <Button
            variant={overview.data?.kill_switch === "on" ? "primary" : "danger"}
            onClick={() => setKillDialog(true)}
          >
            {overview.data?.kill_switch === "on" ? "Release kill-switch" : "Engage kill-switch"}
          </Button>
        }
      />

      <div role="tablist" aria-label="Admin sections" className="mb-5 flex flex-wrap gap-1 border-b border-edge">
        {TABS.map((item) => (
          <button
            key={item}
            role="tab"
            aria-selected={tab === item}
            onClick={() => setTab(item)}
            className={`min-h-touch rounded-t-md px-4 text-body transition ${
              tab === item ? "border-b-2 border-accent font-semibold text-accent" : "text-fgmuted hover:text-fg"
            }`}
          >
            {item}
          </button>
        ))}
      </div>

      {tab === "Overview" && (
        <>
          {overview.isLoading && <LoadingBlock />}
          {overview.isError && <ErrorState message={overview.error.message} onRetry={() => void overview.refetch()} />}
          {overview.data && (
            <>
              <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
                {[
                  ["Users", overview.data.users, `${overview.data.active_users} active`],
                  ["Sessions", overview.data.active_sessions, "live refresh sessions"],
                  ["Linked devices", overview.data.linked_devices, `${overview.data.devices} total`],
                  ["Projects", overview.data.generated_projects, "generated sites"],
                  ["Audit events", overview.data.audit_events, "hash-chained"],
                  ["Pending approvals", overview.data.pending_approvals, "awaiting humans"],
                  ["Tools", overview.data.tools.total, "registered"],
                  ["Kill-switch", overview.data.kill_switch.toUpperCase(), "global"],
                ].map(([label, value, hint]) => (
                  <Card key={String(label)} className="p-4">
                    <p className="text-caption text-fgmuted">{label}</p>
                    <p className="mt-1 text-h2">{String(value)}</p>
                    <p className="text-caption text-fgmuted">{hint}</p>
                  </Card>
                ))}
              </div>
              <Card className="mt-5">
                <CardHeader title="Safety posture" description="What is enforced right now." />
                <ul className="space-y-2 p-5 text-body text-fgmuted">
                  <li className="flex gap-2">
                    <StatusDot tone={overview.data.kill_switch === "off" ? "success" : "danger"} label={`Kill-switch ${overview.data.kill_switch}`} />
                  </li>
                  <li>Every medium/high tool is bound to a single-use approval hash (tool + args + actor + session + expiry).</li>
                  <li>Deploy destinations are allowlisted per user; the model cannot invent a repo or project.</li>
                  <li>Admins can view linked devices but cannot unlink them — that needs the device owner’s password.</li>
                  <li>The audit log is append-only and hash-chained; tampering breaks verification.</li>
                </ul>
              </Card>
            </>
          )}
        </>
      )}

      {tab === "Users" && (
        <Card>
          <CardHeader
            title="Users"
            description="Promote to VIP for device linking. Admins cannot demote themselves."
            action={
              <div className="w-full sm:w-64">
                <label htmlFor="user-search" className="sr-only">
                  Search users
                </label>
                <Input id="user-search" placeholder="Search by email" value={search} onChange={(e) => setSearch(e.target.value)} />
              </div>
            }
          />
          {users.isLoading && (
            <div className="p-5">
              <LoadingBlock />
            </div>
          )}
          {users.data && users.data.items.length === 0 && <div className="p-5"><EmptyState title="No users found" /></div>}
          <div className="divide-y divide-edge">
            {users.data?.items.map((row) => (
              <div key={row.id} className="flex flex-wrap items-center gap-3 px-4 py-3">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-body">{row.display_name || row.email}</p>
                  <p className="truncate text-caption text-fgmuted">
                    {row.email} · joined {new Date(row.created_at).toLocaleDateString()}
                    {row.locked && " · locked"}
                  </p>
                </div>
                <Badge tone={row.role === "admin" ? "accent" : row.role === "vip" ? "success" : "neutral"}>{row.role}</Badge>
                <Badge tone={row.is_active ? "success" : "danger"}>{row.is_active ? "active" : "disabled"}</Badge>
                <select
                  aria-label={`Role for ${row.email}`}
                  value={row.role}
                  onChange={(e) => setRole.mutate({ id: row.id, role: e.target.value })}
                  className="min-h-[40px] rounded-md border border-edge bg-bg px-2 text-caption"
                >
                  <option value="user">user</option>
                  <option value="vip">vip</option>
                  <option value="admin">admin</option>
                </select>
                <Button
                  size="sm"
                  variant={row.is_active ? "danger" : "secondary"}
                  onClick={() => setActive.mutate({ id: row.id, is_active: !row.is_active })}
                >
                  {row.is_active ? "Disable" : "Enable"}
                </Button>
              </div>
            ))}
          </div>
        </Card>
      )}

      {tab === "Tools" && (
        <div className="space-y-3">
          {tools.isLoading && <LoadingBlock />}
          {tools.data?.map((tool) => (
            <Card key={tool.name} className="p-4">
              <div className="flex flex-wrap items-center gap-2">
                <code className="font-mono text-caption text-accent">{tool.name}</code>
                <RiskBadge risk={tool.risk} />
                <Badge>{tool.category}</Badge>
                <span className="ml-auto w-full sm:w-56">
                  <Switch
                    checked={(tool as unknown as { enabled_global?: boolean }).enabled_global ?? tool.enabled}
                    onChange={(next) => toggleTool.mutate({ name: tool.name, enabled: next })}
                    label={tool.enabled ? "Enabled" : "Disabled"}
                  />
                </span>
              </div>
              <p className="mt-2 text-caption text-fgmuted">{tool.description}</p>
            </Card>
          ))}
        </div>
      )}

      {tab === "Audit" && (
        <Card>
          <CardHeader
            title="Audit trail"
            description="Append-only and hash-chained. Editing a row breaks verification."
            action={
              chain.data && (
                <Badge tone={chain.data.ok ? "success" : "danger"}>
                  {chain.data.ok ? `chain verified · ${chain.data.checked} entries` : `broken at #${chain.data.broken_at}`}
                </Badge>
              )
            }
          />
          {audit.isLoading && (
            <div className="p-5">
              <LoadingBlock />
            </div>
          )}
          <div className="divide-y divide-edge">
            {audit.data?.items.map((entry) => (
              <div key={entry.id} className="px-4 py-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-caption text-accent">{entry.action}</span>
                  {entry.tool && <code className="text-caption text-fgmuted">{entry.tool}</code>}
                  {entry.risk && <RiskBadge risk={entry.risk} />}
                  <Badge tone={entry.status === "ok" ? "success" : entry.status === "denied" ? "danger" : "neutral"}>
                    {entry.status}
                  </Badge>
                  <span className="ml-auto text-caption text-fgmuted">{new Date(entry.ts).toLocaleString()}</span>
                </div>
                <p className="mt-1 text-caption text-fgmuted">
                  {entry.actor_email || "system"} · {entry.ip_address || "no ip"} ·{" "}
                  <span className="font-mono">{entry.entry_hash.slice(0, 12)}…</span>
                </p>
              </div>
            ))}
          </div>
        </Card>
      )}

      {tab === "Devices" && (
        <Card>
          <CardHeader title="All linked devices" description="Read-only. Admins cannot unlink or command another account’s device." />
          <div className="divide-y divide-edge">
            {devices.data?.length === 0 && <p className="px-4 py-4 text-caption text-fgmuted">No devices linked.</p>}
            {devices.data?.map((device) => (
              <div key={device.id} className="flex flex-wrap items-center gap-2 px-4 py-3">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-body">{device.name}</p>
                  <p className="truncate text-caption text-fgmuted">
                    {device.owner_email} · {device.platform} · {device.capabilities.join(", ")}
                  </p>
                </div>
                <Badge tone={device.status === "active" ? "success" : "neutral"}>{device.status}</Badge>
                <Badge>read-only</Badge>
              </div>
            ))}
          </div>
        </Card>
      )}

      <ConfirmActionDialog
        open={killDialog}
        onCancel={() => setKillDialog(false)}
        onConfirm={() => killSwitch.mutate(overview.data?.kill_switch !== "on")}
        busy={killSwitch.isPending}
        tool="kill_switch"
        risk="high"
        title={overview.data?.kill_switch === "on" ? "Release the kill-switch?" : "Engage the kill-switch?"}
        consequences={
          overview.data?.kill_switch === "on"
            ? ["Tools and integrations become available again immediately."]
            : [
                "Every integration and tool call halts instantly, independent of the AI.",
                "Only read-only health checks keep working.",
                "Pending approvals stay pending but cannot execute.",
              ]
        }
        confirmLabel={overview.data?.kill_switch === "on" ? "Release" : "Engage"}
      />
    </div>
  );
}
