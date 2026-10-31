"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { api, tokenStore } from "@/lib/api/client";
import type { TokenPair, User } from "@/lib/types";

const USER_KEY = "armx.user";

export function useAuth() {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    if (!tokenStore.access() && !tokenStore.refresh()) {
      setLoading(false);
      setUser(null);
      return null;
    }
    try {
      const me = await api.get<User>("/auth/me");
      setUser(me);
      localStorage.setItem(USER_KEY, JSON.stringify(me));
      return me;
    } catch {
      tokenStore.clear();
      localStorage.removeItem(USER_KEY);
      setUser(null);
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const login = useCallback(
    async (email: string, password: string) => {
      const tokens = await api.post<TokenPair>("/auth/login", { email, password });
      tokenStore.set(tokens.access_token, tokens.refresh_token);
      return load();
    },
    [load],
  );

  const signup = useCallback(
    async (email: string, password: string, display_name: string) => {
      const tokens = await api.post<TokenPair>("/auth/signup", { email, password, display_name });
      tokenStore.set(tokens.access_token, tokens.refresh_token);
      return load();
    },
    [load],
  );

  const logout = useCallback(async () => {
    try {
      await api.post("/auth/logout");
    } catch {
      /* the session may already be gone */
    }
    tokenStore.clear();
    localStorage.removeItem(USER_KEY);
    setUser(null);
    router.push("/login");
  }, [router]);

  return { user, loading, login, signup, logout, refreshUser: load };
}

export function useRequireAuth(redirectTo = "/login") {
  const router = useRouter();
  const { user, loading } = useAuth();
  useEffect(() => {
    if (!loading && !user) router.replace(redirectTo);
  }, [loading, user, router, redirectTo]);
  return { user, loading };
}
