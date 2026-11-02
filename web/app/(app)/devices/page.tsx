"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "@/lib/api/client";
import { useAuth } from "@/lib/hooks/useAuth";
import type { Device } from "@/lib/types";
import {
  Badge,
  Button,
  Card,
  CardHeader,
  EmptyState,
  ErrorState,
  Input,
  Label,
  LoadingBlock,
  PageHeader,
} from "@/components/ui/primitives";
import { Dialog } from "@/components/ui/dialog";
import { Switch } from "@/components/ui/switch";
import { useToast } from "@/components/ui/toast";

type ScreenShareStatus = {
  active: boolean;
  status: "inactive" | "requested" | "active";
  session_id: string | null;
  requested_at: string | null;
  consented_at: string | null;
  visible_indicator: boolean;
};

type ManagedPolicy = {
  configured: boolean;
  policy_version: number;
  kiosk_enabled: boolean;
  launcher_enabled: boolean;
  usage_telemetry_enabled: boolean;
  allowed_packages: string[];
  restrictions: string[];
  last_applied_version: number;
  last_applied_at: string | null;
  last_error: string;
  pending_local_approval?: boolean;
};

type UsageReport = {
  permission_scoped: boolean;
  content_captured: false;
  items: Array<{
    package_name: string;
    foreground_seconds: number;
    launches: number;
    window_start: string;
    window_end: string;
  }>;
};

const RESTRICTIONS = [
  ["no_add_users", "Block adding users"],
  ["no_unknown_sources", "Block unknown app sources"],
  ["no_safe_boot", "Block safe boot"],
] as const;

function ManagedDevicePanel({ device }: { device: Device }) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const policy = useQuery({
    queryKey: ["managed-policy", device.id],
    queryFn: () => api.get<ManagedPolicy>(`/devices/${device.id}/management/policy`),
  });
  const usage = useQuery({
    queryKey: ["managed-usage", device.id],
    queryFn: () => api.get<UsageReport>(`/devices/${device.id}/management/usage?days=7`),
  });
  const [kiosk, setKiosk] = useState(false);
  const [launcher, setLauncher] = useState(false);
  const [telemetry, setTelemetry] = useState(false);
  const [packages, setPackages] = useState("ai.armx.managed");
  const [restrictions, setRestrictions] = useState<string[]>([]);
  const [loadedVersion, setLoadedVersion] = useState<number | null>(null);

  useEffect(() => {
    const value = policy.data;
    if (!value || loadedVersion === value.policy_version) return;
    setKiosk(value.kiosk_enabled);
    setLauncher(value.launcher_enabled);
    setTelemetry(value.usage_telemetry_enabled);
    setPackages(value.allowed_packages.join("\n"));
    setRestrictions(value.restrictions);
    setLoadedVersion(value.policy_version);
  }, [loadedVersion, policy.data]);

  const save = useMutation({
    mutationFn: () =>
      api.put<ManagedPolicy>(`/devices/${device.id}/management/policy`, {
        kiosk_enabled: kiosk,
        launcher_enabled: launcher,
        usage_telemetry_enabled: telemetry,
        allowed_packages: packages
          .split(/[\n,]/)
          .map((value) => value.trim())
          .filter(Boolean),
        restrictions,
      }),
    onSuccess: (updated) => {
      queryClient.setQueryData(["managed-policy", device.id], updated);
      setLoadedVersion(null);
      toast.push("Policy sent. It applies only after the local owner enters the device passcode.", "success");
    },
    onError: (error) => toast.push(error instanceof ApiError ? error.message : "Policy update failed", "error"),
  });

  const totals = new Map<string, { seconds: number; launches: number }>();
  for (const item of usage.data?.items ?? []) {
    const current = totals.get(item.package_name) ?? { seconds: 0, launches: 0 };
    current.seconds += item.foreground_seconds;
    current.launches += item.launches;
    totals.set(item.package_name, current);
  }
  const topUsage = [...totals.entries()].sort((a, b) => b[1].seconds - a[1].seconds).slice(0, 8);

  return (
    <details className="mt-4 w-full rounded-xl border border-edge bg-surface/40">
      <summary className="cursor-pointer px-4 py-3 text-body font-semibold text-fg">
        Device Owner policy and aggregate usage
      </summary>
      <div className="grid gap-5 border-t border-edge p-4 lg:grid-cols-2">
        <section aria-label="Managed policy" className="space-y-4">
          {policy.isLoading && <LoadingBlock label="Loading management policy" />}
          {policy.isError && <ErrorState message={policy.error.message} onRetry={() => void policy.refetch()} />}
          {policy.data && (
            <>
              <div className="flex flex-wrap gap-2">
                <Badge tone={policy.data.pending_local_approval ? "warning" : "success"}>
                  {policy.data.pending_local_approval ? "Awaiting local passcode approval" : `Applied v${policy.data.last_applied_version}`}
                </Badge>
                <Badge>Policy v{policy.data.policy_version}</Badge>
              </div>
              <Switch checked={launcher} onChange={setLauncher} label="Use A.R.M.X as the managed launcher" />
              <Switch checked={kiosk} onChange={setKiosk} label="Enable lock-task kiosk after local approval" />
              <Switch checked={telemetry} onChange={setTelemetry} label="Share permission-scoped aggregate app usage" />
              <div>
                <Label htmlFor={`packages-${device.id}`}>Allowed Android packages</Label>
                <textarea
                  id={`packages-${device.id}`}
                  rows={4}
                  value={packages}
                  onChange={(event) => setPackages(event.target.value)}
                  className="mt-1 w-full rounded-md border border-edge bg-bg px-3 py-2 font-mono text-caption text-fg"
                  placeholder={"ai.armx.managed\ncom.android.chrome"}
                />
                <p className="mt-1 text-caption text-fgmuted">One package ID per line. A.R.M.X is always retained.</p>
              </div>
              <fieldset>
                <legend className="text-caption font-medium text-fg">Dedicated-device restrictions</legend>
                <div className="mt-2 space-y-2">
                  {RESTRICTIONS.map(([value, label]) => (
                    <label key={value} className="flex min-h-touch items-center gap-2 text-caption text-fgmuted">
                      <input
                        type="checkbox"
                        checked={restrictions.includes(value)}
                        onChange={(event) =>
                          setRestrictions((current) =>
                            event.target.checked ? [...current, value] : current.filter((item) => item !== value),
                          )
                        }
                        className="size-4 accent-accent"
                      />
                      {label}
                    </label>
                  ))}
                </div>
              </fieldset>
              {policy.data.last_error && <p role="alert" className="text-caption text-danger">{policy.data.last_error}</p>}
              <Button onClick={() => save.mutate()} loading={save.isPending}>Stage policy for local approval</Button>
              <p className="text-caption text-fgmuted">
                Remote changes never bypass the on-device owner passcode. Deprovisioning also remains a local, passcode-authorized action.
              </p>
            </>
          )}
        </section>
        <section aria-label="Aggregate usage telemetry">
          <h3 className="text-body font-semibold">Last 7 days · aggregate only</h3>
          <p className="mt-1 text-caption text-fgmuted">Package, foreground time and launch count only. No screen content, typing, messages or notifications.</p>
          {usage.isLoading && <div className="mt-4"><LoadingBlock label="Loading aggregate usage" /></div>}
          {usage.isError && <div className="mt-4"><ErrorState message={usage.error.message} onRetry={() => void usage.refetch()} /></div>}
          {usage.data && topUsage.length === 0 && <p className="mt-4 text-caption text-fgmuted">No aggregate reports received yet.</p>}
          <div className="mt-4 divide-y divide-edge">
            {topUsage.map(([packageName, total]) => (
              <div key={packageName} className="flex items-center gap-3 py-2 text-caption">
                <code className="min-w-0 flex-1 truncate text-accent">{packageName}</code>
                <span className="text-fgmuted">{Math.round(total.seconds / 60)} min</span>
                <span className="text-fgmuted">{total.launches} launches</span>
              </div>
            ))}
          </div>
        </section>
      </div>
    </details>
  );
}

function ScreenShareControls({
  device,
  busy,
  onToggle,
}: {
  device: Device;
  busy: boolean;
  onToggle: (active: boolean) => void;
}) {
  const status = useQuery({
    queryKey: ["screen-share", device.id],
    queryFn: () => api.get<ScreenShareStatus>(`/devices/${device.id}/screen-share`),
    refetchInterval: 1_500,
  });
  const [frameUrl, setFrameUrl] = useState<string | null>(null);
  const [frameError, setFrameError] = useState<string | null>(null);
  const loadingFrame = useRef(false);
  const sessionId = status.data?.status === "active" ? status.data.session_id : null;

  useEffect(() => {
    if (!sessionId) {
      setFrameUrl((previous) => {
        if (previous) URL.revokeObjectURL(previous);
        return null;
      });
      setFrameError(null);
      return;
    }
    let cancelled = false;
    const loadFrame = async () => {
      if (loadingFrame.current) return;
      loadingFrame.current = true;
      try {
        const blob = await api.blob(`/devices/${device.id}/consent-sessions/${sessionId}/frame`);
        if (blob && !cancelled) {
          const next = URL.createObjectURL(blob);
          setFrameUrl((previous) => {
            if (previous) URL.revokeObjectURL(previous);
            return next;
          });
          setFrameError(null);
        }
      } catch (error) {
        if (!cancelled && error instanceof ApiError && error.status !== 409) setFrameError(error.message);
      } finally {
        loadingFrame.current = false;
      }
    };
    void loadFrame();
    const timer = window.setInterval(() => void loadFrame(), 1_000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
      setFrameUrl((previous) => {
        if (previous) URL.revokeObjectURL(previous);
        return null;
      });
    };
  }, [device.id, sessionId]);

  const sharing = status.data?.status === "active";
  const requested = status.data?.status === "requested";
  return (
    <div className="w-full">
      <div className="flex flex-wrap items-center justify-end gap-2">
        {(sharing || requested) && (
          <Badge tone={sharing ? "success" : "warning"}>{sharing ? "Live · visible on device" : "Awaiting device consent"}</Badge>
        )}
        <Button
          size="sm"
          variant="secondary"
          loading={busy}
          disabled={status.isLoading || status.isError}
          onClick={() => onToggle(!(sharing || requested))}
        >
          {sharing ? "End screen share" : requested ? "Cancel consent request" : "Request screen share"}
        </Button>
      </div>
      {sharing && (
        <div className="mt-4 overflow-hidden rounded-xl border border-edge bg-black/80" aria-live="polite">
          <div className="flex items-center justify-between border-b border-edge px-3 py-2 text-caption">
            <span className="font-medium text-success">● Consented live mirror</span>
            <span className="text-fgmuted">The device can stop this at any time</span>
          </div>
          <div className="flex min-h-56 items-center justify-center">
            {frameUrl ? (
              // Object URLs keep bearer credentials out of image URLs and browser history.
              // eslint-disable-next-line @next/next/no-img-element
              <img src={frameUrl} alt={`Live consented screen from ${device.name}`} className="max-h-[38rem] w-full object-contain" />
            ) : (
              <p className="p-8 text-center text-body text-fgmuted">Waiting for the first encrypted frame from the device…</p>
            )}
          </div>
          {frameError && <p role="alert" className="border-t border-edge px-3 py-2 text-caption text-danger">{frameError}</p>}
        </div>
      )}
    </div>
  );
}

export default function DevicesPage() {
  const { user } = useAuth();
  const toast = useToast();
  const queryClient = useQueryClient();
  const canLink = user?.role === "vip" || user?.role === "admin";

  const devices = useQuery({ queryKey: ["devices"], queryFn: () => api.get<Device[]>("/devices") });

  const [pairing, setPairing] = useState<{ code: string; deviceName: string } | null>(null);
  const [confirmDevice, setConfirmDevice] = useState<Device | null>(null);
  const [unlinkPassword, setUnlinkPassword] = useState("");
  const [unlinkError, setUnlinkError] = useState<string | null>(null);

  const requestPairing = useMutation({
    mutationFn: (payload: { name: string; platform: string; capabilities: string[] }) =>
      api.post<{ pairing_code: string; device: Device }>("/devices/pairing/request", payload),
    onSuccess: (data) => {
      setPairing({ code: data.pairing_code, deviceName: data.device.name });
      void queryClient.invalidateQueries({ queryKey: ["devices"] });
    },
    onError: (error) => toast.push(error instanceof ApiError ? error.message : "Pairing failed", "error"),
  });

  const startUnlink = useMutation({
    mutationFn: async ({ device, password }: { device: Device; password: string }) => {
      const { ticket } = await api.post<{ ticket: string }>(`/devices/${device.id}/unlink/verify`, { password });
      await api.post(`/devices/${device.id}/unlink`, { ticket });
    },
    onSuccess: () => {
      toast.push("Device unlinked. Commands can no longer reach it.", "success");
      setConfirmDevice(null);
      setUnlinkPassword("");
      void queryClient.invalidateQueries({ queryKey: ["devices"] });
    },
    onError: (error) => setUnlinkError(error instanceof ApiError ? error.message : "Could not unlink the device"),
  });

  const toggleShare = useMutation({
    mutationFn: async ({ device, active }: { device: Device; active: boolean }) => {
      if (active) await api.post(`/devices/${device.id}/screen-share/start`);
      else await api.post(`/devices/${device.id}/screen-share/stop`);
      return { device, active };
    },
    onSuccess: ({ device, active }) => {
      void queryClient.invalidateQueries({ queryKey: ["screen-share", device.id] });
      toast.push(
        active ? "Consent request sent. Sharing starts only after the device accepts Android’s capture prompt and shows its live indicator." : "Screen share ended.",
        "info",
      );
    },
    onError: (error) => toast.push(error instanceof ApiError ? error.message : "Could not update screen sharing", "error"),
  });

  return (
    <div>
      <PageHeader
        title="Linked devices"
        description="Pairing happens on the device itself. The device always shows a persistent “Linked” notification, and only the password set on that device can unlink it."
        action={
          canLink ? (
            <Button
              onClick={() =>
                requestPairing.mutate({ name: "My phone", platform: "android", capabilities: ["alarm", "app_launch", "state", "calls", "management", "screen_share", "voice", "usage"] })
              }
              loading={requestPairing.isPending}
            >
              Pair a device
            </Button>
          ) : undefined
        }
      />

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        <div>
          {devices.isLoading && <LoadingBlock label="Loading devices" />}
          {devices.isError && <ErrorState message={devices.error.message} onRetry={() => void devices.refetch()} />}
          {devices.data && devices.data.length === 0 && (
            <EmptyState
              icon="▤"
              title="No devices linked"
              description={
                canLink
                  ? "Start pairing here, then enter the code in the A.R.M.X app on the device and choose an unlink password there."
                  : "Device linking requires the VIP role. Ask an administrator to upgrade your account."
              }
              action={
                canLink ? (
                  <Button
                    onClick={() =>
                      requestPairing.mutate({ name: "My phone", platform: "android", capabilities: ["alarm", "app_launch", "state", "calls", "management", "screen_share", "voice", "usage"] })
                    }
                    loading={requestPairing.isPending}
                  >
                    Start pairing
                  </Button>
                ) : undefined
              }
            />
          )}

          <div className="space-y-3">
            {devices.data?.map((device) => (
              <Card key={device.id}>
                <CardHeader
                  title={device.name}
                  description={`${device.platform} · ${device.capabilities.join(", ") || "no capabilities"}`}
                  action={
                    <Badge tone={device.status === "active" ? "success" : device.status === "pending" ? "warning" : "neutral"}>
                      {device.status}
                    </Badge>
                  }
                />
                <div className="flex flex-wrap items-center gap-2 px-5 py-4">
                  <span className="text-caption text-fgmuted">
                    Last seen {device.last_seen_at ? new Date(device.last_seen_at).toLocaleString() : "never"}
                  </span>
                  {device.status === "active" && (
                    <>
                      <Button size="sm" variant="danger" className="ml-auto" onClick={() => setConfirmDevice(device)}>
                        Unlink
                      </Button>
                      <ScreenShareControls
                        device={device}
                        busy={toggleShare.isPending}
                        onToggle={(active) => toggleShare.mutate({ device, active })}
                      />
                    </>
                  )}
                </div>
                {device.status === "active" && (
                  <>
                    <p className="border-t border-edge px-5 py-3 text-caption text-fgmuted">
                      This device must keep showing the persistent “Linked” notification. There is no silent mode.
                    </p>
                    {device.platform === "android" && device.capabilities.includes("management") && (
                      <div className="border-t border-edge px-5 pb-5">
                        <ManagedDevicePanel device={device} />
                      </div>
                    )}
                  </>
                )}
              </Card>
            ))}
          </div>
        </div>

        <Card>
          <CardHeader title="How linking works" description="Four rules, enforced in code." />
          <ol className="space-y-3 p-5 text-body text-fgmuted">
            <li>
              <span className="font-semibold text-fg">1. Explicit pairing.</span> One action on the device: you type the
              code and choose the unlink password there.
            </li>
            <li>
              <span className="font-semibold text-fg">2. Always visible.</span> The device keeps a persistent
              notification. Silent mode does not exist.
            </li>
            <li>
              <span className="font-semibold text-fg">3. Owner password.</span> Unlinking needs the password set on the
              device. Admins and VIPs cannot override it.
            </li>
            <li>
              <span className="font-semibold text-fg">4. Nothing sneaky.</span> No silent call or SMS interception, no
              hidden screen capture. Screen mirroring is a flagged session either side can end.
            </li>
          </ol>
        </Card>
      </div>

      <Dialog
        open={Boolean(pairing)}
        onClose={() => setPairing(null)}
        title="Enter this code on the device"
        description={`Pairing ${pairing?.deviceName ?? "your device"} expires in 10 minutes.`}
        footer={<Button onClick={() => setPairing(null)}>Done</Button>}
      >
        <p className="font-mono text-display tracking-[0.3em] text-accent">{pairing?.code}</p>
        <p className="mt-3 text-caption text-fgmuted">
          In the A.R.M.X app choose “Pair with code”, enter it, then set the unlink password. The link only becomes
          active after that confirmation.
        </p>
      </Dialog>

      <Dialog
        open={Boolean(confirmDevice)}
        onClose={() => {
          setConfirmDevice(null);
          setUnlinkPassword("");
          setUnlinkError(null);
        }}
        tone="danger"
        title="Unlink this device?"
        description="Enter the unlink password that was set on the device. Administrators cannot bypass this."
        footer={
          <>
            <Button
              variant="ghost"
              onClick={() => {
                setConfirmDevice(null);
                setUnlinkPassword("");
              }}
            >
              Cancel
            </Button>
            <Button
              variant="danger"
              loading={startUnlink.isPending}
              onClick={() => confirmDevice && startUnlink.mutate({ device: confirmDevice, password: unlinkPassword })}
              disabled={unlinkPassword.length < 1}
            >
              Unlink device
            </Button>
          </>
        }
      >
        <Label htmlFor="unlink-password">Unlink password</Label>
        <Input
          id="unlink-password"
          type="password"
          value={unlinkPassword}
          onChange={(e) => setUnlinkPassword(e.target.value)}
          placeholder="Password set on the device"
        />
        {unlinkError && (
          <p role="alert" className="mt-2 text-caption text-danger">
            {unlinkError}
          </p>
        )}
      </Dialog>
    </div>
  );
}
