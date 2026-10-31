"use client";

import { AppShell } from "@/components/app/shell";
import { useRequireAuth } from "@/lib/hooks/useAuth";
import { Spinner } from "@/components/ui/primitives";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const { user, loading } = useRequireAuth();

  if (loading) {
    return (
      <div className="grid min-h-screen place-items-center">
        <div className="flex items-center gap-3 text-body text-fgmuted">
          <Spinner /> Loading your workspace…
        </div>
      </div>
    );
  }
  if (!user) return null;

  return <AppShell>{children}</AppShell>;
}
