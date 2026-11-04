"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { describeError, request } from "@/lib/api/client";
import { useAuth } from "@/lib/hooks/useAuth";
import {
  AuthCard,
  AuthFooterLinks,
  AuthLink,
  Notice,
  PasswordField,
  PasswordRequirements,
  PrimaryButton,
  TextField,
  passwordScore,
} from "@/components/auth/auth-ui";

export default function RegisterPage() {
  const router = useRouter();
  const { register } = useAuth();
  const [form, setForm] = useState({
    full_name: "",
    email: "",
    password: "",
    confirm_password: "",
    terms_accepted: false,
    remember_me: false,
  });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const { data: config } = useQuery({
    queryKey: ["config", "register"],
    queryFn: () =>
      request<{ features: { email_verification_required: boolean } }>("/config", { auth: false }),
    staleTime: Infinity,
    retry: false,
  });

  const update = (patch: Partial<typeof form>) => setForm((prev) => ({ ...prev, ...patch }));

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    if (!form.full_name.trim()) return setError("Enter your full name.");
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(form.email.trim())) return setError("Enter a valid email address.");
    if (passwordScore(form.password) < 3) return setError("Choose a stronger password that meets every requirement below.");
    if (form.password !== form.confirm_password) return setError("Passwords do not match.");
    if (!form.terms_accepted) return setError("Accept the terms to create your account.");

    setBusy(true);
    try {
      await register({
        full_name: form.full_name.trim(),
        email: form.email.trim(),
        password: form.password,
        confirm_password: form.confirm_password,
        terms_accepted: true,
        remember_me: form.remember_me,
      });
      const email = encodeURIComponent(form.email.trim());
      if (config?.features.email_verification_required) {
        router.push(`/verify-email?sent=1&email=${email}`);
      } else {
        router.push(`/verify-email?sent=1&email=${email}&optional=1`);
      }
    } catch (err) {
      setError(describeError(err, "create your account"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthCard
      title="Create your account"
      subtitle="New accounts start with user permissions. Admin access is never granted automatically."
      footer={
        <AuthFooterLinks>
          Already have an account? <AuthLink href="/login">Sign in</AuthLink>
        </AuthFooterLinks>
      }
    >
      {error && <div className="mb-4"><Notice tone="error" title="Registration failed">{error}</Notice></div>}
      <form onSubmit={onSubmit} className="space-y-3.5" noValidate>
        <TextField
          id="register-name"
          label="Full name"
          autoComplete="name"
          placeholder="Md. Moshiur Rahman"
          value={form.full_name}
          onChange={(value) => update({ full_name: value })}
          disabled={busy}
        />
        <TextField
          id="register-email"
          label="Email address"
          type="email"
          autoComplete="email"
          placeholder="you@example.com"
          value={form.email}
          onChange={(value) => update({ email: value })}
          disabled={busy}
        />
        <PasswordField
          id="register-password"
          label="Password"
          autoComplete="new-password"
          value={form.password}
          onChange={(value) => update({ password: value })}
          showStrength
          disabled={busy}
        />
        <PasswordField
          id="register-confirm"
          label="Confirm password"
          autoComplete="new-password"
          value={form.confirm_password}
          onChange={(value) => update({ confirm_password: value })}
          error={form.confirm_password && form.confirm_password !== form.password ? "Passwords do not match" : undefined}
          disabled={busy}
        />
        <PasswordRequirements password={form.password} />
        <label className="flex cursor-pointer items-start gap-2.5 rounded-lg border border-edge/70 bg-bg/45 p-3 text-caption text-fgmuted">
          <input
            type="checkbox"
            checked={form.terms_accepted}
            onChange={(event) => update({ terms_accepted: event.target.checked })}
            className="mt-0.5 h-4 w-4 shrink-0 rounded border-edge bg-bg accent-accent"
          />
          <span>
            I accept the A.R.M.X AI terms and acknowledge that high-risk tool actions require explicit approval.
            A verification email will be sent to this address.
          </span>
        </label>
        <label className="flex cursor-pointer items-center gap-2 text-caption text-fgmuted">
          <input
            type="checkbox"
            checked={form.remember_me}
            onChange={(event) => update({ remember_me: event.target.checked })}
            className="h-4 w-4 rounded border-edge bg-bg accent-accent"
          />
          Keep me signed in on this device
        </label>
        <PrimaryButton busy={busy}>{busy ? "Creating account…" : "Create account"}</PrimaryButton>
      </form>
    </AuthCard>
  );
}
