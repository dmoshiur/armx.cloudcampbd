"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, request } from "@/lib/api/client";
import { usePreferences } from "@/lib/preferences";
import type { MatrixStatus } from "@/lib/types";

/**
 * Full-viewport Matrix rain.
 *
 * Primary renderer: the ORIGINAL GPL-3.0 `cmatrix` executable running in a
 * backend PTY. Its ncurses terminal frames arrive over an authenticated
 * WebSocket (or SSE where upgrades are blocked) and are painted onto a canvas.
 * Fallback: the vendored MIT jcubic/cmatrix JavaScript port, clearly labelled.
 * Neither path pretends the other succeeded.
 */

type Mode = "connecting" | "pty" | "port" | "reduced" | "disabled";

interface FrameEvent {
  type: string;
  lines?: string[];
  intensity?: string[];
  cols?: number;
  rows?: number;
  detail?: string;
  status?: MatrixStatus;
}

export function CMatrixBackdrop() {
  const { settings } = usePreferences();
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [status, setStatus] = useState<MatrixStatus | null>(null);
  const [mode, setMode] = useState<Mode>("connecting");
  const [reason, setReason] = useState("Checking CMatrix capability…");
  const [reducedMotion, setReducedMotion] = useState(false);

  useEffect(() => {
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReducedMotion(query.matches);
    update();
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);

  const paintFrame = useCallback((frame: FrameEvent) => {
    const canvas = canvasRef.current;
    if (!canvas || !frame.lines || !frame.intensity) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const dpr = Math.min(1.5, window.devicePixelRatio || 1);
    const width = Math.max(320, window.innerWidth);
    const height = Math.max(240, window.innerHeight);
    if (canvas.width !== Math.floor(width * dpr) || canvas.height !== Math.floor(height * dpr)) {
      canvas.width = Math.floor(width * dpr);
      canvas.height = Math.floor(height * dpr);
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    // Fade rather than wipe: the terminal itself produces the falling streams.
    ctx.fillStyle = "rgba(1, 6, 4, 0.55)";
    ctx.fillRect(0, 0, width, height);
    const cols = Math.max(1, frame.cols || 80);
    const rows = Math.max(1, frame.rows || frame.lines.length || 24);
    const cellW = width / cols;
    const cellH = height / rows;
    const fontSize = Math.max(8, Math.min(cellH * 1.05, cellW * 0.92, 22));
    ctx.font = `${fontSize}px ui-monospace, SFMono-Regular, Menlo, monospace`;
    ctx.textBaseline = "top";
    for (let row = 0; row < frame.lines.length; row += 1) {
      const line = frame.lines[row] || "";
      const styles = frame.intensity[row] || "";
      for (let col = 0; col < line.length; col += 1) {
        const char = line[col];
        if (!char || char === " ") continue;
        const level = styles[col] || "1";
        ctx.fillStyle = level === "2" ? "rgba(200, 255, 218, 0.92)" : "rgba(18, 247, 124, 0.72)";
        ctx.fillText(char, col * cellW, row * cellH);
      }
    }
  }, []);

  // The renderer lifecycle is driven by the persisted Matrix settings.
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const matrix = settings.matrix;
    if (!matrix.enabled) {
      setMode("disabled");
      setReason("Matrix background is switched off in Settings.");
      canvas.getContext("2d")?.clearRect(0, 0, canvas.width, canvas.height);
      return;
    }
    if (matrix.respect_reduced_motion && reducedMotion) {
      setMode("reduced");
      setReason("Reduced-motion preference is active; animation is intentionally paused.");
      canvas.getContext("2d")?.clearRect(0, 0, canvas.width, canvas.height);
      return;
    }

    let cancelled = false;
    let socket: WebSocket | null = null;
    let events: EventSource | null = null;
    let portInstance: { stop(): void; clear(): void; render(): void; resize(w: number, h: number): void } | null = null;
    let portTimer: number | null = null;
    let resizeHandler: (() => void) | null = null;
    let frameCounter = 0;
    const skip = Math.max(0, Math.round((10 - matrix.speed) / 2));

    const clearCanvas = () => {
      canvas.getContext("2d")?.clearRect(0, 0, canvas.width, canvas.height);
    };

    const startPort = async (why: string) => {
      if (cancelled) return;
      setMode("port");
      setReason(why);
      clearCanvas();
      try {
        const { default: effect } = await import("@/lib/vendor/cmatrix.mjs");
        if (cancelled) return;
        const fontSize = Math.max(10, 22 - matrix.density);
        effect(canvas, {
          chars: effect.custom_chars,
          color: "#12f77c",
          background: "rgba(1, 9, 6, 0.12)",
          font_size: fontSize,
          width: window.innerWidth,
          height: window.innerHeight,
          resize: false,
          exit: false,
          mount: (mounted) => {
            portInstance = mounted;
            mounted.stop(); // drive frames ourselves so speed is adjustable
            const interval = Math.max(30, 180 - matrix.speed * 14);
            portTimer = window.setInterval(() => {
              if (document.hidden) return;
              mounted.render();
            }, interval);
          },
        });
        resizeHandler = () => portInstance?.resize(window.innerWidth, window.innerHeight);
        window.addEventListener("resize", resizeHandler);
      } catch (err) {
        if (!cancelled) {
          setMode("disabled");
          setReason(`CMatrix fallback could not start: ${err instanceof Error ? err.message : String(err)}`);
        }
      }
    };

    const startSSE = async (paths: { sse_path: string }) => {
      if (cancelled || events) return;
      try {
        events = new EventSource(paths.sse_path);
        events.onmessage = (message) => {
          let event: FrameEvent;
          try {
            event = JSON.parse(message.data);
          } catch {
            return;
          }
          if (event.type === "status") {
            setMode("pty");
            setReason("Original CMatrix PTY stream (SSE transport).");
          } else if (event.type === "frame") {
            if (skip && frameCounter++ % (skip + 1) !== 0) return;
            if (!document.hidden) paintFrame(event);
          } else if (event.type === "error") {
            events?.close();
            events = null;
            void startPort(event.detail || "The CMatrix process stopped; using the MIT JS port.");
          }
        };
        events.onerror = () => {
          events?.close();
          events = null;
          void startPort("SSE transport failed; using the MIT JS port.");
        };
      } catch {
        await startPort("SSE could not be opened; using the MIT JS port.");
      }
    };

    const startPTY = async () => {
      let capability: MatrixStatus;
      try {
        capability = await request<MatrixStatus>("/matrix/status", { auth: false });
        setStatus(capability);
      } catch (err) {
        await startPort(`Capability check failed (${err instanceof Error ? err.message : "unknown"}); using the MIT JS port.`);
        return;
      }
      if (cancelled) return;
      if (matrix.renderer === "port" || !capability.available) {
        await startPort(
          matrix.renderer === "port"
            ? "MIT JS port selected in Matrix settings."
            : capability.reason || "The original cmatrix binary is not available in this deployment.",
        );
        return;
      }
      let paths: { websocket_path: string; sse_path: string };
      try {
        paths = await api.post<{ websocket_path: string; sse_path: string }>("/matrix/ticket", {});
      } catch {
        await startPort("Not signed in for the authenticated PTY stream; using the MIT JS port.");
        return;
      }
      if (cancelled) return;
      setMode("connecting");
      setReason("Connecting to the original CMatrix process…");
      try {
        const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
        socket = new WebSocket(`${protocol}//${window.location.host}${paths.websocket_path}`);
        let receivedFrame = false;
        const fallback = (why: string) => {
          if (cancelled || receivedFrame) return;
          socket?.close();
          socket = null;
          void startSSE(paths).catch(() => startPort(why));
        };
        socket.onmessage = (message) => {
          let event: FrameEvent;
          try {
            event = JSON.parse(message.data);
          } catch {
            return;
          }
          if (event.type === "frame") {
            receivedFrame = true;
            setMode("pty");
            setReason("Original CMatrix executable · authenticated PTY · WebSocket.");
            if (skip && frameCounter++ % (skip + 1) !== 0) return;
            if (!document.hidden) paintFrame(event);
          } else if (event.type === "status" && event.status) {
            setStatus(event.status);
          } else if (event.type === "error") {
            socket?.close();
            socket = null;
            void startPort(event.detail || "The CMatrix process could not start; using the MIT JS port.");
          }
        };
        socket.onerror = () => fallback("WebSocket upgrade unavailable; trying SSE, then the MIT JS port.");
        socket.onclose = () => fallback("WebSocket closed before frames arrived; trying SSE, then the MIT JS port.");
      } catch {
        await startSSE(paths).catch(() => startPort("WebSocket could not be opened; using the MIT JS port."));
      }
    };

    void startPTY();

    return () => {
      cancelled = true;
      socket?.close();
      events?.close();
      if (portTimer) window.clearInterval(portTimer);
      portInstance?.stop();
      portInstance?.clear();
      if (resizeHandler) window.removeEventListener("resize", resizeHandler);
      clearCanvas();
    };
  }, [settings.matrix, reducedMotion, paintFrame]);

  const label =
    mode === "pty"
      ? "CMATRIX · ORIGINAL PTY"
      : mode === "port"
        ? "CMATRIX · MIT JS PORT"
        : mode === "reduced"
          ? "CMATRIX · REDUCED MOTION"
          : mode === "disabled"
            ? "CMATRIX · OFF"
            : "CMATRIX · CONNECTING";

  return (
    <div className="cmatrix-backdrop" aria-hidden="true" data-matrix-mode={mode} data-reduced-motion={reducedMotion}>
      <canvas
        ref={canvasRef}
        className="cmatrix-canvas"
        style={{ opacity: mode === "pty" || mode === "port" ? settings.matrix.opacity : 0 }}
      />
      <div className="cmatrix-vignette" />
      <div className="cmatrix-status" title={reason}>
        <span className={mode === "pty" ? "cmatrix-status-dot is-live" : "cmatrix-status-dot"} />
        {label}
      </div>
      <span className="sr-only">{reason}</span>
    </div>
  );
}
