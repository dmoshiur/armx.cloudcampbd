"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api/client";
import { Button, FieldError, Input, Label } from "@/components/ui/primitives";

interface SetupState {
  required: boolean;
  complete: boolean;
  needs_setup: boolean;
  setup_available: boolean;
  environment_seed_configured: boolean;
}

export default function SetupPage() {
  const router = useRouter();
  const [setupToken, setSetupToken] = useState("");
  const [email, setEmail] = useState("");
  const [displayName, setDisplayName] = useState("Platform owner");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const state = useQuery({
    queryKey: ["setup", "status"],
    queryFn: () => api.get<SetupState>("/setup/status"),
    retry: false,
  });

  useEffect(() => {
    if (state.data?.complete) router.replace("/login?setup=complete");
  }, [router, state.data]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    if (password !== confirm) {
      setError("Passwords do not match.");
      return;
    }
    setBusy(true);
    try {
      await api.post("/setup/complete", {
        setup_token: setupToken,
        email,
        display_name: displayName,
        password,
      });
      router.replace("/login?setup=complete");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Setup could not be completed");
    } finally {
      setBusy(false);
    }
  }

  if (state.isLoading) return <p className="text-body text-fgmuted">Checking platform state…</p>;
  if (state.isError) return <p className="text-body text-danger">Could not read setup status.</p>;
  if (!state.data?.needs_setup) return <p className="text-body text-fgmuted">Setup is already complete. Redirecting…</p>;

  if (!state.data.setup_available) {
    return (
      <div>
        <p className="font-mono text-caption uppercase tracking-[0.2em] text-accent">bootstrap locked</p>
        <h2 className="mt-2 text-h1">Set an initial setup token</h2>
        <p className="mt-3 text-body text-fgmuted">
          Add <code className="text-accent">INITIAL_SETUP_TOKEN</code> to Render, redeploy, then reload this page. Use at least 32 random characters.
          Alternatively set both <code className="text-accent">FIRST_ADMIN_EMAIL</code> and <code className="text-accent">FIRST_ADMIN_PASSWORD</code> for one-shot environment seeding.
        </p>
      </div>
    );
  }

  return (
    <div>
      <p className="font-mono text-caption uppercase tracking-[0.2em] text-accent">first secure boot</p>
      <h2 className="mt-2 text-h1">Create the platform owner</h2>
      <p className="mt-2 text-body text-fgmuted">
        This route permanently closes after the first administrator is committed to the database.
      </p>
      <form onSubmit={submit} className="mt-6 space-y-4" noValidate>
        <div>
          <Label htmlFor="setup-token">Render setup token</Label>
          <Input id="setup-token" type="password" autoComplete="off" required value={setupToken} onChange={(event) => setSetupToken(event.target.value)} />
        </div>
        <div>
          <Label htmlFor="owner-name">Display name</Label>
          <Input id="owner-name" required value={displayName} onChange={(event) => setDisplayName(event.target.value)} />
        </div>
        <div>
          <Label htmlFor="owner-email">Owner email</Label>
          <Input id="owner-email" type="email" autoComplete="email" required value={email} onChange={(event) => setEmail(event.target.value)} />
        </div>
        <div>
          <Label htmlFor="owner-password" hint="10+ characters, uppercase and symbol">Password</Label>
          <Input id="owner-password" type="password" autoComplete="new-password" required value={password} onChange={(event) => setPassword(event.target.value)} />
        </div>
        <div>
          <Label htmlFor="owner-confirm">Confirm password</Label>
          <Input id="owner-confirm" type="password" autoComplete="new-password" required value={confirm} onChange={(event) => setConfirm(event.target.value)} />
          <FieldError>{error}</FieldError>
        </div>
        <Button type="submit" className="w-full" loading={busy}>Seal setup and continue</Button>
      </form>
    </div>
  );
}
