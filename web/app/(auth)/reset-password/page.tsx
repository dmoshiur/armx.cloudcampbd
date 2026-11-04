"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { api, describeError } from "@/lib/api/client";
import {
  AuthCard,
  AuthLink,
  Notice,
  PasswordField,
  PasswordRequirements,
  PrimaryButton,
  passwordScore,
} from "@/components/auth/auth-ui";

function ResetForm() {
  const token = useSearchParams().get("token") ?? "";
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    if (passwordScore(password) < 3) {
      setError("Choose a stronger password that meets every requirement below.");
      return;
    }
    if (password !== confirm) {
      setError("Passwords do not match.");
      return;
    }
    setBusy(true);
    try {
      await api.post("/auth/reset-password", {
        token,
        password,
        confirm_password: confirm,
      });
      setDone(true);
    } catch (err) {
      setError(describeError(err, "reset your password"));
    } finally {
      setBusy(false);
    }
  }

  if (!token) {
    return (
      <AuthCard title="Invalid recovery link" subtitle="Open the link from your email again." footer={<AuthLink href="/forgot-password">Request a new link</AuthLink>}>
        <Notice tone="error">This page is missing its single-use token. A fresh request can be made from the forgot-password page.</Notice>
      </AuthCard>
    );
  }

  if (done) {
    return (
      <AuthCard title="Password reset" subtitle="Your password was updated successfully." footer={<AuthLink href="/login">← Back to sign in</AuthLink>}>
        <Notice tone="success" title="Success">
          Your password was updated and all existing sessions were revoked. For your security, you were not signed in automatically. Use the new password on the login page.
        </Notice>
        <div className="mt-5">
          <AuthLink href="/login?reset=1">Continue to sign in →</AuthLink>
        </div>
      </AuthCard>
    );
  }

  return (
    <AuthCard
      title="Choose a new password"
      subtitle="This recovery link works once and expires in 15 minutes."
      footer={<AuthLink href="/login">← Back to sign in</AuthLink>}
    >
      {error && <div className="mb-4"><Notice tone="error" title="Could not reset password">{error}</Notice></div>}
      <form onSubmit={onSubmit} className="space-y-4" noValidate>
        <PasswordField
          id="reset-password"
          label="New password"
          autoComplete="new-password"
          value={password}
          onChange={setPassword}
          showStrength
          disabled={busy}
        />
        <PasswordField
          id="reset-confirm"
          label="Confirm new password"
          autoComplete="new-password"
          value={confirm}
          onChange={setConfirm}
          error={confirm && confirm !== password ? "Passwords do not match" : undefined}
          disabled={busy}
        />
        <PasswordRequirements password={password} />
        <PrimaryButton busy={busy}>{busy ? "Updating…" : "Update password"}</PrimaryButton>
      </form>
      <p className="mt-4 text-center text-[11px] leading-relaxed text-fgmuted/70">
        Old sessions are revoked. The backend validates token expiry and single-use status before any password change.
      </p>
    </AuthCard>
  );
}

export default function ResetPasswordPage() {
  return (
    <Suspense fallback={<p className="text-body text-fgmuted">Loading…</p>}>
      <ResetForm />
    </Suspense>
  );
}
