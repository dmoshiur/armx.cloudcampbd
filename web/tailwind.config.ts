import type { Config } from "tailwindcss";
import tokens from "../design/tokens.json";

const color = tokens.color;

export default {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        ink: color.ink,
        navy: color.navy,
        accent: color.accent,
        accent2: color.accent2,
        fog: color.fog,
        line: color.line,
        muted: color.muted,
        success: color.success,
        warning: color.warning,
        danger: color.danger,
        // semantic aliases resolved through CSS variables (dark default)
        bg: "rgb(var(--bg) / <alpha-value>)",
        surface: "rgb(var(--surface) / <alpha-value>)",
        edge: "rgb(var(--border) / <alpha-value>)",
        fg: "rgb(var(--text) / <alpha-value>)",
        fgmuted: "rgb(var(--text-muted) / <alpha-value>)",
      },
      fontFamily: {
        sans: ["Inter", "Inter var", "ui-sans-serif", "system-ui", "sans-serif"],
      },
      fontSize: {
        display: ["2.75rem", { lineHeight: "1.1", letterSpacing: "-0.02em", fontWeight: "700" }],
        h1: ["2rem", { lineHeight: "1.2", letterSpacing: "-0.015em", fontWeight: "700" }],
        h2: ["1.5rem", { lineHeight: "1.25", letterSpacing: "-0.01em", fontWeight: "650" }],
        h3: ["1.125rem", { lineHeight: "1.35", fontWeight: "600" }],
        body: ["0.9375rem", { lineHeight: "1.5" }],
        caption: ["0.78125rem", { lineHeight: "1.45", letterSpacing: "0.01em" }],
      },
      borderRadius: {
        sm: "8px",
        md: "12px",
        lg: "16px",
        xl: "22px",
      },
      maxWidth: { content: `${tokens.layout.contentMaxWidth}px` },
      minHeight: { touch: `${tokens.layout.touchTargetMin}px` },
      transitionTimingFunction: { standard: "cubic-bezier(0.2, 0.7, 0.3, 1)" },
    },
  },
  plugins: [],
} satisfies Config;
