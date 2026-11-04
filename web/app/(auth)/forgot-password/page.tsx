"use client";

import { useEffect, useState } from "react";
import { api, describeError } from "@/lib/api/client";
import { AuthCard, AuthLink, Notice, PrimaryButton, TextField } from "@/components/auth/auth-ui";

const GENERIC_MESSAGE = "If an account exists for this email, you will receive password recovery instructions shortly.";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [message, setMessage] = useState(GENERIC_MESSAGE);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [cooldown, setCooldown] = useState(0);

  useEffect(() => {
    if (cooldown <= 0) return;
    const timer = window.setInterval(() => setCooldown((value) => Math.max(0, value - 1)), 1000);
    return () => window.clearInterval(timer);
  }, [cooldown]);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.trim())) {
      setError("Enter a valid email address.");
      return;
    }
    if (cooldown > 0) return;
    setBusy(true);
    try {
      const result = await api.post<{ status: string; message: string }>("/auth/forgot-password", {
        email: email.trim(),
      });
      setMessage(result.message || GENERIC_MESSAGE);
      setSent(true);
      setCooldown(60);
    } catch (err) {
      setError(describeError(err, "request password recovery"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthCard
      title="Reset your password"
      subtitle="Enter your registered email. We will send a secure, single-use recovery link."
      footer={<AuthLink href="/login">← Back to sign in</AuthLink>}
    >
      {sent ? (
        <div className="space-y-4">
          <Notice tone="success" title="Check your email">{message}</Notice>
          <div className="rounded-lg border border-edge/70 bg-bg/50 p-3 text-caption text-fgmuted">
            <p>The link expires in 15 minutes and can be used once. Requests are rate-limited; a 60-second cooldown protects against duplicate emails.</p>
            <p className="mt-2">If you do not see the message, check spam and confirm the Resend sender domain is verified.</p>
          </div>
          {cooldown > 0 && (
            <p className="text-center text-caption text-fgmuted">You can request another link in {cooldown}s.</p>
          )}
          <button
            type="button"
            disabled={cooldown > 0}
            onClick={() => { setSent(false); setError(null); }}
            className="w-full rounded-lg border border-edge px-4 py-2.5 text-caption font-semibold text-fgmuted transition hover:border-accent/40 hover:text-accent disabled:opacity-50"
          >
            Use a different email
          </button>
        </div>
      ) : (
        <>
          {error && <div className="mb-4"><Notice tone="error">{error}</Notice></div>}
          <form onSubmit={onSubmit} className="space-y-4" noValidate>
            <TextField
              id="forgot-email"
              label="Email address"
              type="email"
              autoComplete="email"
              placeholder="you@example.com"
              value={email}
              onChange={setEmail}
              disabled={busy || cooldown > 0}
            />
            <PrimaryButton busy={busy} disabled={cooldown > 0}>
              {cooldown > 0 ? `Please wait ${cooldown}s` : busy ? "Sending…" : "Send reset link"}
            </PrimaryButton>
          </form>
          <p className="mt-4 text-center text-[11px] leading-relaxed text-fgmuted/70">
            We never reveal whether an address has an account. Delivery requires server-side Resend configuration.
          </p>
        </>
      )}
    </AuthCard>
  );
}
