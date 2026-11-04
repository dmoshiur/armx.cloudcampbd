"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { describeError, request } from "@/lib/api/client";
import { useAuth } from "@/lib/hooks/useAuth";
import { AuthCard, AuthFooterLinks, AuthLink, Notice, PasswordField, PrimaryButton, TextField } from "@/components/auth/auth-ui";

const GOOGLE_ERRORS: Record<string, string> = {
  google_cancelled: "Google sign-in was cancelled.",
  google_token: "Google did not return a token. Try again.",
  google_profile: "Could not read your Google profile.",
  google_unverified: "Your Google email is not verified.",
  state_mismatch: "The sign-in request expired. Try again.",
  state_invalid: "The sign-in request could not be verified.",
};

function safeNext(raw: string | null): string {
  if (!raw || !raw.startsWith("/") || raw.startsWith("//")) return "/";
  return raw;
}

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const { login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const code = params.get("error");
    if (code) setError(GOOGLE_ERRORS[code] ?? "Sign-in failed. Try again.");
    if (params.get("reset") === "1") setNotice("Password updated. Sign in with your new password.");
    if (params.get("verified") === "1") setNotice("Email verified. You can sign in now.");
    if (params.get("setup") === "complete") setNotice("Secure setup complete. Sign in as the platform owner.");
  }, [params]);

  const { data: setup } = useQuery({
    queryKey: ["setup", "status"],
    queryFn: () => request<{ needs_setup: boolean }>("/setup/status", { auth: false }),
    retry: false,
  });

  useEffect(() => {
    if (setup?.needs_setup) router.replace("/setup");
  }, [router, setup]);

  const { data: config } = useQuery({
    queryKey: ["config"],
    queryFn: () => request<{ features: { google_login: boolean } }>("/config", { auth: false }),
    staleTime: Infinity,
    retry: false,
  });

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.trim())) {
      setError("Enter a valid email address.");
      return;
    }
    if (!password) {
      setError("Enter your password.");
      return;
    }
    setBusy(true);
    try {
      const me = await login({ email: email.trim(), password, remember_me: remember });
      if (!me) throw new Error("The session could not be established. Sign in again.");
      router.replace(safeNext(params.get("next")));
    } catch (err) {
      setError(describeError(err, "sign in"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthCard
      title="Welcome back"
      subtitle="Sign in to your A.R.M.X AI workspace."
      footer={
        <AuthFooterLinks>
          <AuthLink href="/forgot-password">Forgot password?</AuthLink>
          <span aria-hidden="true" className="text-edge">·</span>
          <AuthLink href="/register">Create an account</AuthLink>
        </AuthFooterLinks>
      }
    >
      {notice && <div className="mb-4"><Notice tone="success">{notice}</Notice></div>}
      {error && (
        <div className="mb-4">
          <Notice tone="error" title="Sign-in failed">
            <p>{error}</p>
            {/verify your email/i.test(error) && (
              <p className="mt-1.5 text-caption">
                Need a new link? <AuthLink href="/verify-email">Resend verification email</AuthLink>
              </p>
            )}
          </Notice>
        </div>
      )}

      <form onSubmit={onSubmit} className="space-y-4" noValidate>
        <TextField
          id="login-email"
          label="Email address"
          type="email"
          autoComplete="email"
          placeholder="you@example.com"
          value={email}
          onChange={setEmail}
          disabled={busy}
        />
        <PasswordField
          id="login-password"
          label="Password"
          autoComplete="current-password"
          value={password}
          onChange={setPassword}
          disabled={busy}
        />
        <div className="flex items-center justify-between gap-3 pt-0.5">
          <label className="flex cursor-pointer items-center gap-2 text-caption text-fgmuted">
            <input
              type="checkbox"
              checked={remember}
              onChange={(event) => setRemember(event.target.checked)}
              className="h-4 w-4 rounded border-edge bg-bg accent-accent"
            />
            Remember me
          </label>
          <AuthLink href="/forgot-password">Forgot password?</AuthLink>
        </div>
        <PrimaryButton busy={busy}>{busy ? "Signing in…" : "Sign in"}</PrimaryButton>
      </form>

      {config?.features.google_login && (
        <div className="mt-5">
          <div className="mb-4 flex items-center gap-3 text-caption text-fgmuted">
            <span className="h-px flex-1 bg-edge" />or<span className="h-px flex-1 bg-edge" />
          </div>
          <a
            href="/api/auth/google/start"
            className="flex h-11 w-full items-center justify-center gap-2 rounded-lg border border-edge bg-bg/50 text-body font-semibold text-fg transition hover:border-accent/40 hover:bg-white/5"
          >
            Continue with Google
          </a>
        </div>
      )}
    </AuthCard>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={<p className="text-body text-fgmuted">Loading…</p>}>
      <LoginForm />
    </Suspense>
  );
}
