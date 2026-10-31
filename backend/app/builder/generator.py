"""Sandboxed project generation ("vibe to preview").

Two paths share one contract:

* **planner path** - when a live Claude adapter is configured, the model drafts the
  files (it is still only a planner: output is parsed, path-checked, size-capped
  and design-linted before anything is written).
* **template path** - when no model is available, a deterministic token-driven
  generator composes a real, deployable page from the prompt. This keeps the
  whole pipeline demonstrable end to end without an API key.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.builder.lint import LintReport, lint_project
from app.core.config import settings
from app.llm import LLMMessage, get_adapter
from app.llm.base import FinishReason

MAX_FILES = 24
MAX_FILE_BYTES = 320_000
SAFE_NAME = re.compile(r"^[a-z0-9][a-z0-9._/-]{0,80}$")

GENERATION_SYSTEM = """You are a senior front-end designer producing a single, production-ready static site.
Return ONLY a JSON object of the shape {"files": {"index.html": "<html>", "styles.css": "...", "README.md": "..."}, "summary": "one sentence"}.
Hard rules:
- Tailwind CSS via <script src="https://cdn.tailwindcss.com"></script>, configured with these colours:
  ink #0B1220, navy #101935, accent #5B8CFF, accent2 #8B5CF6, fog #F4F6FB, line #D7DCEA, muted #5B6475.
- One typeface (Inter), generous 1.5 line-height, clear heading jumps.
- Dark theme by default, responsive at 600px and 1024px, content capped at 1200px and centred.
- Real, specific copy for the user's business. No lorem ipsum, no placeholder images, no stock photos.
- Accessible: lang attribute, viewport meta, one h1, alt text, visible focus states, 48px+ touch targets.
- Include a contact section with a labelled form and an aria-live status region.
- Never put accent (#5B8CFF) and accent2 (#8B5CF6) on the same element.
- No external JS frameworks. Plain HTML/CSS/Tailwind only. Everything must render offline except the Tailwind CDN.
"""


@dataclass(slots=True)
class GenerationResult:
    files: dict[str, str]
    summary: str
    lint: LintReport
    mode: str  # planner | template
    repairs: int = 0


def slugify(value: str, fallback: str = "project") -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return (slug or fallback)[:50]


def _safe_path(path: str) -> bool:
    if not SAFE_NAME.match(path):
        return False
    if ".." in path or path.startswith("/") or path.startswith("."):
        return False
    return True


def sanitise_files(raw: dict[str, Any]) -> dict[str, str]:
    files: dict[str, str] = {}
    for path, content in list(raw.items())[:MAX_FILES]:
        if not isinstance(path, str) or not isinstance(content, str):
            continue
        if not _safe_path(path):
            continue
        files[path] = content[:MAX_FILE_BYTES]
    if "index.html" not in files:
        for p in files:
            if p.endswith(".html"):
                files["index.html"] = files[p]
                break
    return files


# --------------------------------------------------------------------------
# Template path (deterministic, no model required)
# --------------------------------------------------------------------------
def _sections(prompt: str) -> list[str]:
    low = prompt.lower()
    picked = ["hero"]
    picked.append("features")
    if any(w in low for w in ("price", "pricing", "plan", "subscription")):
        picked.append("pricing")
    if any(w in low for w in ("contact", "email", "book", "call", "hire")):
        picked.append("contact")
    else:
        picked.append("contact")
    return picked


LEAD_INS = (
    r"^(please\s+)?(build|create|make|generate|design|spin up|set up)\s+"
    r"(me\s+)?(a|an|the)?\s*(website|web ?site|site|landing page|web app|page|portfolio|shop|store)?\s*"
    r"(for|about|of|selling|to sell)?\s*"
)


def _title_from(prompt: str, name: str) -> str:
    for line in prompt.splitlines():
        line = line.strip()
        if not (3 <= len(line) <= 120):
            continue
        cleaned = re.sub(LEAD_INS, "", line, flags=re.I).strip(" .,:;-")
        words = re.findall(r"[A-Za-z0-9'&-]+", cleaned)[:6]
        if words:
            return " ".join(words).rstrip(",").title()
        words = re.findall(r"[A-Za-z0-9'&-]+", line)[:6]
        if words:
            return " ".join(words).rstrip(",").title()
    return name.replace("-", " ").title()


def template_site(prompt: str, name: str) -> tuple[dict[str, str], str]:
    title = _title_from(prompt, name)
    low = prompt.lower()
    tagline = (
        "Fast, reliable and built to grow with you."
        if "fast" not in low
        else "Built for speed from the first byte."
    )
    audience = "customers"
    for candidate in ("students", "developers", "founders", "families", "teams", "small businesses", "creators"):
        if candidate in low:
            audience = candidate
            break

    features = [
        ("Built for real work", f"Every screen is designed for {audience} who need answers, not clutter."),
        ("Fast by default", "Lightweight pages, no blocking scripts, and readable on any connection."),
        ("Honest and simple", "Clear pricing, plain language, and no dark patterns anywhere."),
    ]
    pricing = [
        ("Starter", "0", ["1 project", "Community support", "Design tokens"]),
        ("Studio", "29", ["Unlimited projects", "Priority email support", "Custom domain"]),
        ("Scale", "99", ["SSO", "Audit log", "Dedicated support"]),
    ]

    html = f"""<!DOCTYPE html>
<html lang="en" class="scroll-smooth">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{title}</title>
  <meta name="description" content="{title} - {tagline}" />
  <script src="https://cdn.tailwindcss.com"></script>
  <script>
    tailwind.config = {{
      theme: {{
        extend: {{
          colors: {{ ink: '#0B1220', navy: '#101935', accent: '#5B8CFF', accent2: '#8B5CF6', fog: '#F4F6FB', line: '#D7DCEA', muted: '#5B6475' }},
          fontFamily: {{ sans: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'] }},
          maxWidth: {{ content: '1200px' }}
        }}
      }}
    }}
  </script>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet" />
  <style>
    body {{ font-family: Inter, ui-sans-serif, system-ui, sans-serif; line-height: 1.5; }}
    :focus-visible {{ outline: 2px solid #5B8CFF; outline-offset: 3px; border-radius: 8px; }}
    @media (prefers-reduced-motion: reduce) {{ * {{ transition: none !important; animation: none !important; }} }}
    html {{ scroll-behavior: smooth; }}
  </style>
</head>
<body class="bg-ink text-fog antialiased selection:bg-accent selection:text-ink">
  <a href="#main" class="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:rounded-lg focus:bg-accent focus:px-4 focus:py-2 focus:text-ink">Skip to content</a>

  <header class="sticky top-0 z-40 border-b border-white/10 bg-ink/80 backdrop-blur">
    <div class="mx-auto flex max-w-content items-center justify-between gap-4 px-5 py-4">
      <a href="#" class="flex items-center gap-3 text-lg font-semibold tracking-tight">
        <span class="grid h-9 w-9 place-items-center rounded-xl bg-accent text-ink" aria-hidden="true">{title[:1].upper()}</span>
        {title}
      </a>
      <nav aria-label="Main" class="hidden items-center gap-1 md:flex">
        <a href="#features" class="rounded-lg px-3 py-2 text-sm text-fog/80 transition hover:bg-white/5 hover:text-fog">Features</a>
        <a href="#pricing" class="rounded-lg px-3 py-2 text-sm text-fog/80 transition hover:bg-white/5 hover:text-fog">Pricing</a>
        <a href="#contact" class="rounded-lg px-3 py-2 text-sm text-fog/80 transition hover:bg-white/5 hover:text-fog">Contact</a>
      </nav>
      <a href="#contact" class="inline-flex min-h-[48px] items-center rounded-xl bg-accent px-5 text-sm font-semibold text-ink transition hover:brightness-110">Get started</a>
    </div>
  </header>

  <main id="main">
    <section class="border-b border-white/10">
      <div class="mx-auto grid max-w-content gap-12 px-5 py-20 lg:grid-cols-[1.1fr_0.9fr] lg:items-center lg:py-28">
        <div>
          <p class="mb-4 inline-flex items-center gap-2 rounded-full border border-white/10 bg-navy px-3 py-1 text-xs font-medium uppercase tracking-wider text-fog/70">
            <span class="h-1.5 w-1.5 rounded-full bg-accent" aria-hidden="true"></span> {title}
          </p>
          <h1 class="text-4xl font-bold leading-tight tracking-tight sm:text-5xl">{tagline}</h1>
          <p class="mt-5 max-w-xl text-lg text-fog/70">{prompt.strip().splitlines()[0][:220]}</p>
          <div class="mt-8 flex flex-col gap-3 sm:flex-row">
            <a href="#contact" class="inline-flex min-h-[48px] items-center justify-center rounded-xl bg-accent px-6 font-semibold text-ink transition hover:brightness-110">Start free</a>
            <a href="#features" class="inline-flex min-h-[48px] items-center justify-center rounded-xl border border-line/20 px-6 font-semibold text-fog transition hover:bg-white/5">See how it works</a>
          </div>
          <dl class="mt-10 grid max-w-lg grid-cols-3 gap-4 text-sm">
            <div class="rounded-xl border border-white/10 bg-navy p-4"><dt class="text-fog/60">Projects</dt><dd class="mt-1 text-xl font-semibold">10k+</dd></div>
            <div class="rounded-xl border border-white/10 bg-navy p-4"><dt class="text-fog/60">Uptime</dt><dd class="mt-1 text-xl font-semibold">99.9%</dd></div>
            <div class="rounded-xl border border-white/10 bg-navy p-4"><dt class="text-fog/60">Setup</dt><dd class="mt-1 text-xl font-semibold">2 min</dd></div>
          </dl>
        </div>
        <div class="rounded-2xl border border-white/10 bg-navy p-6 shadow-2xl shadow-black/40" role="img" aria-label="Product preview panel">
          <div class="mb-4 flex items-center gap-2">
            <span class="h-2.5 w-2.5 rounded-full bg-accent"></span>
            <span class="h-2.5 w-2.5 rounded-full bg-white/20"></span>
            <span class="h-2.5 w-2.5 rounded-full bg-white/20"></span>
            <span class="ml-auto text-xs text-fog/50">{name}</span>
          </div>
          <div class="space-y-3">
            <div class="h-3 w-2/3 rounded-full bg-white/15"></div>
            <div class="h-3 w-1/2 rounded-full bg-white/10"></div>
            <div class="mt-6 grid grid-cols-2 gap-3">
              <div class="rounded-xl border border-white/10 bg-ink/60 p-4"><div class="h-2 w-10 rounded bg-accent"></div><div class="mt-3 h-2 w-full rounded bg-white/10"></div><div class="mt-2 h-2 w-4/5 rounded bg-white/10"></div></div>
              <div class="rounded-xl border border-white/10 bg-ink/60 p-4"><div class="h-2 w-10 rounded bg-white/30"></div><div class="mt-3 h-2 w-full rounded bg-white/10"></div><div class="mt-2 h-2 w-2/3 rounded bg-white/10"></div></div>
            </div>
          </div>
        </div>
      </div>
    </section>

    <section id="features" class="border-b border-white/10">
      <div class="mx-auto max-w-content px-5 py-20">
        <h2 class="text-3xl font-bold tracking-tight">What you get</h2>
        <p class="mt-3 max-w-2xl text-fog/70">Three things we do properly, instead of twenty things we do badly.</p>
        <div class="mt-10 grid gap-5 md:grid-cols-3">
          {''.join(f'''<article class="rounded-2xl border border-white/10 bg-navy p-6"><h3 class="text-lg font-semibold">{t}</h3><p class="mt-2 text-sm leading-relaxed text-fog/70">{d}</p></article>''' for t, d in features)}
        </div>
      </div>
    </section>

    <section id="pricing" class="border-b border-white/10">
      <div class="mx-auto max-w-content px-5 py-20">
        <h2 class="text-3xl font-bold tracking-tight">Simple pricing</h2>
        <p class="mt-3 text-fog/70">No seats, no surprises, cancel any time.</p>
        <div class="mt-10 grid gap-5 md:grid-cols-3">
          {''.join(f'''<article class="flex flex-col rounded-2xl border border-white/10 bg-navy p-6"><h3 class="text-sm font-medium uppercase tracking-wider text-fog/60">{p}</h3><p class="mt-2 text-3xl font-bold">${c}<span class="text-base font-normal text-fog/60">/mo</span></p><ul class="mt-5 flex-1 space-y-2 text-sm text-fog/75">{''.join(f'<li class="flex gap-2"><span class="text-accent" aria-hidden="true">&#10003;</span>{feat}</li>' for feat in feats)}</ul><a href="#contact" class="mt-6 inline-flex min-h-[48px] items-center justify-center rounded-xl border border-line/20 px-4 font-semibold transition hover:bg-white/5">Choose {p}</a></article>''' for p, c, feats in pricing)}
        </div>
      </div>
    </section>

    <section id="contact">
      <div class="mx-auto grid max-w-content gap-10 px-5 py-20 lg:grid-cols-2 lg:items-start">
        <div>
          <h2 class="text-3xl font-bold tracking-tight">Talk to us</h2>
          <p class="mt-3 text-fog/70">Tell us what you need and we will reply within one business day.</p>
        </div>
        <form id="contact-form" class="rounded-2xl border border-white/10 bg-navy p-6" novalidate>
          <label class="block text-sm font-medium" for="email">Email</label>
          <input id="email" name="email" type="email" required autocomplete="email" class="mt-2 min-h-[48px] w-full rounded-xl border border-line/20 bg-ink px-4 text-fog placeholder:text-fog/35 focus-visible:outline-none" placeholder="you@example.com" />
          <label class="mt-4 block text-sm font-medium" for="message">Message</label>
          <textarea id="message" name="message" rows="4" required class="mt-2 w-full rounded-xl border border-line/20 bg-ink p-4 text-fog placeholder:text-fog/35 focus-visible:outline-none" placeholder="What are you building?"></textarea>
          <button type="submit" class="mt-5 inline-flex min-h-[48px] w-full items-center justify-center rounded-xl bg-accent px-6 font-semibold text-ink transition hover:brightness-110">Send message</button>
          <p id="form-status" aria-live="polite" class="mt-3 text-sm text-fog/60"></p>
        </form>
      </div>
    </section>
  </main>

  <footer class="border-t border-white/10">
    <div class="mx-auto flex max-w-content flex-col gap-2 px-5 py-10 text-sm text-fog/55 sm:flex-row sm:items-center sm:justify-between">
      <p>&copy; <span id="year">2026</span> {title}. All rights reserved.</p>
      <p>Built with A.R.M.X AI</p>
    </div>
  </footer>

  <script>
    const form = document.getElementById('contact-form');
    const status = document.getElementById('form-status');
    document.getElementById('year').textContent = new Date().getFullYear();
    form.addEventListener('submit', (event) => {{
      event.preventDefault();
      const email = form.email.value.trim();
      if (!email || !/^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$/.test(email)) {{
        status.textContent = 'Please enter a valid email address.';
        form.email.focus();
        return;
      }}
      status.textContent = 'Sending...';
      setTimeout(() => {{ status.textContent = 'Thanks - we will be in touch shortly.'; form.reset(); }}, 400);
    }});
  </script>
</body>
</html>
"""
    files = {
        "index.html": html,
        "README.md": f"# {title}\n\nGenerated by A.R.M.X AI from this brief:\n\n> {prompt.strip()[:1500]}\n\nDeploy target is a static site: `index.html` is the entry point.\n",
        "vercel.json": json.dumps({"cleanUrls": True, "trailingSlash": False}, indent=2) + "\n",
    }
    return files, f"Static landing page for {title} with features, pricing and a contact form."


# --------------------------------------------------------------------------
# Planner path
# --------------------------------------------------------------------------
def _extract_json(text: str) -> dict[str, Any] | None:
    match = re.search(r"\{.*\}", text, flags=re.S)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


async def generate(prompt: str, name: str) -> GenerationResult:
    adapter = get_adapter()
    if adapter.name != "mock":
        response = await adapter.complete(
            [
                LLMMessage(role="system", content=GENERATION_SYSTEM),
                LLMMessage(role="user", content=f"Brief:\n{prompt}\n\nProject name: {name}"),
            ],
            [],
        )
        if response.finish_reason is not FinishReason.ERROR:
            parsed = _extract_json(response.text)
            if parsed and isinstance(parsed.get("files"), dict):
                files = sanitise_files(parsed["files"])
                if files:
                    report = lint_project(files)
                    repairs = 0
                    if not report.ok:
                        files, report = await _repair(files, report, prompt, name)
                        repairs = 1
                    return GenerationResult(
                        files=files,
                        summary=str(parsed.get("summary", ""))[:400] or f"Generated site for {name}.",
                        lint=report,
                        mode="planner",
                        repairs=repairs,
                    )

    files, summary = template_site(prompt, name)
    return GenerationResult(files=files, summary=summary, lint=lint_project(files), mode="template")


async def _repair(
    files: dict[str, str], report: LintReport, prompt: str, name: str
) -> tuple[dict[str, str], LintReport]:
    """One bounded repair round: feed violations back to the planner."""
    adapter = get_adapter()
    problems = json.dumps(report.as_dict()["errors"][:12], indent=1)
    response = await adapter.complete(
        [
            LLMMessage(role="system", content=GENERATION_SYSTEM),
            LLMMessage(
                role="user",
                content=(
                    f"Brief:\n{prompt}\n\nProject name: {name}\n\n"
                    f"Your previous output failed the design lint with these errors:\n{problems}\n"
                    "Return the corrected JSON object with the same shape."
                ),
            ),
        ],
        [],
    )
    parsed = _extract_json(response.text) if response.finish_reason is not FinishReason.ERROR else None
    if not parsed or not isinstance(parsed.get("files"), dict):
        return files, report
    repaired = sanitise_files(parsed["files"])
    return (repaired, lint_project(repaired)) if repaired else (files, report)


# --------------------------------------------------------------------------
# Sandboxed materialisation
# --------------------------------------------------------------------------
def workspace_for(user_id: str, slug: str) -> Path:
    root = Path(settings.PROJECT_WORKSPACE).resolve()
    target = (root / user_id / slug).resolve()
    if not str(target).startswith(str(root)):
        raise ValueError("Path traversal outside the project workspace")
    return target


def write_project(user_id: str, slug: str, files: dict[str, str]) -> Path:
    target = workspace_for(user_id, slug)
    (target / "public").mkdir(parents=True, exist_ok=True)
    for path, content in files.items():
        if not _safe_path(path):
            continue
        dest = (target / "public" / path).resolve()
        if not str(dest).startswith(str(target)):
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
    return target
