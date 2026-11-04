"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { describeError, request } from "@/lib/api/client";
import { AuthCard, AuthLink, Notice, PrimaryButton, TextField } from "@/components/auth/auth-ui";

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
    queryFn: () => request<SetupState>("/setup/status", { auth: false }),
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
      await request("/setup/complete", {
        method: "POST",
        auth: false,
        body: JSON.stringify({
          setup_token: setupToken,
          email,
          display_name: displayName,
          password,
        }),
      });
      router.replace("/login?setup=complete");
    } catch (err) {
      setError(describeError(err, "complete platform setup"));
    } finally {
      setBusy(false);
    }
  }

  if (state.isLoading) {
    return (
      <AuthCard title="Checking platform state" subtitle="Reading the protected first-boot status…">
        <div className="flex items-center justify-center gap-3 py-4 text-body text-fgmuted">
          <span className="h-4 w-4 animate-spin rounded-full border-2 border-accent border-t-transparent" /> Checking…
        </div>
      </AuthCard>
    );
  }
  if (state.isError) {
    return (
      <AuthCard title="Setup status unavailable" subtitle={state.error.message} footer={<AuthLink href="/login">Back to sign in</AuthLink>}>
        <Notice tone="error">Check `/api/health` and the deployment proxy, then refresh this page.</Notice>
      </AuthCard>
    );
  }
  if (!state.data?.needs_setup) {
    const complete = state.data?.complete;
    return (
      <AuthCard
        title={complete ? "Setup is already complete" : "Setup is not required"}
        subtitle={complete ? "An administrator exists; redirecting to sign in." : "This instance is not in a production/staging first-boot state."}
        footer={<AuthLink href={complete ? "/login?setup=complete" : "/login"}>Continue to sign in →</AuthLink>}
      >
        <Notice tone={complete ? "success" : "info"}>
          {complete
            ? "This one-time bootstrap route is closed."
            : "In production, ENV=production or ENV=staging requires one protected admin bootstrap before public use."}
        </Notice>
      </AuthCard>
    );
  }
  if (!state.data.setup_available) {
    return (
      <AuthCard title="Bootstrap locked" subtitle="Set a protected initial setup token before creating the first administrator." footer={<AuthLink href="/login">Back to sign in</AuthLink>}>
        <Notice tone="info">
          Add <code className="font-mono text-accent">INITIAL_SETUP_TOKEN</code> to Render, redeploy, then reload this page. Use at least 32 random characters.
          {state.data.environment_seed_configured && " An environment seed is configured; restart the service to apply it."}
        </Notice>
      </AuthCard>
    );
  }

  return (
    <AuthCard
      title="Create the platform owner"
      subtitle="This one-time route permanently closes after the first administrator is committed to the database."
      footer={<AuthLink href="/login">← Back to sign in</AuthLink>}
    >
      {error && <div className="mb-4"><Notice tone="error">{error}</Notice></div>}
      <form onSubmit={submit} className="space-y-4" noValidate>
        <TextField id="setup-token" label="Render setup token" type="password" autoComplete="off" value={setupToken} onChange={setSetupToken} hint="At least 32 characters; never shared with the browser bundle" disabled={busy} />
        <TextField id="owner-name" label="Display name" autoComplete="name" value={displayName} onChange={setDisplayName} disabled={busy} />
        <TextField id="owner-email" label="Owner email" type="email" autoComplete="email" value={email} onChange={setEmail} disabled={busy} />
        <TextField id="owner-password" label="Password" type="password" autoComplete="new-password" value={password} onChange={setPassword} hint="10+ characters, uppercase and symbol" disabled={busy} />
        <TextField id="owner-confirm" label="Confirm password" type="password" autoComplete="new-password" value={confirm} onChange={setConfirm} disabled={busy} />
        <PrimaryButton busy={busy}>Seal setup and continue</PrimaryButton>
      </form>
      <p className="mt-4 text-center text-[11px] leading-relaxed text-fgmuted/70">
        The owner is created with server-side authorization only. No public registration can grant ADMIN.
      </p>
    </AuthCard>
  );
}
