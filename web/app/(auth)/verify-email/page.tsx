"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { api } from "@/lib/api/client";
import { Button, Spinner } from "@/components/ui/primitives";

function VerifyInner() {
  const token = useSearchParams().get("token");
  const [state, setState] = useState<"pending" | "ok" | "error">("pending");
  const [message, setMessage] = useState("");

  useEffect(() => {
    if (!token) {
      setState("error");
      setMessage("This link is missing its token.");
      return;
    }
    api
      .get<{ status: string }>(`/auth/verify-email?token=${encodeURIComponent(token)}`)
      .then(() => setState("ok"))
      .catch((err) => {
        setState("error");
        setMessage(err instanceof Error ? err.message : "Verification failed");
      });
  }, [token]);

  if (state === "pending") {
    return (
      <div className="flex items-center gap-3 text-body text-fgmuted">
        <Spinner /> Verifying your email…
      </div>
    );
  }

  return (
    <>
      <h2 className="text-h1">{state === "ok" ? "Email verified" : "Verification failed"}</h2>
      <p className="mt-2 text-body text-fgmuted">
        {state === "ok" ? "Your account is ready. You can sign in now." : message}
      </p>
      <Link href={state === "ok" ? "/login?verified=1" : "/login"} className="mt-6 inline-block">
        <Button>{state === "ok" ? "Sign in" : "Back to sign in"}</Button>
      </Link>
    </>
  );
}

export default function VerifyEmailPage() {
  return (
    <Suspense fallback={<Spinner />}>
      <VerifyInner />
    </Suspense>
  );
}
