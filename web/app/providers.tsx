"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useState } from "react";

export function Providers({ children }: { children: React.ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: { retry: 1, refetchOnWindowFocus: false, staleTime: 15_000 },
        },
      }),
  );

  useEffect(() => {
    // Restore the saved theme without a flash of the wrong palette.
    const saved = localStorage.getItem("armx.theme");
    const root = document.documentElement;
    root.classList.remove("dark", "light");
    root.classList.add(saved === "light" ? "light" : "dark");
  }, []);

  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
