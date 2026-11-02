"use client";

import { useEffect, useRef, useState } from "react";
import type { CMatrixInstance } from "cmatrix";

/**
 * Full-viewport Matrix rain powered by jcubic/cmatrix (MIT).
 *
 * The effect is deliberately client-only: the package renders into a canvas and
 * needs browser APIs. Users who prefer reduced motion get the same atmospheric
 * backdrop without a continuously-running animation.
 */
export function CMatrixBackdrop() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [reducedMotion, setReducedMotion] = useState(true);

  useEffect(() => {
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReducedMotion(query.matches);
    update();
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || reducedMotion) return;

    let disposed = false;
    let instance: CMatrixInstance | undefined;
    let observer: ResizeObserver | undefined;

    void import("cmatrix").then(({ default: matrix }) => {
      if (disposed) return;

      const resize = () => {
        instance?.resize(window.innerWidth, window.innerHeight);
      };

      matrix(canvas, {
        chars: matrix.custom_chars,
        color: "#12f77c",
        background: "rgba(1, 9, 6, 0.095)",
        font_size: window.innerWidth < 640 ? 13 : 16,
        width: window.innerWidth,
        height: window.innerHeight,
        resize: false,
        exit: false,
        mount: (mounted) => {
          instance = mounted;
          observer = new ResizeObserver(resize);
          observer.observe(document.documentElement);
        },
      });
    });

    return () => {
      disposed = true;
      observer?.disconnect();
      instance?.stop();
      instance?.clear();
      canvas.classList.remove("running");
    };
  }, [reducedMotion]);

  return (
    <div className="cmatrix-backdrop" aria-hidden="true" data-reduced-motion={reducedMotion}>
      <canvas ref={canvasRef} className="cmatrix-canvas" />
      <div className="cmatrix-vignette" />
    </div>
  );
}
