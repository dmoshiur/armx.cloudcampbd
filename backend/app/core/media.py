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
    ext = ALLOWED_IMAGE_TYPES.get(content_type)
    if ext is None:
        raise ValueError("unsupported image type; use PNG, JPEG or WebP")
    if len(content) > settings.MAX_UPLOAD_BYTES:
        raise ValueError(f"file too large (max {settings.MAX_UPLOAD_BYTES // 1024} KB)")
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
