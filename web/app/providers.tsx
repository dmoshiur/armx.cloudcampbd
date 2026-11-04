"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { PreferencesProvider } from "@/lib/preferences";

export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: { retry: 1, refetchOnWindowFocus: false, staleTime: 15_000 },
        },
      }),
  );

  return (
    <QueryClientProvider client={client}>
      <PreferencesProvider>{children}</PreferencesProvider>
    </QueryClientProvider>
  );
}
