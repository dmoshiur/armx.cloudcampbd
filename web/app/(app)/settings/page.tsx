"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { useEffect, useState } from "react";
import { api, describeError, request } from "@/lib/api/client";
import { useAuth } from "@/lib/hooks/useAuth";
import { usePreferences } from "@/lib/preferences";
import type { Device, IntegrationStatus, MatrixStatus } from "@/lib/types";
import { Badge, Button, Card, CardHeader, ErrorState, Input, Label, PageHeader } from "@/components/ui/primitives";
import { Switch } from "@/components/ui/switch";
import { useToast } from "@/components/ui/toast";

interface SessionRow {
  id: string;
  created_at: string;
  expires_at: string;
  ip_address: string;
  user_agent: string;
  current: boolean;
}

interface Profile {
  id: string;
  channel: string;
  contact_id: string;
  display_name: string;
  personality: string;
  auto_send: boolean;
}

interface ModelOption {
  id: string;
  display_name: string;
  provider: string;
  provider_display_name: string;
  status: string;
  max_tokens: number;
}

interface EmailDeliveryRow {
  id: string;
  recipient: string;
  purpose: string;
  status: string;
  provider_message_id: string | null;
  attempts: number;
  request_id: string;
  last_error: string;
  created_at: string;
  delivered_at: string | null;
  failed_at: string | null;
}

interface ProviderHealth {
  email?: {
    configured: boolean;
    webhook_configured: boolean;
    base_url: string;
    status_counts: Record<string, number>;
    note: string;
  };
  checked_at?: string;
  integrations?: IntegrationStatus[];
}

const TABS = ["Appearance", "Matrix", "AI & Voice", "Account", "Integrations", "System"] as const;
type Tab = (typeof TABS)[number];

function TabButton({ active, label, onClick }: { active: boolean; label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={clsx(
        "min-h-touch shrink-0 rounded-md border px-3 text-caption font-semibold transition",
        active ? "border-accent/50 bg-accent/10 text-accent" : "border-edge bg-surface/60 text-fgmuted hover:text-fg",
      )}
    >
      {label}
    </button>
  );
}

function downloadJson(filename: string, data: unknown) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

export default function SettingsPage() {
  const { user, logout, refreshUser } = useAuth();
  const { settings, update, loading: preferencesLoading } = usePreferences();
  const toast = useToast();
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<Tab>("Appearance");
  const [displayName, setDisplayName] = useState(user?.display_name ?? "");
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [verificationEmail, setVerificationEmail] = useState(user?.email ?? "");
  const [newContact, setNewContact] = useState({ channel: "whatsapp", contact_id: "", display_name: "", personality: "", auto_send: false });
  const [cooldown, setCooldown] = useState(0);

  useEffect(() => {
    if (user) {
      setDisplayName(user.display_name);
      setVerificationEmail(user.email);
    }
  }, [user]);

  useEffect(() => {
    if (cooldown <= 0) return;
    const timer = window.setInterval(() => setCooldown((value) => Math.max(0, value - 1)), 1000);
    return () => window.clearInterval(timer);
  }, [cooldown]);

  const sessions = useQuery({ queryKey: ["sessions"], queryFn: () => api.get<SessionRow[]>("/auth/sessions") });
  const profiles = useQuery({ queryKey: ["profiles"], queryFn: () => api.get<Profile[]>("/messaging/profiles") });
  const devices = useQuery({ queryKey: ["devices"], queryFn: () => api.get<Device[]>("/devices") });
  const models = useQuery({ queryKey: ["models"], queryFn: () => api.get<{ items: ModelOption[] }>("/models") });
  const integrations = useQuery({ queryKey: ["integrations"], queryFn: () => api.get<{ integrations: IntegrationStatus[] }>("/integrations") });
  const providerHealth = useQuery({ queryKey: ["health", "providers"], queryFn: () => api.get<ProviderHealth>("/health/providers") });
  const verification = useQuery({
    queryKey: ["verification-status"],
    queryFn: () => api.get<{ email: string; is_verified: boolean; required: boolean }>("/auth/verification-status"),
    retry: false,
  });
  const matrixStatus = useQuery({
    queryKey: ["matrix", "status"],
    queryFn: () => request<MatrixStatus>("/matrix/status", { auth: false }),
    refetchInterval: 30_000,
  });
  const emailDeliveries = useQuery({
    queryKey: ["admin", "email-deliveries"],
    queryFn: () => api.get<{ items: EmailDeliveryRow[]; event_count: number }>("/admin/email-deliveries?limit=50"),
    enabled: user?.role === "admin",
    retry: false,
  });

  const mutateError = (err: unknown) => toast.push(describeError(err, "save this change"), "error");

  const saveName = useMutation({
    mutationFn: () => api.patch("/auth/me", { display_name: displayName }),
    onSuccess: async () => {
      await refreshUser();
      toast.push("Profile updated.", "success");
    },
    onError: mutateError,
  });

  const changePassword = useMutation({
    mutationFn: () =>
      api.post("/auth/change-password", {
        current_password: currentPassword,
        new_password: newPassword,
      }),
    onSuccess: async () => {
      toast.push("Password changed. All sessions were revoked; sign in again.", "success");
      await logout();
    },
    onError: mutateError,
  });

  const logoutAll = useMutation({
    mutationFn: () => api.post("/auth/logout-all", {}),
    onSuccess: async () => {
      toast.push("Signed out of every device.", "success");
      await logout();
    },
    onError: mutateError,
  });

  const revokeSession = useMutation({
    mutationFn: (id: string) => api.del(`/auth/sessions/${id}`),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["sessions"] }),
    onError: mutateError,
  });

  const resendVerification = useMutation({
    mutationFn: () => api.post<{ message: string }>("/auth/resend-verification", { email: verificationEmail }),
    onSuccess: (result) => {
      setCooldown(60);
      toast.push(result.message, "success");
    },
    onError: mutateError,
  });

  const addProfile = useMutation({
    mutationFn: () => api.post("/messaging/profiles", newContact),
    onSuccess: () => {
      toast.push("Contact saved.", "success");
      setNewContact({ channel: "whatsapp", contact_id: "", display_name: "", personality: "", auto_send: false });
      void queryClient.invalidateQueries({ queryKey: ["profiles"] });
    },
    onError: mutateError,
  });

  const removeProfile = useMutation({
    mutationFn: (id: string) => api.del(`/messaging/profiles/${id}`),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["profiles"] }),
    onError: mutateError,
  });

  const configureMatrix = useMutation({
    mutationFn: () => api.post<MatrixStatus>("/matrix/configure", { speed: settings.matrix.speed, density: settings.matrix.density }),
    onSuccess: (result) => {
      void queryClient.invalidateQueries({ queryKey: ["matrix", "status"] });
      toast.push(result.running ? "Original CMatrix PTY updated." : result.reason || "CMatrix configuration returned an honest unavailable status.", result.running ? "success" : "info");
    },
    onError: mutateError,
  });

  const exportData = useMutation({
    mutationFn: async () => {
      const conversations = await api.get<{ items: unknown[]; total: number }>("/assistant/conversations?limit=100&include_archived=true");
      downloadJson("armx-conversations.json", conversations);
      return conversations.total;
    },
    onSuccess: (total) => toast.push(`Exported ${total} conversation records. Message bodies can be exported per conversation from the Assistant.`, "success"),
    onError: mutateError,
  });

  const matrix = settings.matrix;

  return (
    <div className="space-y-5 pb-10">
      <PageHeader
        title="Settings"
        description="Preferences are stored in the database; appearance, Matrix, model, voice and account controls are persisted server-side."
        action={<Badge tone={preferencesLoading ? "warning" : "success"}>{preferencesLoading ? "syncing…" : "preferences saved"}</Badge>}
      />

      <div className="flex gap-2 overflow-x-auto pb-1" role="tablist" aria-label="Settings sections">
        {TABS.map((item) => (
          <TabButton key={item} label={item} active={tab === item} onClick={() => setTab(item)} />
        ))}
      </div>

      {tab === "Appearance" && (
        <div className="grid gap-5 lg:grid-cols-2">
          <Card>
            <CardHeader title="Appearance" description="Theme and layout are saved to your account, not just this browser." />
            <div className="space-y-5 p-5">
              <Switch
                label="Dark theme"
                description="Deep-black emerald interface. Light mode keeps the same layout with high contrast."
                checked={settings.theme === "dark"}
                onChange={(next) => void update({ theme: next ? "dark" : "light" })}
              />
              <Switch
                label="Collapsed sidebar"
                description="Compact desktop navigation. Mobile uses a slide-in drawer."
                checked={settings.sidebar_collapsed}
                onChange={(next) => void update({ sidebar_collapsed: next })}
              />
              <Switch
                label="Notifications"
                description="Allow user-visible status notifications for long-running work."
                checked={settings.notifications}
                onChange={(next) => void update({ notifications: next })}
              />
              <Switch
                label="Save explicit instructions"
                description="When on, explicitly saved instructions may become long-term memory. Chat messages are never automatically permanent."
                checked={settings.privacy.save_explicit_instructions}
                onChange={(next) => void update({ privacy: { save_explicit_instructions: next } })}
              />
            </div>
          </Card>
          <Card>
            <CardHeader title="Data export" description="Export conversation metadata as JSON. Individual conversations can be exported as Markdown from the Assistant." />
            <div className="space-y-4 p-5">
              <p className="text-body text-fgmuted">Your durable data lives in the application database. Export is generated from the server response; no secret or API key is included.</p>
              <Button variant="secondary" onClick={() => exportData.mutate()} loading={exportData.isPending}>Export conversation index</Button>
              <Button variant="ghost" onClick={() => void logout()}>Sign out of this device</Button>
            </div>
          </Card>
        </div>
      )}

      {tab === "Matrix" && (
        <div className="grid gap-5 lg:grid-cols-2">
          <Card>
            <CardHeader title="Matrix background" description="Authentic terminal rain with an honest capability status." />
            <div className="space-y-5 p-5">
              {matrixStatus.isLoading && <p className="text-caption text-fgmuted">Checking CMatrix capability…</p>}
              {matrixStatus.data && (
                <div className="rounded-lg border border-edge bg-bg/50 p-3 text-caption">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge tone={matrixStatus.data.available ? "success" : "warning"}>{matrixStatus.data.available ? "executable available" : "executable unavailable"}</Badge>
                    <Badge tone={matrixStatus.data.running ? "success" : "neutral"}>{matrixStatus.data.running ? "PTY running" : "not running"}</Badge>
                    <span className="font-mono text-fgmuted">{matrixStatus.data.license?.license || "GPL-3.0"}</span>
                  </div>
                  <p className="mt-2 text-fgmuted">{matrixStatus.data.reason || "Capability check completed."}</p>
                  <p className="mt-1 text-fgmuted">Binary: <span className="font-mono">{matrixStatus.data.binary || "not found"}</span> · FPS: {matrixStatus.data.fps} · subscribers: {matrixStatus.data.subscribers}</p>
                </div>
              )}
              <Switch label="Enable Matrix background" description="Full-screen, low-intensity rain behind content." checked={matrix.enabled} onChange={(next) => void update({ matrix: { enabled: next } })} />
              <Switch label="Respect reduced motion" description="Pause animation and show a static grid when the OS requests reduced motion." checked={matrix.respect_reduced_motion} onChange={(next) => void update({ matrix: { respect_reduced_motion: next } })} />
              <div>
                <Label htmlFor="matrix-speed">Speed · {matrix.speed}/10</Label>
                <input id="matrix-speed" type="range" min={1} max={10} value={matrix.speed} onChange={(e) => void update({ matrix: { speed: Number(e.target.value) } })} className="w-full accent-accent" />
              </div>
              <div>
                <Label htmlFor="matrix-density">Density · {matrix.density}/10</Label>
                <input id="matrix-density" type="range" min={1} max={10} value={matrix.density} onChange={(e) => void update({ matrix: { density: Number(e.target.value) } })} className="w-full accent-accent" />
              </div>
              <div>
                <Label htmlFor="matrix-opacity">Opacity · {Math.round(matrix.opacity * 100)}%</Label>
                <input id="matrix-opacity" type="range" min={0} max={0.6} step={0.02} value={matrix.opacity} onChange={(e) => void update({ matrix: { opacity: Number(e.target.value) } })} className="w-full accent-accent" />
              </div>
              <div>
                <Label htmlFor="matrix-renderer">Renderer</Label>
                <select id="matrix-renderer" value={matrix.renderer} onChange={(e) => void update({ matrix: { renderer: e.target.value as "auto" | "pty" | "port" } })} className="h-10 w-full rounded-md border border-edge bg-bg px-3 text-caption text-fg">
                  <option value="auto">Auto — original PTY, then MIT JS port</option>
                  <option value="pty">Original CMatrix PTY only</option>
                  <option value="port">MIT JavaScript port only</option>
                </select>
              </div>
            </div>
          </Card>
          <Card>
            <CardHeader title="Process control" description="Operator-level PTY speed/density requires server-side admin authorization." />
            <div className="space-y-4 p-5">
              <p className="text-body text-fgmuted">
                Preference sliders are saved per user. The backend process itself is shared and can only be reconfigured by an admin. If the original executable is unavailable, the UI honestly labels the MIT JavaScript port fallback; it never claims the binary ran.
              </p>
              {user?.role === "admin" ? (
                <Button variant="secondary" onClick={() => configureMatrix.mutate()} loading={configureMatrix.isPending}>Apply speed/density to PTY</Button>
              ) : (
                <Badge tone="warning">Admin required for shared PTY control</Badge>
              )}
              <p className="text-caption text-fgmuted">
                Reduced motion, hidden-tab pausing and frame skipping keep CPU use bounded. The canvas is pointer-events:none and never blocks clicks.
              </p>
            </div>
          </Card>
        </div>
      )}

      {tab === "AI & Voice" && (
        <div className="grid gap-5 lg:grid-cols-2">
          <Card>
            <CardHeader title="Assistant behaviour" description="Model selection, streaming and memory controls." />
            <div className="space-y-5 p-5">
              <div>
                <Label htmlFor="default-model">Default model</Label>
                <select id="default-model" value={settings.default_model} onChange={(e) => void update({ default_model: e.target.value })} className="h-10 w-full rounded-md border border-edge bg-bg px-3 text-caption text-fg">
                  <option value="">Auto route (weighted DB routing)</option>
                  {(models.data?.items || []).map((option) => (
                    <option key={`${option.provider}-${option.id}`} value={option.id}>{option.provider_display_name} / {option.display_name} · {option.status}</option>
                  ))}
                </select>
                <p className="mt-1 text-caption text-fgmuted">The exact per-turn provider/model is shown in chat. Routes never silently switch without a visible fallback reason.</p>
              </div>
              <Switch label="Streaming responses" description="Real provider deltas over authenticated SSE with stop control." checked={settings.streaming} onChange={(next) => void update({ streaming: next })} />
              <Switch label="Voice input" description="Microphone starts only after an explicit button press and shows a recording indicator." checked={settings.voice_enabled} onChange={(next) => void update({ voice_enabled: next })} />
              <Switch label="Long-term memory" description="Ranked, deduplicated memory is separate from conversation history." checked={settings.memory_enabled} onChange={(next) => void update({ memory_enabled: next })} />
            </div>
          </Card>
          <Card>
            <CardHeader title="Provider health" description="Server-side status. No API key is exposed to this page." />
            <div className="space-y-3 p-5">
              {providerHealth.isError && <ErrorState message={providerHealth.error.message} onRetry={() => void providerHealth.refetch()} />}
              {providerHealth.data?.email && (
                <div className="rounded-lg border border-edge bg-bg/50 p-3 text-caption">
                  <p className="font-semibold text-fg">Email · Resend REST</p>
                  <p className="mt-1 text-fgmuted">configured: {String(providerHealth.data.email.configured)} · webhook: {String(providerHealth.data.email.webhook_configured)}</p>
                  <p className="mt-1 break-all text-fgmuted">base URL: {providerHealth.data.email.base_url}</p>
                  <p className="mt-1 text-fgmuted">{providerHealth.data.email.note}</p>
                </div>
              )}
              <p className="text-body text-fgmuted">Provider credentials are encrypted server-side and managed in Admin → Models. Model health checks, retries, rate-limit classification and request logs are visible in Activity Logs.</p>
              <a href="/admin" className="inline-flex text-caption text-accent hover:underline">Open Admin Console →</a>
            </div>
          </Card>
        </div>
      )}

      {tab === "Account" && (
        <div className="grid gap-5 lg:grid-cols-2">
          <Card>
            <CardHeader title="Profile & verification" description={user ? `${user.email} · ${user.role.toUpperCase()}` : ""} />
            <div className="space-y-4 p-5">
              <div>
                <Label htmlFor="display-name">Display name</Label>
                <Input id="display-name" value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
              </div>
              <Button onClick={() => saveName.mutate()} loading={saveName.isPending}>Save profile</Button>
              <div className="rounded-lg border border-edge bg-bg/50 p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone={user?.is_verified ? "success" : "warning"}>{user?.is_verified ? "email verified" : "email not verified"}</Badge>
                  {verification.data && <Badge tone={verification.data.required ? "danger" : "neutral"}>{verification.data.required ? "required by policy" : "optional by current policy"}</Badge>}
                </div>
                <p className="mt-2 text-caption text-fgmuted">New accounts never receive admin privileges. Verification links are single-use, expire after 24 hours, and use a 60-second resend cooldown.</p>
                <div className="mt-3 flex gap-2">
                  <Input value={verificationEmail} onChange={(e) => setVerificationEmail(e.target.value)} aria-label="Verification email" />
                  <Button variant="secondary" onClick={() => resendVerification.mutate()} loading={resendVerification.isPending} disabled={cooldown > 0}>
                    {cooldown > 0 ? `${cooldown}s` : "Resend"}
                  </Button>
                </div>
              </div>
            </div>
          </Card>
          <Card>
            <CardHeader title="Password & sessions" description="HttpOnly SameSite cookies, rotating refresh tokens and server-side revocation." />
            <div className="space-y-4 p-5">
              <div>
                <Label htmlFor="current-password">Current password</Label>
                <Input id="current-password" type="password" autoComplete="current-password" value={currentPassword} onChange={(e) => setCurrentPassword(e.target.value)} />
              </div>
              <div>
                <Label htmlFor="new-password">New password</Label>
                <Input id="new-password" type="password" autoComplete="new-password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} />
              </div>
              <div>
                <Label htmlFor="confirm-password">Confirm new password</Label>
                <Input id="confirm-password" type="password" autoComplete="new-password" value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} />
              </div>
              {confirmPassword && confirmPassword !== newPassword && <p className="text-caption text-danger">Passwords do not match.</p>}
              <div className="flex flex-wrap gap-2">
                <Button
                  variant="danger"
                  disabled={!currentPassword || !newPassword || newPassword !== confirmPassword}
                  onClick={() => changePassword.mutate()}
                  loading={changePassword.isPending}
                >
                  Change password
                </Button>
                <Button variant="ghost" onClick={() => logoutAll.mutate()} loading={logoutAll.isPending}>Sign out everywhere</Button>
              </div>
              <div className="rounded-lg border border-edge bg-bg/50 p-3">
                <p className="mb-2 text-caption font-semibold text-fg">Active sessions ({sessions.data?.length ?? 0})</p>
                {sessions.isError && <ErrorState message={sessions.error.message} onRetry={() => void sessions.refetch()} />}
                <ul className="space-y-2">
                  {(sessions.data || []).map((session) => (
                    <li key={session.id} className="flex flex-wrap items-center gap-2 text-caption text-fgmuted">
                      {session.current && <Badge tone="accent">this device</Badge>}
                      <span className="font-mono">{session.ip_address || "unknown IP"}</span>
                      <span className="truncate">{session.user_agent || "unknown browser"}</span>
                      <button type="button" onClick={() => revokeSession.mutate(session.id)} className="ml-auto text-danger hover:underline">Revoke</button>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          </Card>
        </div>
      )}

      {tab === "Integrations" && (
        <div className="grid gap-5 lg:grid-cols-2">
          <Card>
            <CardHeader title="Integration status" description="Honest configuration state. No secrets are editable from the browser." />
            <div className="space-y-2 p-5">
              {integrations.isError && <ErrorState message={integrations.error.message} onRetry={() => void integrations.refetch()} />}
              {(integrations.data?.integrations || []).map((item) => (
                <div key={item.provider} className="flex flex-wrap items-center gap-2 rounded-md border border-edge bg-bg/40 p-2.5 text-caption">
                  <Badge tone={item.configured ? "success" : "warning"}>{item.configured ? "configured" : "not configured"}</Badge>
                  <span className="font-mono text-fg">{item.provider}</span>
                  <span className="text-fgmuted">{item.mode}</span>
                  {item.simulated && <Badge tone="warning">simulated</Badge>}
                  <p className="w-full text-fgmuted">{item.detail}</p>
                </div>
              ))}
              <p className="pt-2 text-caption text-fgmuted">Registered devices: {devices.data?.length ?? 0}. Device automation and health are available in the Devices section.</p>
            </div>
          </Card>
          <Card>
            <CardHeader title="Messaging contacts" description="Explicit outbound messaging profiles. No hidden background sending." />
            <div className="space-y-3 p-5">
              {profiles.isError && <ErrorState message={profiles.error.message} onRetry={() => void profiles.refetch()} />}
              {(profiles.data || []).map((profile) => (
                <div key={profile.id} className="flex flex-wrap items-center gap-2 rounded-md border border-edge bg-bg/40 p-2.5 text-caption">
                  <Badge tone="accent">{profile.channel}</Badge>
                  <span className="font-mono text-fg">{profile.contact_id}</span>
                  <span className="text-fgmuted">{profile.display_name || "unnamed"}</span>
                  <button type="button" onClick={() => removeProfile.mutate(profile.id)} className="ml-auto text-danger hover:underline">Remove</button>
                </div>
              ))}
              <div className="grid gap-2 sm:grid-cols-2">
                <Input placeholder="contact id" value={newContact.contact_id} onChange={(e) => setNewContact({ ...newContact, contact_id: e.target.value })} />
                <Input placeholder="display name" value={newContact.display_name} onChange={(e) => setNewContact({ ...newContact, display_name: e.target.value })} />
              </div>
              <Button variant="secondary" onClick={() => addProfile.mutate()} loading={addProfile.isPending}>Add contact</Button>
            </div>
          </Card>
        </div>
      )}

      {tab === "System" && (
        <div className="grid gap-5 lg:grid-cols-2">
          <Card>
            <CardHeader title="Email delivery health" description="Resend request acceptance is distinct from confirmed delivery." />
            <div className="space-y-3 p-5">
              {providerHealth.data?.email ? (
                <>
                  <div className="flex flex-wrap gap-2">
                    <Badge tone={providerHealth.data.email.configured ? "success" : "danger"}>{providerHealth.data.email.configured ? "Resend configured" : "Resend not configured"}</Badge>
                    <Badge tone={providerHealth.data.email.webhook_configured ? "success" : "warning"}>{providerHealth.data.email.webhook_configured ? "webhooks verified" : "webhooks not configured"}</Badge>
                  </div>
                  <pre className="overflow-x-auto rounded-md border border-edge bg-bg/60 p-3 text-[11px] text-fgmuted">{JSON.stringify(providerHealth.data.email.status_counts, null, 2)}</pre>
                  <p className="text-caption text-fgmuted">{providerHealth.data.email.note}</p>
                </>
              ) : (
                <p className="text-caption text-fgmuted">Loading provider health…</p>
              )}
              <p className="text-caption text-fgmuted">Setup guide: <code>docs/RESEND_SETUP.md</code>. Required server-side variables: <code>RESEND_API_KEY</code>, <code>RESEND_FROM_EMAIL</code>, <code>APP_BASE_URL</code>.</p>
            </div>
          </Card>
          <Card>
            <CardHeader title="Delivery ledger" description="Server-authorised view. Only shown to admins." />
            <div className="space-y-2 p-5">
              {user?.role !== "admin" && <Badge tone="warning">Admin authorization required</Badge>}
              {user?.role === "admin" && emailDeliveries.isError && <ErrorState message={emailDeliveries.error.message} onRetry={() => void emailDeliveries.refetch()} />}
              {user?.role === "admin" && (emailDeliveries.data?.items || []).slice(0, 12).map((row) => (
                <div key={row.id} className="rounded-md border border-edge bg-bg/40 p-2.5 text-caption">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge tone={row.status === "delivered" ? "success" : row.status === "failed" || row.status === "bounced" ? "danger" : "warning"}>{row.status}</Badge>
                    <span className="font-mono text-fg">{row.purpose}</span>
                    <span className="text-fgmuted">{row.recipient}</span>
                    <span className="ml-auto font-mono text-fgmuted">{row.request_id || "no id"}</span>
                  </div>
                  {row.last_error && <p className="mt-1 text-danger">{row.last_error}</p>}
                </div>
              ))}
              {user?.role === "admin" && emailDeliveries.data && <p className="text-caption text-fgmuted">Signed provider events recorded: {emailDeliveries.data.event_count}</p>}
            </div>
          </Card>
        </div>
      )}
    </div>
  );
}
