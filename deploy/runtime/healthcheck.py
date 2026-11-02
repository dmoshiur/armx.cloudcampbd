"""Check both public routes, not just the lifetime of the supervisor process."""
from __future__ import annotations

import json
import os
import urllib.request

port = os.environ.get("PORT", "10000")
base = f"http://127.0.0.1:{port}"
with urllib.request.urlopen(f"{base}/api/health", timeout=5) as response:
    health = json.load(response)
if health.get("status") != "ok" or health.get("database") != "ok":
    raise RuntimeError("API or database health check failed")
with urllib.request.urlopen(f"{base}/login", timeout=5) as response:
    if response.status != 200:
        raise RuntimeError("Web health check failed")
