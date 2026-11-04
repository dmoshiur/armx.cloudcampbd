"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { api, tokenStore } from "@/lib/api/client";
import type { TokenPair, User } from "@/lib/types";

const USER_KEY = "armx.user";

export interface LoginInput {
  email: string;
  password: string;
  remember_me?: boolean;
}

export interface RegisterInput {
  full_name: string;
  email: string;
  password: string;
  confirm_password: string;
  terms_accepted: boolean;
  remember_me?: boolean;
}

export function useAuth() {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(() => {
    if (typeof window === "undefined") return null;
    try {
      const cached = localStorage.getItem(USER_KEY);
      return cached ? (JSON.parse(cached) as User) : null;
    } catch {
      return null;
    }
  });
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      // The cookie is the source of truth. Older localStorage tokens are only
      // used by the API client for one legacy refresh migration.
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
    async (input: LoginInput) => {
      await api.post<TokenPair>("/auth/login", {
        email: input.email,
        password: input.password,
        remember_me: Boolean(input.remember_me),
      });
      // Do not store tokens: the server set HttpOnly cookies on the response.
      return load();
    },
    [load],
  );

  const register = useCallback(
    async (input: RegisterInput) => {
      await api.post<TokenPair>("/auth/register", input);
      return load();
    },
    [load],
  );

  const logout = useCallback(async () => {
    try {
      await api.post("/auth/logout", {});
    } catch {
      /* the session may already be gone; cookies are still cleared below */
    }
    tokenStore.clear();
    localStorage.removeItem(USER_KEY);
    setUser(null);
    router.push("/login");
  }, [router]);

  return { user, loading, login, register, logout, refreshUser: load };
}

export function useRequireAuth(redirectTo = "/login") {
  const router = useRouter();
  const { user, loading } = useAuth();
  useEffect(() => {
    if (loading || user) return;
    const current =
      typeof window === "undefined" ? "/" : `${window.location.pathname}${window.location.search}`;
    const destination = current.startsWith("/") && !current.startsWith("//") ? current : "/";
    router.replace(`${redirectTo}?next=${encodeURIComponent(destination)}`);
  }, [loading, user, router, redirectTo]);
  return { user, loading };
}
