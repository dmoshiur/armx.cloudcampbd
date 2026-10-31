"""Integration registry + health aggregation."""
from __future__ import annotations

from typing import Any

from app.core.config import settings
from app.integrations import github_vercel, home_assistant, mail, messaging, search, telecom


def snapshot() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = [
        github_vercel.status()[0].as_dict(),
        github_vercel.status()[1].as_dict(),
        github_vercel.status()[2].as_dict(),
        home_assistant.status().as_dict(),
        search.status().as_dict(),
        mail.status().as_dict(),
        messaging.status()[0].as_dict(),
        messaging.status()[1].as_dict(),
        telecom.status(),
    ]
    for item in items:
        item["simulated"] = settings.PIPELINE_MODE == "simulated" and item["provider"] in {
            "github",
            "vercel",
            "turso",
        }
    return items
