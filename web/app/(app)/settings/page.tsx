"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, ApiError } from "@/lib/api/client";
import { useAuth } from "@/lib/hooks/useAuth";
import type { Device } from "@/lib/types";
import {Badge, Button, Card, CardHeader, ErrorState, Input, Label, LoadingBlock, PageHeader} from "@/components/ui/primitives";
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

export default function SettingsPage() {
  const { user, logout, refreshUser } = useAuth();
  const toast = useToast();
  const queryClient = useQueryClient();

  const sessions = useQuery({ queryKey: ["sessions"], queryFn: () => api.get<SessionRow[]>("/auth/sessions") });
  const profiles = useQuery({ queryKey: ["profiles"], queryFn: () => api.get<Profile[]>("/messaging/profiles") });
  const devices = useQuery({ queryKey: ["devices"], queryFn: () => api.get<Device[]>("/devices") });

  const [displayName, setDisplayName] = useState(user?.display_name ?? "");
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [newContact, setNewContact] = useState({ channel: "whatsapp", contact_id: "", display_name: "", personality: "", auto_send: false });

  const saveName = useMutation({
    mutationFn: () => api.patch("/auth/me", { display_name: displayName }),
    onSuccess: async () => {
      await refreshUser();
      toast.push("Profile updated", "success");
    },
    onError: (error) => toast.push(error instanceof ApiError ? error.message : "Could not save", "error"),
  });

  const changePassword = useMutation({
    mutationFn: () => api.post("/auth/change-password", { current_password: currentPassword, new_password: newPassword }),
    onSuccess: async () => {
      toast.push("Password changed. Other sessions were signed out.", "success");
      setCurrentPassword("");
      setNewPassword("");
      await logout();
    },
    onError: (error) => toast.push(error instanceof ApiError ? error.message : "Could not change the password", "error"),
  });

  const revokeSession = useMutation({
    mutationFn: (id: string) => api.del(`/auth/sessions/${id}`),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["sessions"] }),
  });

  const addProfile = useMutation({
    mutationFn: () => api.post("/messaging/profiles", newContact),
    onSuccess: () => {
      toast.push("Contact saved", "success");
      setNewContact({ channel: "whatsapp", contact_id: "", display_name: "", personality: "", auto_send: false });
      void queryClient.invalidateQueries({ queryKey: ["profiles"] });
    },
    onError: (error) => toast.push(error instanceof ApiError ? error.message : "Could not save the contact", "error"),
  });

  const removeProfile = useMutation({
    mutationFn: (id: string) => api.del(`/messaging/profiles/${id}`),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["profiles"] }),
  });

  return (
    <div className="space-y-5">
      <PageHeader title="Settings" description="Your profile, sessions, messaging contacts and account security." />

      <div className="grid gap-5 lg:grid-cols-2">
        <Card>
          <CardHeader title="Profile" description={user ? `${user.email} · ${user.role.toUpperCase()}` : ""} />
          <div className="space-y-4 p-5">
            <div>
              <Label htmlFor="display-name">Display name</Label>
              <Input id="display-name" value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
            </div>
            <Button onClick={() => saveName.mutate()} loading={saveName.isPending}>
              Save profile
            </Button>
            <div className="rounded-md border border-edge bg-bg p-3">
              <p className="text-caption text-fgmuted">Account role</p>
              <div className="mt-1 flex items-center gap-2">
                <Badge tone={user?.role === "admin" ? "accent" : user?.role === "vip" ? "success" : "neutral"}>
                  {user?.role ?? "user"}
                </Badge>
                <span className="text-caption text-fgmuted">
                  {user?.role === "user" ? "Device linking needs the VIP role." : "Device linking unlocked."}
                </span>
              </div>
            </div>
          </div>
        </Card>

        <Card>
          <CardHeader title="Password" description="Changing it signs out every other session." />
          <div className="space-y-4 p-5">
            <div>
              <Label htmlFor="current">Current password</Label>
              <Input id="current" type="password" value={currentPassword} onChange={(e) => setCurrentPassword(e.target.value)} autoComplete="current-password" />
            </div>
            <div>
              <Label htmlFor="next" hint="min 10 chars, uppercase, symbol">
                New password
              </Label>
              <Input id="next" type="password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} autoComplete="new-password" />
            </div>
            <Button
              variant="secondary"
              onClick={() => changePassword.mutate()}
              loading={changePassword.isPending}
              disabled={!currentPassword || newPassword.length < 10}
            >
              Change password
            </Button>
            <Button variant="danger" onClick={() => void logout()}>
              Sign out of this device
            </Button>
          </div>
        </Card>

        <Card>
          <CardHeader title="Active sessions" description="Revoke anything you do not recognise." />
          <div className="divide-y divide-edge">
            {sessions.isLoading && (
              <div className="p-5">
                <LoadingBlock />
              </div>
            )}
            {sessions.isError && (
              <div className="p-5">
                <ErrorState message={sessions.error.message} onRetry={() => void sessions.refetch()} />
              </div>
            )}
            {sessions.data?.map((session) => (
              <div key={session.id} className="flex items-start justify-between gap-3 px-4 py-3">
                <div className="min-w-0">
                  <p className="truncate text-caption text-fg">{session.user_agent || "unknown client"}</p>
                  <p className="text-caption text-fgmuted">
                    {session.ip_address || "unknown ip"} · started {new Date(session.created_at).toLocaleString()}
                  </p>
                </div>
                {session.current ? (
                  <Badge tone="accent">this session</Badge>
                ) : (
                  <Button size="sm" variant="ghost" onClick={() => revokeSession.mutate(session.id)}>
                    Revoke
                  </Button>
                )}
              </div>
            ))}
          </div>
        </Card>

        <Card>
          <CardHeader
            title="Messaging contacts"
            description="The assistant can only message people you add here. Auto-send is MEDIUM risk; new contacts are HIGH."
          />
          <div className="divide-y divide-edge">
            {profiles.data?.length === 0 && (
              <p className="px-4 py-4 text-caption text-fgmuted">No contacts yet.</p>
            )}
            {profiles.data?.map((profile) => (
              <div key={profile.id} className="flex items-start justify-between gap-3 px-4 py-3">
                <div className="min-w-0">
                  <p className="truncate text-body">{profile.display_name || profile.contact_id}</p>
                  <p className="truncate text-caption text-fgmuted">
                    {profile.channel} · {profile.contact_id}
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <Badge tone={profile.auto_send ? "warning" : "neutral"}>{profile.auto_send ? "auto-send" : "draft only"}</Badge>
                  <Button size="sm" variant="ghost" onClick={() => removeProfile.mutate(profile.id)}>
                    Remove
                  </Button>
                </div>
              </div>
            ))}
          </div>
          <div className="space-y-3 border-t border-edge p-4">
            <div className="grid gap-3 sm:grid-cols-2">
              <div>
                <Label htmlFor="contact-channel">Channel</Label>
                <select
                  id="contact-channel"
                  value={newContact.channel}
                  onChange={(e) => setNewContact({ ...newContact, channel: e.target.value })}
                  className="min-h-touch w-full rounded-md border border-edge bg-bg px-3 text-body"
                >
                  <option value="whatsapp">WhatsApp</option>
                  <option value="messenger">Messenger</option>
                </select>
              </div>
              <div>
                <Label htmlFor="contact-id">Phone (E.164) or PSID</Label>
                <Input
                  id="contact-id"
                  value={newContact.contact_id}
                  onChange={(e) => setNewContact({ ...newContact, contact_id: e.target.value })}
                  placeholder="+8801700000000"
                />
              </div>
            </div>
            <div>
              <Label htmlFor="contact-name">Name</Label>
              <Input id="contact-name" value={newContact.display_name} onChange={(e) => setNewContact({ ...newContact, display_name: e.target.value })} placeholder="Rahim" />
            </div>
            <Switch
              checked={newContact.auto_send}
              onChange={(next) => setNewContact({ ...newContact, auto_send: next })}
              label="Allow auto-send"
              description="Only enable this for contacts who have agreed to receive automated replies."
            />
            <Button
              variant="secondary"
              onClick={() => addProfile.mutate()}
              loading={addProfile.isPending}
              disabled={newContact.contact_id.length < 3}
            >
              Add contact
            </Button>
          </div>
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader title="Your linked devices" description="Read-only summary; manage them on the Devices page." />
          <div className="divide-y divide-edge">
            {devices.data?.length === 0 && <p className="px-4 py-4 text-caption text-fgmuted">No devices linked.</p>}
            {devices.data?.map((device) => (
              <div key={device.id} className="flex items-center justify-between gap-3 px-4 py-3">
                <div>
                  <p className="text-body">{device.name}</p>
                  <p className="text-caption text-fgmuted">{device.capabilities.join(", ")}</p>
                </div>
                <Badge tone={device.status === "active" ? "success" : "neutral"}>{device.status}</Badge>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
}
