import type { ReactNode } from "react";
import { AuthBrand } from "@/components/auth/auth-ui";

export default function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <div className="auth-page">
      <div className="auth-grid" aria-hidden="true" />
      <div className="auth-glow" aria-hidden="true" />
      <main className="relative z-10 flex min-h-[100dvh] w-full flex-col items-center justify-center px-4 py-8 sm:px-6">
        <AuthBrand />
        {children}
        <p className="mt-6 max-w-[420px] text-center text-[11px] leading-relaxed text-fgmuted/60">
          Secure access to A.R.M.X AI · Protected by HttpOnly sessions, single-use recovery links and server-side authorization.
        </p>
      </main>
    </div>
  );
}
