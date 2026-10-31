"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
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
import { useToast } from "@/components/ui/toast";

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
  const [shareActive, setShareActive] = useState<string | null>(null);

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
      setShareActive(active ? device.id : null);
      toast.push(
        active ? "Screen share started — the device shows a live indicator you can stop any time." : "Screen share ended.",
        "info",
      );
    },
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
                requestPairing.mutate({ name: "My phone", platform: "android", capabilities: ["alarm", "app_launch", "state", "calls"] })
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
                      requestPairing.mutate({ name: "My phone", platform: "android", capabilities: ["alarm", "app_launch", "state", "calls"] })
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
                      <Button
                        size="sm"
                        variant="secondary"
                        className="ml-auto"
                        onClick={() => toggleShare.mutate({ device, active: shareActive !== device.id })}
                      >
                        {shareActive === device.id ? "End screen share" : "Start screen share"}
                      </Button>
                      <Button size="sm" variant="danger" onClick={() => setConfirmDevice(device)}>
                        Unlink
                      </Button>
                    </>
                  )}
                </div>
                {device.status === "active" && (
                  <p className="border-t border-edge px-5 py-3 text-caption text-fgmuted">
                    This device must keep showing the persistent “Linked” notification. There is no silent mode.
                  </p>
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
