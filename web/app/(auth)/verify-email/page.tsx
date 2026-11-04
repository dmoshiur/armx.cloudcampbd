"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, describeError, request } from "@/lib/api/client";
import { useAuth } from "@/lib/hooks/useAuth";
import { AuthCard, AuthLink, Notice, PrimaryButton, TextField } from "@/components/auth/auth-ui";

const GENERIC_MESSAGE = "If an account exists and needs verification, you will receive instructions shortly.";

function VerifyInner() {
  const params = useSearchParams();
  const token = params.get("token");
  const sent = params.get("sent") === "1";
  const optional = params.get("optional") === "1";
  const emailFromQuery = params.get("email") || "";
  const { user } = useAuth();
  const [state, setState] = useState<"pending" | "ok" | "error" | "sent">(token ? "pending" : sent ? "sent" : "error");
  const [message, setMessage] = useState(token ? "" : sent ? "A verification email was queued for your new account." : "This link is missing its token.");
  const [email, setEmail] = useState(emailFromQuery);
  const [resendMessage, setResendMessage] = useState(GENERIC_MESSAGE);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [cooldown, setCooldown] = useState(0);

  const { data: config } = useQuery({
    queryKey: ["config", "verify"],
    queryFn: () =>
      request<{ features: { email_verification_required: boolean } }>("/config", { auth: false }),
    staleTime: Infinity,
    retry: false,
  });

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    api
      .post<{ status: string; message: string }>("/auth/verify-email", { token })
      .then((result) => {
        if (!cancelled) {
          setState("ok");
          setMessage(result.message || "Email verified. You can sign in now.");
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setState("error");
          setMessage(describeError(err, "verify your email"));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  useEffect(() => {
    if (cooldown <= 0) return;
    const timer = window.setInterval(() => setCooldown((value) => Math.max(0, value - 1)), 1000);
    return () => window.clearInterval(timer);
  }, [cooldown]);

  async function resend(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.trim())) {
      setError("Enter a valid email address.");
      return;
    }
    if (cooldown > 0) return;
    setBusy(true);
    try {
      const result = await api.post<{ status: string; message: string }>("/auth/resend-verification", {
        email: email.trim(),
      });
      setResendMessage(result.message || GENERIC_MESSAGE);
      setCooldown(60);
      setState("sent");
    } catch (err) {
      setError(describeError(err, "resend the verification email"));
    } finally {
      setBusy(false);
    }
  }

  if (state === "pending") {
    return (
      <AuthCard title="Verifying your email" subtitle="Validating the single-use link…" footer={<AuthLink href="/login">Back to sign in</AuthLink>}>
        <div className="flex items-center justify-center gap-3 py-4 text-body text-fgmuted">
          <span className="h-4 w-4 animate-spin rounded-full border-2 border-accent border-t-transparent" /> Verifying…
        </div>
      </AuthCard>
    );
  }

  if (state === "ok") {
    return (
      <AuthCard title="Email verified" subtitle={message} footer={<AuthLink href="/login?verified=1">Continue to sign in →</AuthLink>}>
        <Notice tone="success" title="Your address is confirmed">
          {config?.features.email_verification_required
            ? "Verified access is now enabled for this account. Sign in to continue."
            : "This instance currently permits unverified access by policy, but your address is now marked verified."}
        </Notice>
        {user && (
          <div className="mt-4 text-center">
            <AuthLink href="/">Open your workspace →</AuthLink>
          </div>
        )}
      </AuthCard>
    );
  }

  return (
    <AuthCard
      title={state === "sent" ? "Check your email" : "Verification failed"}
      subtitle={state === "sent" ? message : message}
      footer={<AuthLink href="/login">← Back to sign in</AuthLink>}
    >
      {state === "sent" && (
        <div className="mb-4 space-y-3">
          <Notice tone="info">{resendMessage}</Notice>
          <p className="text-caption text-fgmuted">
            Verification links expire after 24 hours and are single-use. {optional && "This instance does not currently require verification to sign in, but confirming is recommended."}
          </p>
        </div>
      )}
      {state === "error" && !sent && (
        <div className="mb-4">
          <Notice tone="error">{message}</Notice>
        </div>
      )}
      {error && <div className="mb-4"><Notice tone="error">{error}</Notice></div>}
      <form onSubmit={resend} className="space-y-4" noValidate>
        <TextField
          id="verify-email"
          label="Email address"
          type="email"
          autoComplete="email"
          placeholder="you@example.com"
          value={email}
          onChange={setEmail}
          disabled={busy || cooldown > 0}
        />
        <PrimaryButton busy={busy} disabled={cooldown > 0}>
          {cooldown > 0 ? `Resend available in ${cooldown}s` : busy ? "Sending…" : "Resend verification email"}
        </PrimaryButton>
      </form>
      <p className="mt-4 text-center text-[11px] leading-relaxed text-fgmuted/70">
        Resend requests are rate-limited and share a 60-second cooldown. The response never reveals whether an address exists.
      </p>
    </AuthCard>
  );
}

export default function VerifyEmailPage() {
  return (
    <Suspense fallback={<p className="text-body text-fgmuted">Loading…</p>}>
      <VerifyInner />
    </Suspense>
  );
}
