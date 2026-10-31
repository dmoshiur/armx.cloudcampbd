"""Security Gateway: approvals, replay, hash binding, kill-switch, toggles, limits."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.core.db import as_utc
from app.models import Approval, ToolDefinition, ToolUserOverride, User
from app.registry import RiskTier, registry
from app.security import GatewayError, create_approval, execute, kill_switch_engaged, set_kill_switch


async def _user(db, email: str = "user@example.com") -> User:
    return (await db.execute(select(User).where(User.email == email))).scalar_one()


async def test_medium_tool_requires_approval(db, client, user_tokens):
    from sqlalchemy.ext.asyncio import AsyncSession  # noqa: F401

    user = await _user(db)
    with pytest.raises(GatewayError) as exc:
        await execute(
            db, user=user, session_id="sess-1", tool_name="web_generate",
            args={"prompt": "a bakery site in Dhaka", "name": "bakery"},
        )
    assert exc.value.code == "approval_required"


async def test_approval_is_single_use(db, user_tokens):
    user = await _user(db)
    spec = registry.get("web_generate")
    args = {"prompt": "a bakery site in Dhaka", "name": "bakery"}
    approval = await create_approval(db, user=user, session_id="sess-1", spec=spec, args=args)

    first = await execute(
        db, user=user, session_id="sess-1", tool_name="web_generate", args=args, approval_id=approval.id
    )
    assert first.ok is True

    with pytest.raises(GatewayError) as exc:
        await execute(
            db, user=user, session_id="sess-1", tool_name="web_generate", args=args, approval_id=approval.id
        )
    assert exc.value.code in {"approval_reused", "approval_required"}


async def test_changing_one_argument_invalidates_approval(db, user_tokens):
    user = await _user(db)
    spec = registry.get("web_generate")
    approved_args = {"prompt": "a bakery site in Dhaka", "name": "bakery"}
    approval = await create_approval(db, user=user, session_id="sess-1", spec=spec, args=approved_args)

    tampered = {"prompt": "a bakery site in Dhaka", "name": "something-else"}
    with pytest.raises(GatewayError) as exc:
        await execute(
            db, user=user, session_id="sess-1", tool_name="web_generate", args=tampered, approval_id=approval.id
        )
    assert exc.value.code == "approval_argument_mismatch"


async def test_approval_bound_to_session_and_actor(db, user_tokens, admin_tokens):
    user = await _user(db)
    other = await _user(db, "admin@example.com")
    spec = registry.get("web_generate")
    args = {"prompt": "a bakery site in Dhaka", "name": "bakery"}
    approval = await create_approval(db, user=user, session_id="sess-1", spec=spec, args=args)

    with pytest.raises(GatewayError) as exc:
        await execute(
            db, user=user, session_id="sess-2", tool_name="web_generate", args=args, approval_id=approval.id
        )
    assert exc.value.code == "approval_wrong_session"

    with pytest.raises(GatewayError) as exc:
        await execute(
            db, user=other, session_id="sess-1", tool_name="web_generate", args=args, approval_id=approval.id
        )
    assert exc.value.code == "approval_foreign"


async def test_expired_approval_is_refused(db, user_tokens):
    user = await _user(db)
    spec = registry.get("web_generate")
    args = {"prompt": "a bakery site in Dhaka", "name": "bakery"}
    approval = await create_approval(db, user=user, session_id="sess-1", spec=spec, args=args, ttl_seconds=1)
    approval.expires_at = datetime.now(timezone.utc) - timedelta(seconds=5)
    await db.commit()

    with pytest.raises(GatewayError) as exc:
        await execute(
            db, user=user, session_id="sess-1", tool_name="web_generate", args=args, approval_id=approval.id
        )
    assert exc.value.code == "approval_expired"


async def test_kill_switch_halts_integrations(db, user_tokens, admin_headers, client):
    user = await _user(db)
    resp = await client.post("/api/admin/kill-switch", headers=admin_headers, json={"engaged": True})
    assert resp.status_code == 200

    assert await kill_switch_engaged(db) is True
    with pytest.raises(GatewayError) as exc:
        await execute(
            db, user=user, session_id="s", tool_name="set_light",
            args={"entity_id": "light.living_room", "state": "on"},
        )
    assert exc.value.code == "denied"
    assert "kill-switch" in exc.value.message

    # health_status stays available so the platform can report its own state.
    ok = await execute(db, user=user, session_id="s", tool_name="health_status", args={})
    assert ok.ok is True

    await set_kill_switch(db, engaged=False, actor_id=user.id)
    assert await kill_switch_engaged(db) is False


async def test_disabled_tool_is_blocked_even_if_requested(db, user_tokens, admin_headers, client):
    user = await _user(db)
    resp = await client.patch("/api/admin/tools", headers=admin_headers, json={"name": "set_light", "enabled": False})
    assert resp.status_code == 200

    with pytest.raises(GatewayError) as exc:
        await execute(
            db, user=user, session_id="s", tool_name="set_light",
            args={"entity_id": "light.living_room", "state": "on"},
        )
    assert exc.value.code == "denied"
    assert "disabled" in exc.value.message


async def test_user_level_tool_toggle(db, user_tokens, admin_headers, client):
    user = await _user(db)
    resp = await client.patch(
        "/api/admin/tools/user",
        headers=admin_headers,
        json={"user_id": user.id, "name": "health_status", "enabled": False},
    )
    assert resp.status_code == 200
    with pytest.raises(GatewayError):
        await execute(db, user=user, session_id="s", tool_name="health_status", args={})


async def test_unknown_tool_is_rejected(db, user_tokens):
    user = await _user(db)
    with pytest.raises(GatewayError) as exc:
        await execute(db, user=user, session_id="s", tool_name="drop_database", args={})
    assert exc.value.code == "unknown_tool"


async def test_schema_violation_is_rejected(db, user_tokens):
    user = await _user(db)
    with pytest.raises(GatewayError) as exc:
        await execute(
            db, user=user, session_id="s", tool_name="set_light",
            args={"entity_id": "light.not_allowlisted", "state": "on"},
        )
    assert exc.value.code == "denied"


async def test_high_risk_device_tool_requires_vip(db, user_tokens):
    user = await _user(db)
    spec = registry.get("call_place")
    assert spec.risk is RiskTier.HIGH
    with pytest.raises(GatewayError) as exc:
        await execute(
            db, user=user, session_id="s", tool_name="call_place",
            args={"contact_number": "+8801700000000", "device_name": "Pixel"},
        )
    assert exc.value.code == "denied"
    assert "VIP" in exc.value.message


async def test_tool_rate_limit(db, user_tokens):
    from app.core.security import rate_limiter

    rate_limiter._buckets.clear()  # noqa: SLF001
    user = await _user(db)
    spec = registry.get("health_status")
    errors = 0
    for _ in range(spec.rate_limit_per_minute + 3):
        try:
            await execute(db, user=user, session_id="s", tool_name="health_status", args={})
        except GatewayError as exc:
            assert exc.code == "denied"
            assert "rate limit" in exc.message
            errors += 1
    assert errors >= 1
