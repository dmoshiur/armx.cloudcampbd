"use client";

import Link from "next/link";
import { useState } from "react";
import { api } from "@/lib/api/client";
import { Button, Input, Label } from "@/components/ui/primitives";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    try {
      await api.post("/auth/forgot-password", { email });
    } finally {
      setBusy(false);
      setSent(true);
    }
  }

  if (sent) {
    return (
      <>
        <h2 className="text-h1">Check your email</h2>
        <p className="mt-3 text-body text-fgmuted">
          If an account exists for <span className="text-fg">{email}</span>, a single-use reset link is on its way.
          It expires in 20 minutes.
        </p>
        <Link href="/login" className="mt-6 inline-block text-body text-accent hover:underline">
          Back to sign in
        </Link>
      </>
    );
  }

  return (
    <>
      <h2 className="text-h1">Reset your password</h2>
      <p className="mt-1.5 text-body text-fgmuted">We will email you a single-use link.</p>
      <form onSubmit={onSubmit} className="mt-6 space-y-4">
        <div>
          <Label htmlFor="email">Email</Label>
          <Input id="email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" />
        </div>
        <Button type="submit" className="w-full" loading={busy}>
          Send reset link
        </Button>
      </form>
      <Link href="/login" className="mt-6 inline-block text-caption text-fgmuted hover:text-fg">
        Back to sign in
      </Link>
    </>
  );
}
