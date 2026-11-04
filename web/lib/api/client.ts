"use client";

/**
 * Cookie-first API client. The browser sends HttpOnly SameSite auth cookies and
 * a readable double-submit CSRF header. Legacy bearer tokens stored by older
 * releases are still read for one migration/refresh cycle but new tokens are
 * never written to localStorage. Every failure becomes an actionable ApiError
 * with a correlation ID.
 */
const ACCESS_KEY = "armx.access";
const REFRESH_KEY = "armx.refresh";
const USER_KEY = "armx.user";
const API = "/api";
const CSRF_COOKIE = "armx_csrf";

export class ApiError extends Error {
  status: number;
  code: string;
  detail?: unknown;
  requestId?: string;
  hint?: string;
  retryable: boolean;
  canRetry: boolean;

  constructor(
    message: string,
    status: number,
    code: string,
    detail?: unknown,
    requestId?: string,
    hint?: string,
    retryable = false,
    canRetry = false,
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.detail = detail;
    this.requestId = requestId;
    this.hint = hint;
    this.retryable = retryable;
    this.canRetry = canRetry;
  }
}

/** Legacy migration helper only. New sessions do not use localStorage tokens. */
export const tokenStore = {
  access(): string | null {
    if (typeof window === "undefined") return null;
    return localStorage.getItem(ACCESS_KEY);
  },
  refresh(): string | null {
    if (typeof window === "undefined") return null;
    return localStorage.getItem(REFRESH_KEY);
  },
  clear() {
    if (typeof window === "undefined") return;
    localStorage.removeItem(ACCESS_KEY);
    localStorage.removeItem(REFRESH_KEY);
    localStorage.removeItem(USER_KEY);
  },
};

function readCookie(name: string): string {
  if (typeof document === "undefined") return "";
  for (const part of document.cookie.split(";")) {
    const [key, ...rest] = part.trim().split("=");
    if (key === name) return decodeURIComponent(rest.join("="));
  }
  return "";
}

let csrfPromise: Promise<string> | null = null;

async function ensureCsrf(): Promise<string> {
  const current = readCookie(CSRF_COOKIE);
  if (current) return current;
  if (!csrfPromise) {
    csrfPromise = fetch(`${API}/auth/csrf`, { credentials: "include" })
      .then(async (res) => {
        if (!res.ok) return "";
        const data = (await res.json()) as { csrf_token?: string };
        return data.csrf_token || readCookie(CSRF_COOKIE);
      })
      .catch(() => "")
      .finally(() => {
        csrfPromise = null;
      });
  }
  return csrfPromise;
}

let refreshing: Promise<boolean> | null = null;

async function refreshOnce(): Promise<boolean> {
  if (refreshing) return refreshing;
  refreshing = (async () => {
    const attempt = async (body: string): Promise<Response> =>
      fetch(`${API}/auth/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body,
        credentials: "include",
      });
    // Prefer the HttpOnly cookie. Only fall back to a legacy localStorage
    // refresh token when no cookie session exists; then remove it permanently.
    let res = await attempt("{}");
    const legacy = tokenStore.refresh();
    if (res.status === 401 && legacy) {
      res = await attempt(JSON.stringify({ refresh_token: legacy }));
    }
    if (!res.ok) {
      tokenStore.clear();
      return false;
    }
    tokenStore.clear();
    return true;
  })().finally(() => {
    refreshing = null;
  });
  return refreshing;
}

interface ErrorPayload {
  detail?: unknown;
  code?: string;
  hint?: string;
  request_id?: string;
  retryable?: boolean;
  can_retry?: boolean;
}

function parsePayload(payload: unknown): ErrorPayload {
  if (!payload || typeof payload !== "object") return {};
  const top = payload as Record<string, unknown>;
  if (top.detail && typeof top.detail === "object") {
    const nested = top.detail as Record<string, unknown>;
    return {
      detail: nested.detail ?? nested.message ?? top.detail,
      code: String(nested.code ?? top.code ?? ""),
      hint: nested.hint ? String(nested.hint) : undefined,
      request_id: String(nested.request_id ?? top.request_id ?? ""),
      retryable: Boolean(nested.retryable ?? top.retryable),
      can_retry: Boolean(nested.can_retry ?? top.can_retry),
    };
  }
  return {
    detail: top.detail,
    code: top.code ? String(top.code) : "",
    hint: top.hint ? String(top.hint) : undefined,
    request_id: top.request_id ? String(top.request_id) : "",
    retryable: Boolean(top.retryable),
    can_retry: Boolean(top.can_retry),
  };
}

const FALLBACK_BY_STATUS: Record<number, string> = {
  400: "The request was rejected as invalid. Check the fields and try again.",
  401: "Your session expired. Sign in again to continue.",
  403: "This action is not permitted for your account or was blocked by the security gateway.",
  404: "The requested resource was not found. It may have been deleted or moved.",
  409: "The request conflicts with the current state. Refresh and try again.",
  410: "This resource is no longer available. Start a new request.",
  413: "The upload is too large for this server.",
  415: "This file type is not accepted.",
  429: "Rate limit reached. Wait a moment before trying again.",
  500: "The server hit an internal error. The request ID below matches the backend log.",
  502: "The API gateway could not reach the backend service.",
  503: "The service is temporarily unavailable. Check system health and retry.",
  504: "The request timed out before the backend answered. Check the audit log before retrying an action.",
};

function messageFrom(payload: unknown, status: number, statusText: string): string {
  const parsed = parsePayload(payload);
  const detail = parsed.detail;
  if (typeof detail === "string" && detail.trim()) return detail.trim();
  if (Array.isArray(detail)) {
    return detail
      .map((d) => (typeof d === "object" && d && "msg" in d ? String((d as { msg: string }).msg) : String(d)))
      .join(", ");
  }
  if (typeof payload === "string" && payload.trim()) {
    return `The server returned ${status} ${statusText || "without a structured error"}: ${payload.trim().slice(0, 180)}`;
  }
  return FALLBACK_BY_STATUS[status] ?? "The request could not be completed. Please try again.";
}

export function describeError(err: unknown, context = "request"): string {
  if (err instanceof ApiError) {
    const parts = [err.message || FALLBACK_BY_STATUS[err.status] || `The ${context} failed.`];
    if (err.hint) parts.push(err.hint);
    if (err.requestId) parts.push(`Request ID: ${err.requestId}`);
    else parts.push("No server response was received, so there is no request ID.");
    return parts.join(" ");
  }
  if (err instanceof DOMException && err.name === "AbortError") {
    return `The ${context} was cancelled or timed out. No server request ID was returned.`;
  }
  return `Could not reach the A.R.M.X service while trying to ${context}. Check your connection and the /api/health endpoint.`;
}

function buildError(payload: unknown, res: Response, fallbackStatus = 0): ApiError {
  const parsed = parsePayload(payload);
  const status = res.status || fallbackStatus;
  const requestId = res.headers.get("X-Request-ID") || parsed.request_id || undefined;
  return new ApiError(
    messageFrom(payload, status, res.statusText),
    status,
    parsed.code || `http_${status}`,
    payload,
    requestId,
    parsed.hint,
    parsed.retryable || [429, 502, 503, 504].includes(status),
    parsed.can_retry,
  );
}

export async function request<T>(
  path: string,
  options: RequestInit & { auth?: boolean } = {},
): Promise<T> {
  const { auth = true, headers, method, ...rest } = options;
  const verb = (method || "GET").toUpperCase();
  const unsafe = ["POST", "PUT", "PATCH", "DELETE"].includes(verb);
  const csrf = unsafe && path !== "/auth/csrf" ? await ensureCsrf() : "";
  const h: Record<string, string> = {
    ...(headers as Record<string, string>),
    "X-Requested-With": "ARMX",
  };
  if (!(rest.body instanceof FormData)) h["Content-Type"] = "application/json";
  if (csrf) h["X-CSRF-Token"] = csrf;
  const legacy = auth ? tokenStore.access() : null;
  if (legacy) h["Authorization"] = `Bearer ${legacy}`;

  const send = async (): Promise<Response> =>
    fetch(`${API}${path}`, { ...rest, method: verb, headers: h, credentials: "include" });

  let res: Response;
  try {
    res = await send();
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    throw new ApiError(
      "Could not reach the A.R.M.X service. Check the network, the /api/health endpoint and the deployment proxy.",
      0,
      "network_unavailable",
      undefined,
      undefined,
      "No server response was received. If the app is deployed on Render, check the service logs for this time.",
      true,
    );
  }

  const noRefresh = path.startsWith("/auth/login") || path.startsWith("/auth/refresh");
  if (res.status === 401 && auth && !noRefresh && (await refreshOnce())) {
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
  if (!res.ok) throw buildError(payload, res);
  return payload as T;
}

/** Parse an SSE stream from a cookie-authenticated POST request. */
export async function* streamSSE<T extends Record<string, unknown>>(
  path: string,
  body: unknown,
  signal?: AbortSignal,
): AsyncGenerator<T> {
  const csrf = await ensureCsrf();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    "X-Requested-With": "ARMX",
    "X-CSRF-Token": csrf,
  };
  const legacy = tokenStore.access();
  if (legacy) headers["Authorization"] = `Bearer ${legacy}`;
  let res = await fetch(`${API}${path}`, {
    method: "POST",
    headers,
    body: JSON.stringify(body ?? {}),
    signal,
    credentials: "include",
  });
  if (res.status === 401 && (await refreshOnce())) {
    res = await fetch(`${API}${path}`, {
      method: "POST",
      headers,
      body: JSON.stringify(body ?? {}),
      signal,
      credentials: "include",
    });
  }
  if (!res.ok) {
    const raw = await res.text();
    let parsed: unknown = raw;
    try {
      parsed = JSON.parse(raw);
    } catch {
      /* keep raw text */
    }
    throw buildError(parsed, res);
  }
  if (!res.body) {
    throw new ApiError(
      "This browser or proxy did not expose the streaming response body. Use Send without streaming instead.",
      0,
      "stream_unsupported",
      undefined,
      undefined,
      "Try the non-streaming Send button; the /api/assistant/chat endpoint returns the same result.",
      true,
    );
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const chunks = buffer.split("\n\n");
      buffer = chunks.pop() ?? "";
      for (const chunk of chunks) {
        const line = chunk.split("\n").find((l) => l.startsWith("data:"));
        if (!line) continue;
        try {
          yield JSON.parse(line.slice(5).trim()) as T;
        } catch {
          // Ignore a malformed event rather than breaking the whole stream.
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown, options: RequestInit = {}) =>
    request<T>(path, { ...options, method: "POST", body: body === undefined ? undefined : JSON.stringify(body) }),
  put: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "PUT", body: body === undefined ? undefined : JSON.stringify(body) }),
  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "PATCH", body: body === undefined ? undefined : JSON.stringify(body) }),
  del: <T>(path: string) => request<T>(path, { method: "DELETE" }),
  upload: async <T>(path: string, file: File, signal?: AbortSignal): Promise<T> => {
    const form = new FormData();
    form.append("file", file);
    return request<T>(path, { method: "POST", body: form, signal });
  },
  stream: streamSSE,
  blob: async (path: string): Promise<Blob | null> => {
    const send = () => {
      const legacy = tokenStore.access();
      return fetch(`${API}${path}`, {
        cache: "no-store",
        credentials: "include",
        headers: legacy ? { Authorization: `Bearer ${legacy}` } : {},
      });
    };
    let response = await send();
    if (response.status === 401 && (await refreshOnce())) response = await send();
    if (response.status === 204) return null;
    if (!response.ok) {
      const raw = await response.text();
      let parsed: unknown = raw;
      try {
        parsed = JSON.parse(raw);
      } catch {
        /* keep raw text */
      }
      throw buildError(parsed, response);
    }
    return response.blob();
  },
};
