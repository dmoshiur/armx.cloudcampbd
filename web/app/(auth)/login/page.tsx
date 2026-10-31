"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import { useAuth } from "@/lib/hooks/useAuth";
import { Button, FieldError, Input, Label } from "@/components/ui/primitives";

const ERRORS: Record<string, string> = {
  google_cancelled: "Google sign-in was cancelled.",
  google_token: "Google did not return a token. Try again.",
  google_profile: "Could not read your Google profile.",
  google_unverified: "Your Google email is not verified.",
  state_mismatch: "The sign-in request expired. Try again.",
  state_invalid: "The sign-in request could not be verified.",
};

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const { login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const code = params.get("error");
    if (code) setError(ERRORS[code] ?? "Sign-in failed. Try again.");
    if (params.get("reset") === "1") setNotice("Password updated. Sign in with your new password.");
    if (params.get("verified") === "1") setNotice("Email verified. You can sign in now.");
  }, [params]);

  const { data: config } = useQuery({
    queryKey: ["config"],
    queryFn: () => api.get<{ features: { google_login: boolean } }>("/config"),
    staleTime: Infinity,
  });

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await login(email, password);
      router.push("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not sign in");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <h2 className="text-h1">Sign in</h2>
      <p className="mt-1.5 text-body text-fgmuted">Welcome back to A.R.M.X AI.</p>

      {notice && (
        <p role="status" className="mt-4 rounded-md border border-success/40 bg-success/10 px-3 py-2 text-body text-success">
          {notice}
        </p>
      )}

      <form onSubmit={onSubmit} className="mt-6 space-y-4" noValidate>
        <div>
          <Label htmlFor="email">Email</Label>
          <Input id="email" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" />
        </div>
        <div>
          <Label htmlFor="password" hint="min 10 characters">Password</Label>
          <Input id="password" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} placeholder="••••••••••" />
          <FieldError>{error}</FieldError>
        </div>
        <Button type="submit" className="w-full" loading={busy}>
          Sign in
        </Button>
      </form>

      {config?.features.google_login && (
        <>
          <div className="my-5 flex items-center gap-3 text-caption text-fgmuted">
            <span className="h-px flex-1 bg-edge" />
            or
            <span className="h-px flex-1 bg-edge" />
          </div>
          <a
            href="/api/auth/google/start"
            className="flex min-h-touch w-full items-center justify-center gap-2 rounded-md border border-edge px-4 text-body font-semibold transition hover:bg-white/5"
          >
            Continue with Google
          </a>
        </>
      )}

      <div className="mt-6 flex flex-wrap justify-between gap-2 text-caption text-fgmuted">
        <Link href="/forgot-password" className="hover:text-fg">
          Forgot your password?
        </Link>
        <Link href="/signup" className="hover:text-fg">
          Create an account
        </Link>
      </div>
    </>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={<p className="text-body text-fgmuted">Loading…</p>}>
      <LoginForm />
    </Suspense>
  );
}
