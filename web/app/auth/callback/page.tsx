"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { useAuth } from "@/lib/hooks/useAuth";
import { AuthCard, AuthLink, Notice } from "@/components/auth/auth-ui";

function AuthCallbackInner() {
  const router = useRouter();
  const params = useSearchParams();
  const { refreshUser } = useAuth();
  const [failed, setFailed] = useState(false);
  const [message, setMessage] = useState("Finishing sign-in…");

  useEffect(() => {
    const google = params.get("google") === "1";
    // Legacy fragment hand-off is still scrubbed for sessions started before
    // the cookie migration. No token is stored in localStorage.
    const hash = window.location.hash.replace(/^#/, "");
    const legacy = new URLSearchParams(hash);
    if (legacy.get("access_token") || legacy.get("refresh_token")) {
      window.history.replaceState(null, "", "/auth/callback");
    }
    if (!google && !legacy.get("access_token")) {
      setFailed(true);
      setMessage("No sign-in callback was found. Start again from the login page.");
      return;
    }
    void refreshUser().then((user) => {
      if (!user) {
        setFailed(true);
        setMessage("The provider did not establish a valid A.R.M.X AI session.");
        return;
      }
      router.replace("/");
    });
  }, [params, refreshUser, router]);

  const card = failed ? (
    <AuthCard title="Sign-in could not be completed" subtitle={message} footer={<AuthLink href="/login">Back to sign in</AuthLink>}>
      <Notice tone="error">No usable session cookie was returned. Check the provider configuration and try again.</Notice>
    </AuthCard>
  ) : (
    <AuthCard title="Finishing sign-in" subtitle="Establishing your secure session…">
      <div className="flex items-center justify-center gap-3 py-5 text-body text-fgmuted">
        <span className="h-4 w-4 animate-spin rounded-full border-2 border-accent border-t-transparent" /> {message}
      </div>
    </AuthCard>
  );
  return <div className="auth-page flex min-h-[100dvh] items-center justify-center px-4 py-8"><div className="auth-grid" aria-hidden="true" /><div className="relative z-10 w-full max-w-[420px]">{card}</div></div>;
}

export default function AuthCallbackPage() {
  return (
    <Suspense fallback={<p className="text-body text-fgmuted">Loading…</p>}>
      <AuthCallbackInner />
    </Suspense>
  );
}
