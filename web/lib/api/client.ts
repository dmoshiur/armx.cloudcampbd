"use client";

/**
 * One typed API client. The browser never talks to the backend directly: every
 * request goes to this origin (/api/...), which Next.js proxies to FastAPI.
 *
 * Access tokens are short-lived; on a 401 we refresh once, rotate the pair and
 * replay the request. Refresh reuse is detected server-side and revokes the
 * session family, so a stolen token cannot be silently revved forever.
 */
const ACCESS_KEY = "armx.access";
const REFRESH_KEY = "armx.refresh";
const API = "/api";

export class ApiError extends Error {
  status: number;
  code?: string;
  detail?: unknown;
  constructor(message: string, status: number, code?: string, detail?: unknown) {
    super(message);
    this.status = status;
    this.code = code;
    this.detail = detail;
  }
}

export const tokenStore = {
  access(): string | null {
    if (typeof window === "undefined") return null;
    return localStorage.getItem(ACCESS_KEY);
  },
  refresh(): string | null {
    if (typeof window === "undefined") return null;
    return localStorage.getItem(REFRESH_KEY);
  },
  set(access: string, refresh: string) {
    localStorage.setItem(ACCESS_KEY, access);
    localStorage.setItem(REFRESH_KEY, refresh);
  },
  clear() {
    localStorage.removeItem(ACCESS_KEY);
    localStorage.removeItem(REFRESH_KEY);
  },
};

let refreshing: Promise<boolean> | null = null;

async function refreshOnce(): Promise<boolean> {
  if (refreshing) return refreshing;
  const refresh = tokenStore.refresh();
  if (!refresh) return false;
  refreshing = (async () => {
    try {
      const res = await fetch(`${API}/auth/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: refresh }),
      });
      if (!res.ok) {
        tokenStore.clear();
        return false;
      }
      const data = await res.json();
      tokenStore.set(data.access_token, data.refresh_token);
      return true;
    } catch {
      return false;
    } finally {
      refreshing = null;
    }
  })();
  return refreshing;
}

function messageFrom(payload: unknown, fallback: string): string {
  if (!payload || typeof payload !== "object") return fallback;
  const detail = (payload as { detail?: unknown }).detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d) => (typeof d === "object" && d && "msg" in d ? String((d as { msg: string }).msg) : String(d)))
      .join(", ");
  }
  if (detail && typeof detail === "object" && "detail" in detail) return String((detail as { detail: string }).detail);
  return fallback;
}

export async function request<T>(
  path: string,
  options: RequestInit & { auth?: boolean; raw?: boolean } = {},
): Promise<T> {
  const { auth = true, headers, ...rest } = options;
  const send = async (): Promise<Response> => {
    const h: Record<string, string> = { ...(headers as Record<string, string>) };
    if (!(rest.body instanceof FormData)) h["Content-Type"] = "application/json";
    const token = auth ? tokenStore.access() : null;
    if (token) h["Authorization"] = `Bearer ${token}`;
    return fetch(`${API}${path}`, { ...rest, headers: h });
  };

  let res = await send();
  if (res.status === 401 && auth && (await refreshOnce())) {
    res = await send();
  }

  if (res.status === 204) return undefined as T;

  const text = await res.text();
  let payload: unknown = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = text;
    }
  }

  if (!res.ok) {
    const code =
      payload && typeof payload === "object" && "code" in payload ? String((payload as { code: string }).code) : undefined;
    throw new ApiError(messageFrom(payload, res.statusText), res.status, code, payload);
  }
  return payload as T;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) }),
  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "PATCH", body: body === undefined ? undefined : JSON.stringify(body) }),
  del: <T>(path: string) => request<T>(path, { method: "DELETE" }),
  upload: <T>(path: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<T>(path, { method: "POST", body: form });
  },
};
