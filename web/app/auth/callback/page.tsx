"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { tokenStore } from "@/lib/api/client";
import { Spinner } from "@/components/ui/primitives";

/** Google OAuth hand-off: tokens arrive in the URL fragment, then are scrubbed. */
export default function AuthCallbackPage() {
  const router = useRouter();
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const hash = window.location.hash.replace(/^#/, "");
    const params = new URLSearchParams(hash);
    const access = params.get("access_token");
    const refresh = params.get("refresh_token");
    if (!access || !refresh) {
      setFailed(true);
      return;
    }
    tokenStore.set(access, refresh);
    // Remove the tokens from the address bar and history before navigating.
    window.history.replaceState(null, "", "/auth/callback");
    router.replace("/");
  }, [router]);

  return (
    <div className="grid min-h-screen place-items-center px-6">
      {failed ? (
        <div className="text-center">
          <h1 className="text-h2">Sign-in could not be completed</h1>
          <p className="mt-2 text-body text-fgmuted">The provider did not return usable credentials.</p>
          <a href="/login" className="mt-4 inline-block text-accent hover:underline">
            Back to sign in
          </a>
        </div>
      ) : (
        <div className="flex items-center gap-3 text-body text-fgmuted">
          <Spinner /> Finishing sign-in…
        </div>
      )}
    </div>
  );
}
