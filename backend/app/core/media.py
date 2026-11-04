"""Tiny per-user media store (uploads + generated images).

Files live under ``MEDIA_ROOT/<user_id>/<asset_id><ext>`` with a JSON sidecar.
Asset ids are opaque and ownership is checked on every read, so one user can
never fetch another user's asset by guessing an id.
"""
from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any

from app.core.config import settings

ASSET_RE = re.compile(r"^[a-f0-9]{32}$")
ALLOWED_IMAGE_TYPES = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}
ALLOWED_DOCUMENT_TYPES = {
    "application/pdf": ".pdf",
    "text/plain": ".txt",
    "text/markdown": ".md",
    "text/csv": ".csv",
    "application/json": ".json",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
}
ALLOWED_UPLOAD_TYPES = {**ALLOWED_IMAGE_TYPES, **ALLOWED_DOCUMENT_TYPES}

# Magic-byte checks stop a renamed executable from being served back as an image.
MAGIC = {
    "image/png": b"\x89PNG\r\n\x1a\n",
    "image/jpeg": b"\xff\xd8\xff",
    "image/webp": b"RIFF",
    "application/pdf": b"%PDF-",
}


def validate_upload(content_type: str, blob: bytes) -> None:
    if content_type not in ALLOWED_UPLOAD_TYPES:
        raise ValueError("unsupported file type; use PNG, JPEG, WebP, PDF, TXT, MD, CSV, JSON or DOCX")
    signature = MAGIC.get(content_type)
    if signature and not blob.startswith(signature):
        raise ValueError("file content does not match its declared type")
    if len(blob) > settings.MAX_UPLOAD_BYTES:
        raise ValueError(f"file too large (max {settings.MAX_UPLOAD_BYTES // 1024} KB)")


def extract_text(content_type: str, blob: bytes, *, filename: str = "") -> str:
    """Best-effort, bounded text extraction for document understanding.

    Binary formats are reported as attachments rather than silently decoded;
    the assistant never claims to have read bytes it could not parse.
    """
    if content_type in {"text/plain", "text/markdown", "text/csv", "application/json"}:
        return blob.decode("utf-8", errors="replace")[:12000]
    if content_type == "application/pdf":
        # No PDF parser dependency: expose the filename and a bounded raw-text
        # view so the model can only use what is actually present in the file.
        raw = blob.decode("latin-1", errors="ignore")
        printable = "".join(ch if ch.isprintable() or ch in "\n\t" else " " for ch in raw)
        return f"[PDF attachment {filename}; readable text is limited without a PDF parser]\n" + printable[:4000]
    return f"[{content_type} attachment {filename}; binary content not decoded]"


def media_root() -> Path:
    root = Path(settings.PROJECT_WORKSPACE).resolve().parent / "media"
    root.mkdir(parents=True, exist_ok=True)
    return root


def user_dir(user_id: str) -> Path:
    if not re.match(r"^[a-f0-9]{32}$", user_id):
        raise ValueError("bad user id")
    path = media_root() / user_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def new_asset_id() -> str:
    return uuid.uuid4().hex


def save_bytes(user_id: str, content: bytes, content_type: str, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    validate_upload(content_type, content)
    ext = ALLOWED_UPLOAD_TYPES[content_type]
    asset_id = new_asset_id()
    path = user_dir(user_id) / f"{asset_id}{ext}"
    path.write_bytes(content)
    record = {
        "asset_id": asset_id,
        "user_id": user_id,
        "content_type": content_type,
        "bytes": len(content),
        "path": str(path),
        **(meta or {}),
    }
    (user_dir(user_id) / f"{asset_id}.json").write_text(json.dumps(record))
    return record


def get(user_id: str, asset_id: str) -> dict[str, Any] | None:
    if not ASSET_RE.match(asset_id or ""):
        return None
    sidecar = user_dir(user_id) / f"{asset_id}.json"
    if not sidecar.exists():
        return None
    record = json.loads(sidecar.read_text())
    if record.get("user_id") != user_id:  # defence in depth
        return None
    if not Path(record["path"]).exists():
        return None
    return record


def read(user_id: str, asset_id: str) -> tuple[dict[str, Any], bytes] | None:
    record = get(user_id, asset_id)
    if record is None:
        return None
    return record, Path(record["path"]).read_bytes()
