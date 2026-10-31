"""Shared integration helpers: configuration state and honest unavailability."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)


class IntegrationNotConfigured(Exception):
    def __init__(self, provider: str, hint: str = "") -> None:
        self.provider = provider
        self.hint = hint
        super().__init__(f"{provider} is not configured")

    def payload(self) -> dict[str, Any]:
        return {
            "ok": False,
            "not_configured": self.provider,
            "hint": self.hint or f"Set the {self.provider} environment variables to enable this.",
        }


@dataclass(slots=True)
class IntegrationStatus:
    provider: str
    configured: bool
    mode: str = "live"
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "configured": self.configured,
            "mode": self.mode if self.configured else "unavailable",
            "detail": self.detail,
        }


def redact(value: str, keep: int = 4) -> str:
    if not value:
        return ""
    if len(value) <= keep:
        return "*" * len(value)
    return value[:keep] + "*" * max(4, len(value) - keep)
