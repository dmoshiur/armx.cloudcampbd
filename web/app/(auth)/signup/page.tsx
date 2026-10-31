"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useAuth } from "@/lib/hooks/useAuth";
import { Button, FieldError, Input, Label } from "@/components/ui/primitives";

export default function SignupPage() {
  const router = useRouter();
  const { signup } = useAuth();
  const [form, setForm] = useState({ display_name: "", email: "", password: "", confirm: "" });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const problems: string[] = [];
  if (form.password && form.password.length < 10) problems.push("at least 10 characters");
  if (form.password && form.password.toLowerCase() === form.password) problems.push("an uppercase letter");
  if (form.password && /^[A-Za-z0-9]+$/.test(form.password)) problems.push("a symbol");

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    if (form.password !== form.confirm) {
      setError("Passwords do not match");
      return;
    }
    setBusy(true);
    try {
      await signup(form.email, form.password, form.display_name);
      router.push("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create the account");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <h2 className="text-h1">Create your account</h2>
      <p className="mt-1.5 text-body text-fgmuted">
        New accounts start as <span className="text-fg">user</span>. An administrator can upgrade you to VIP for
        device linking.
      </p>

      <form onSubmit={onSubmit} className="mt-6 space-y-4" noValidate>
        <div>
          <Label htmlFor="name">Display name</Label>
          <Input id="name" autoComplete="name" value={form.display_name} onChange={(e) => setForm({ ...form, display_name: e.target.value })} placeholder="Amina Rahman" />
        </div>
        <div>
          <Label htmlFor="email">Email</Label>
          <Input id="email" type="email" autoComplete="email" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} placeholder="you@example.com" />
        </div>
        <div>
          <Label htmlFor="password" hint={problems.length ? `needs ${problems.join(", ")}` : "min 10 characters"}>
            Password
          </Label>
          <Input id="password" type="password" autoComplete="new-password" required value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
        </div>
        <div>
          <Label htmlFor="confirm">Confirm password</Label>
          <Input id="confirm" type="password" autoComplete="new-password" required value={form.confirm} onChange={(e) => setForm({ ...form, confirm: e.target.value })} />
          <FieldError>{error}</FieldError>
        </div>
        <Button type="submit" className="w-full" loading={busy}>
          Create account
        </Button>
      </form>

      <p className="mt-6 text-caption text-fgmuted">
        Already have an account?{" "}
        <Link href="/login" className="text-accent hover:underline">
          Sign in
        </Link>
      </p>
    </>
  );
}
