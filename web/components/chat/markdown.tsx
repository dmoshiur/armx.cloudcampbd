"use client";

import { useMemo, useState, type ReactNode } from "react";

/** Small, dependency-free Markdown renderer. React escapes all text, and links
 * are restricted to safe schemes, so model output can never inject HTML/script. */

const KEYWORDS = new Set([
  "const", "let", "var", "function", "return", "if", "else", "for", "while", "class",
  "import", "from", "export", "default", "async", "await", "try", "catch", "throw",
  "new", "true", "false", "null", "None", "True", "False", "def", "self", "public",
  "private", "interface", "type", "extends", "SELECT", "FROM", "WHERE", "def", "end",
]);

const TOKEN_RE = /(\/\/[^\n]*|\/\*[\s\S]*?\*\/|#[^\n]*)|("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`)|\b(\d+(?:\.\d+)?)\b|([A-Za-z_$][\w$]*)/g;

function highlight(code: string): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0;
  for (const match of code.matchAll(TOKEN_RE)) {
    const index = match.index ?? 0;
    if (index > last) out.push(code.slice(last, index));
    const [whole, comment, string, number, word] = match;
    if (comment) out.push(<span key={index} className="tok-com">{comment}</span>);
    else if (string) out.push(<span key={index} className="tok-str">{string}</span>);
    else if (number) out.push(<span key={index} className="tok-num">{number}</span>);
    else if (word && KEYWORDS.has(word)) out.push(<span key={index} className="tok-key">{word}</span>);
    else out.push(whole);
    last = index + whole.length;
  }
  if (last < code.length) out.push(code.slice(last));
  return out;
}

function safeHref(raw: string): string | null {
  const value = raw.trim();
  if (/^(https?:\/\/|mailto:|\/)/i.test(value)) return value;
  return null;
}

function inline(text: string, keyPrefix: string): ReactNode[] {
  const pattern = /(\*\*[^*]+\*\*|__[^_]+__|\*[^*]+\*|_[^_]+_|`[^`]+`|\[[^\]]+\]\([^)\s]+\))/g;
  const out: ReactNode[] = [];
  let last = 0;
  for (const match of text.matchAll(pattern)) {
    const index = match.index ?? 0;
    if (index > last) out.push(text.slice(last, index));
    const token = match[0];
    const key = `${keyPrefix}-${index}`;
    if (token.startsWith("**") || token.startsWith("__")) {
      out.push(<strong key={key} className="font-semibold text-fg">{token.slice(2, -2)}</strong>);
    } else if (token.startsWith("`")) {
      out.push(<code key={key}>{token.slice(1, -1)}</code>);
    } else if (token.startsWith("[")) {
      const link = /^\[([^\]]+)\]\(([^)\s]+)\)$/.exec(token);
      const href = link ? safeHref(link[2]) : null;
      out.push(
        href ? (
          <a key={key} href={href} target="_blank" rel="noopener noreferrer">{link![1]}</a>
        ) : (
          <span key={key}>{token}</span>
        ),
      );
    } else {
      out.push(<em key={key}>{token.slice(1, -1)}</em>);
    }
    last = index + token.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

function CodeBlock({ code, language }: { code: string; language: string }) {
  const [copied, setCopied] = useState(false);
  const tokens = useMemo(() => highlight(code), [code]);
  return (
    <div className="armx-code">
      <div className="flex items-center justify-between border-b border-edge/60 px-3 py-1.5">
        <span className="font-mono text-[11px] uppercase tracking-wider text-fgmuted">{language || "code"}</span>
        <button
          type="button"
          onClick={() => {
            void navigator.clipboard?.writeText(code).then(() => {
              setCopied(true);
              window.setTimeout(() => setCopied(false), 1600);
            });
          }}
          className="rounded border border-edge/70 px-2 py-0.5 text-[11px] text-fgmuted transition hover:border-accent/50 hover:text-accent"
        >
          {copied ? "Copied" : "Copy code"}
        </button>
      </div>
      <pre><code>{tokens}</code></pre>
    </div>
  );
}

function TextBlock({ text, prefix }: { text: string; prefix: string }) {
  const lines = text.split("\n");
  const blocks: ReactNode[] = [];
  let list: { ordered: boolean; items: string[] } | null = null;

  const flush = (key: string) => {
    if (!list) return;
    const Tag = list.ordered ? "ol" : "ul";
    blocks.push(
      <Tag key={key}>
        {list.items.map((item, index) => <li key={index}>{inline(item, `${key}-${index}`)}</li>)}
      </Tag>,
    );
    list = null;
  };

  lines.forEach((line, index) => {
    const key = `${prefix}-l${index}`;
    const bullet = /^\s*[-*+]\s+(.+)$/.exec(line);
    const numbered = /^\s*\d+[.)]\s+(.+)$/.exec(line);
    if (bullet || numbered) {
      const ordered = Boolean(numbered);
      if (!list || list.ordered !== ordered) {
        flush(`${key}-flush`);
        list = { ordered, items: [] };
      }
      list.items.push((bullet || numbered)![1]);
      return;
    }
    flush(`${key}-flush`);
    if (!line.trim()) return;
    const heading = /^(#{1,3})\s+(.+)$/.exec(line);
    if (heading) {
      const level = heading[1].length;
      const content = inline(heading[2], key);
      blocks.push(level === 1 ? <h1 key={key}>{content}</h1> : level === 2 ? <h2 key={key}>{content}</h2> : <h3 key={key}>{content}</h3>);
      return;
    }
    if (/^>\s?/.test(line)) {
      blocks.push(<blockquote key={key}>{inline(line.replace(/^>\s?/, ""), key)}</blockquote>);
      return;
    }
    blocks.push(<p key={key}>{inline(line, key)}</p>);
  });
  flush(`${prefix}-end`);
  return <>{blocks}</>;
}

export function Markdown({ content }: { content: string }) {
  const parts = useMemo(() => {
    const chunks: ReactNode[] = [];
    const fence = /```([\w+-]*)\n([\s\S]*?)```/g;
    let last = 0;
    let index = 0;
    for (const match of content.matchAll(fence)) {
      const at = match.index ?? 0;
      if (at > last) chunks.push(<TextBlock key={`t${index}`} text={content.slice(last, at)} prefix={`t${index}`} />);
      chunks.push(<CodeBlock key={`c${index}`} code={match[2].replace(/\n$/, "")} language={match[1]} />);
      last = at + match[0].length;
      index += 1;
    }
    if (last < content.length) chunks.push(<TextBlock key={`t${index}`} text={content.slice(last)} prefix={`t${index}`} />);
    return chunks;
  }, [content]);

  return <div className="armx-markdown text-body text-fg">{parts.length ? parts : <p>{content}</p>}</div>;
}
