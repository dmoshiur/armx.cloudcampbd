"""Design-consistency lint for generated projects.

Runs before every deploy. Violations are reported to the model and the user;
an error-level violation blocks deployment instead of shipping silently.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

TOKENS_PATH = Path(__file__).resolve().parents[3] / "design" / "tokens.json"


def load_tokens() -> dict[str, Any]:
    try:
        return json.loads(TOKENS_PATH.read_text())
    except Exception:  # pragma: no cover - defensive
        return {"color": {}, "typography": {}, "layout": {}}


TOKENS = load_tokens()
PALETTE = {v.lower() for k, v in TOKENS.get("color", {}).items() if isinstance(v, str) and v.startswith("#")}
CONTENT_MAX = TOKENS.get("layout", {}).get("contentMaxWidth", 1200)

HEX_RE = re.compile(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})\b")
BANNED_FONTS = ("comic sans", "papyrus", "lobster")
BANNED_LIBS = ("bootstrap.min.css", "jquery.min.js")


@dataclass(slots=True)
class Finding:
    file: str
    rule: str
    severity: str  # error | warn | info
    message: str
    hint: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "file": self.file,
            "rule": self.rule,
            "severity": self.severity,
            "message": self.message,
            "hint": self.hint,
        }


@dataclass(slots=True)
class LintReport:
    ok: bool = True
    score: int = 100
    findings: list[Finding] = field(default_factory=list)
    checked_files: int = 0

    def add(self, finding: Finding) -> None:
        self.findings.append(finding)
        if finding.severity == "error":
            self.ok = False
            self.score -= 20
        elif finding.severity == "warn":
            self.score -= 5
        self.score = max(0, self.score)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "score": self.score,
            "checked_files": self.checked_files,
            "errors": [f.as_dict() for f in self.findings if f.severity == "error"],
            "warnings": [f.as_dict() for f in self.findings if f.severity == "warn"],
            "info": [f.as_dict() for f in self.findings if f.severity == "info"],
        }


def lint_html(path: str, html: str) -> LintReport:
    report = LintReport(checked_files=1)
    low = html.lower()

    # Structure ---------------------------------------------------------
    if "<!doctype html>" not in low:
        report.add(Finding(path, "doctype", "error", "Missing <!DOCTYPE html>"))
    if 'lang="' not in low and "lang='" not in low:
        report.add(Finding(path, "lang", "error", "Missing lang attribute on <html>"))
    if 'name="viewport"' not in low:
        report.add(Finding(path, "viewport", "error", "Missing responsive viewport meta tag"))
    if "<title>" not in low:
        report.add(Finding(path, "title", "warn", "Missing <title>"))
    if 'charset="utf-8"' not in low and "charset=utf-8" not in low:
        report.add(Finding(path, "charset", "warn", "Missing UTF-8 charset declaration"))

    # Design system -----------------------------------------------------
    tailwind = "tailwind" in low
    if not tailwind:
        report.add(
            Finding(
                path,
                "design-system",
                "error",
                "No Tailwind detected - generated sites must use the shared Tailwind system",
                "Use the Tailwind CDN script or a Tailwind build with the A.R.M.X tokens.",
            )
        )

    hexes = {h.lower() for h in HEX_RE.findall(html)}
    off_palette = {h for h in hexes if h not in PALETTE and h not in {"#000", "#fff", "#000000", "#ffffff"}}
    if len(off_palette) > 6:
        report.add(
            Finding(
                path,
                "palette",
                "error",
                f"{len(off_palette)} off-palette colours: {', '.join(sorted(off_palette)[:8])}",
                "Use the token palette: " + ", ".join(sorted(PALETTE)),
            )
        )
    elif off_palette:
        report.add(
            Finding(
                path,
                "palette",
                "warn",
                f"Off-palette colours used: {', '.join(sorted(off_palette)[:5])}",
                "Prefer design tokens.",
            )
        )

    if "#5b8cff" in hexes and "#8b5cf6" in hexes:
        # Both accents are fine globally; flag only if they share a utility class line.
        for line_no, line in enumerate(html.splitlines(), 1):
            bare = line.lower()
            # Only inspect actual markup/utility usage, not the design-token declaration.
            if not ("class=" in bare or "style=" in bare or "fill=" in bare or "stroke=" in bare):
                continue
            if "#5b8cff" in bare and "#8b5cf6" in bare:
                report.add(
                    Finding(
                        path,
                        "accent-pairing",
                        "error",
                        f"Line {line_no} combines accent and accent2 on one element",
                        "Secondary emphasis must never be combined with the primary accent.",
                    )
                )
                break

    if any(font in low for font in BANNED_FONTS):
        report.add(Finding(path, "typography", "error", "Banned decorative typeface detected"))
    if "font-family" in low and not re.search(r"font-family:\s*(var\(--|['\"]?inter)", low):
        report.add(
            Finding(path, "typography", "warn", "Custom font stack bypasses the shared typeface", "Use Inter via the token stack.")
        )

    if any(lib in low for lib in BANNED_LIBS):
        report.add(Finding(path, "dependencies", "warn", "Legacy CSS/JS library detected", "Tailwind only."))

    # Layout / responsiveness ------------------------------------------
    if re.search(r"max-width:\s*9[6-9]\dpx", low) and f"{CONTENT_MAX}" not in low:
        report.add(
            Finding(path, "content-width", "warn", f"Content width cap should be ~{CONTENT_MAX}px")
        )
    if re.search(r"width:\s*(1[2-9]\d{2}|[2-9]\d{3})px", low):
        report.add(Finding(path, "fixed-layout", "warn", "Fixed pixel root width detected", "Use responsive max-width + centred container."))
    if not re.search(r"@media[^{]*\(max-width", low) and "md:" not in low and "sm:" not in low:
        report.add(
            Finding(path, "responsive", "warn", "No responsive breakpoints found", "Add compact/medium/expanded behaviour.")
        )

    # Accessibility -----------------------------------------------------
    imgs = re.findall(r"<img\b[^>]*>", html, flags=re.I)
    missing_alt = [i for i in imgs if "alt=" not in i.lower()]
    if missing_alt:
        report.add(Finding(path, "a11y", "error", f"{len(missing_alt)} <img> without alt text"))
    if re.search(r"<button[^>]*>\s*</button>", html, flags=re.I):
        report.add(Finding(path, "a11y", "error", "Empty <button> with no accessible label"))
    if "<h1" not in low:
        report.add(Finding(path, "a11y", "warn", "No <h1> on the page"))
    if re.search(r"outline:\s*none", low) and "focus-visible" not in low:
        report.add(Finding(path, "a11y", "error", "Outline removed without a visible focus style"))
    if "aria-label" not in low and '<nav' in low:
        report.add(Finding(path, "a11y", "info", "Consider aria-label on navigation landmarks"))

    # Content hygiene ---------------------------------------------------
    if re.search(r"(lorem ipsum|placehold\.co|via\.placeholder)", low):
        report.add(Finding(path, "placeholder-content", "error", "Placeholder/lorem content must not ship"))
    if "stock" in low and "unsplash" in low:
        report.add(Finding(path, "imagery", "warn", "Stock photography detected", "Use typography and layout instead."))
    if 'rel="noopener' not in low and 'target="_blank"' in low:
        report.add(Finding(path, "security", "error", "target=_blank without rel=noopener"))

    return report


def lint_project(files: dict[str, str]) -> LintReport:
    total = LintReport()
    for path, content in files.items():
        if not path.lower().endswith((".html", ".htm")):
            continue
        r = lint_html(path, content)
        total.checked_files += r.checked_files
        for f in r.findings:
            total.add(f)
    if total.checked_files == 0:
        total.add(Finding("(project)", "structure", "error", "No HTML entry point found"))
    return total
