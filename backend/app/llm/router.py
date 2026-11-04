"""Database-backed weighted model routing with circuit-breaker failover."""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import as_utc, utcnow
from app.core.errors import classify_provider_error
from app.core.net import validate_provider_url
from app.core.secrets import decrypt_secret, encrypt_secret, secret_hint
from app.llm.base import FinishReason, LLMAdapter, LLMMessage, LLMResponse
from app.llm.claude import ClaudeAdapter
from app.llm.mock import MockAdapter
from app.llm.openai import OpenAIAdapter
from app.models import LLMModelConfig, LLMProvider, LLMRequestLog

log = logging.getLogger(__name__)


@dataclass(slots=True)
class Candidate:
    model_pk: str
    provider_pk: str
    provider_name: str
    provider_kind: str
    base_url: str
    api_key_encrypted: str
    model_id: str
    priority: int
    weight: int
    max_tokens: int
    supports_tools: bool


def _weighted_order(rows: list[Candidate]) -> list[Candidate]:
    """Weighted shuffle within each priority tier; lower priority wins."""
    if settings.LLM_ROUTING_STRATEGY == "priority":
        return sorted(
            rows,
            key=lambda row: (
                row.priority,
                -row.weight,
                row.provider_name,
                row.model_id,
            ),
        )
    ordered: list[Candidate] = []
    priorities = sorted({row.priority for row in rows})
    for priority in priorities:
        pool = [row for row in rows if row.priority == priority]
        while pool:
            total = sum(max(1, row.weight) for row in pool)
            choice = secrets.randbelow(total)
            upto = 0
            selected = pool[-1]
            for row in pool:
                upto += max(1, row.weight)
                if choice < upto:
                    selected = row
                    break
            ordered.append(selected)
            pool.remove(selected)
    return ordered


async def load_candidates(db: AsyncSession) -> list[Candidate]:
    now = datetime.now(timezone.utc)
    rows = (
        await db.execute(
            select(LLMModelConfig, LLMProvider)
            .join(LLMProvider, LLMProvider.id == LLMModelConfig.provider_id)
            .where(LLMModelConfig.enabled.is_(True), LLMProvider.enabled.is_(True))
        )
    ).all()
    candidates = []
    for model, provider in rows:
        circuit = as_utc(model.circuit_open_until)
        if circuit and circuit > now:
            continue
        candidates.append(
            Candidate(
                model_pk=model.id,
                provider_pk=provider.id,
                provider_name=provider.name,
                provider_kind=provider.kind,
                base_url=provider.base_url,
                api_key_encrypted=provider.api_key_encrypted,
                model_id=model.model_id,
                priority=model.priority,
                weight=model.weight,
                max_tokens=model.max_tokens,
                supports_tools=model.supports_tools,
            )
        )
    return _weighted_order(candidates)


def _adapter(candidate: Candidate) -> LLMAdapter:
    api_key = decrypt_secret(candidate.api_key_encrypted)
    if candidate.provider_kind == "anthropic":
        return ClaudeAdapter(
            api_keys=[api_key],
            model=candidate.model_id,
            base_url=candidate.base_url,
            provider_name=candidate.provider_name,
            max_tokens=candidate.max_tokens,
        )
    return OpenAIAdapter(
        api_key=api_key,
        model=candidate.model_id,
        base_url=candidate.base_url,
        provider_name=candidate.provider_name,
        max_tokens=candidate.max_tokens,
    )


async def _record_result(
    db: AsyncSession,
    candidate: Candidate,
    response: LLMResponse,
    *,
    commit: bool = False,
) -> None:
    """Persist route health without opening a competing database session.

    The previous implementation wrote through a second session while the chat
    session still held a read transaction. Embedded SQLite/Turso replicas can
    serialize that pattern and make a completed provider call appear to hang.
    Reusing the request session also avoids an extra remote sync per turn.
    """
    now = datetime.now(timezone.utc)
    model = await db.get(LLMModelConfig, candidate.model_pk)
    provider = await db.get(LLMProvider, candidate.provider_pk)
    if model is None or provider is None:
        return
    model.last_used_at = now
    model.status = "healthy" if response.ok else "degraded"
    provider.status = model.status
    provider.last_checked_at = now
    if response.ok:
        model.consecutive_failures = 0
        model.circuit_open_until = None
        model.last_error = ""
        model.last_success_at = now
        provider.last_error = ""
        provider.last_success_at = now
    else:
        model.consecutive_failures += 1
        model.last_error = response.error[:500]
        provider.last_error = response.error[:500]
        if model.consecutive_failures >= settings.LLM_FAILURE_THRESHOLD:
            model.status = "circuit_open"
            model.circuit_open_until = now + timedelta(
                seconds=settings.LLM_CIRCUIT_COOLDOWN_SECONDS
            )
    if commit:
        await db.commit()
    else:
        await db.flush()


class RoutingAdapter:
    """Select a healthy model for each completion and fail over transparently.

    The exact provider/model that produced a reply is always returned; a
    ``fallback_reason`` is set when the labelled offline planner is used.
    """

    name = "router"
    model = "balanced-pool"

    def __init__(
        self,
        db: AsyncSession,
        *,
        user_id: str = "",
        conversation_id: str = "",
        request_id: str = "",
        model_override: str | None = None,
    ) -> None:
        self.db = db
        self.user_id = user_id
        self.conversation_id = conversation_id
        self.request_id = request_id
        self.model_override = model_override

    async def _log(
        self,
        candidate: Candidate | None,
        response: LLMResponse,
        started: float,
        *,
        streamed: bool = False,
    ) -> None:
        classified = classify_provider_error(response.error) if not response.ok else None
        self.db.add(
            LLMRequestLog(
                user_id=self.user_id,
                conversation_id=self.conversation_id,
                request_id=self.request_id,
                provider=response.provider or (candidate.provider_name if candidate else "mock"),
                model=response.model or (candidate.model_id if candidate else "armx-offline-planner"),
                status="ok" if response.ok else "error",
                error_code=response.error_code or (classified.code if classified else ""),
                error=(response.error or "")[:500],
                latency_ms=int((time.monotonic() - started) * 1000),
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                streamed=streamed,
            )
        )
        await self.db.flush()

    async def _attempt(
        self,
        candidate: Candidate,
        messages: list[LLMMessage],
        tool_schemas: list[dict[str, Any]],
        *,
        on_delta: Callable[[str], Awaitable[None]] | None = None,
    ) -> LLMResponse:
        await validate_provider_url(candidate.base_url)
        adapter = _adapter(candidate)
        schemas = tool_schemas if candidate.supports_tools else []
        if on_delta is not None:
            return await adapter.stream(messages, schemas, on_delta)
        return await adapter.complete(messages, schemas)

    async def _candidate_response(
        self,
        candidate: Candidate,
        messages: list[LLMMessage],
        tool_schemas: list[dict[str, Any]],
        attempt_timeout: float,
        *,
        on_delta: Callable[[str], Awaitable[None]] | None = None,
    ) -> LLMResponse:
        started = time.monotonic()
        # One bounded retry for retryable provider failures (429/5xx/timeouts).
        for retry in range(2):
            try:
                response = await asyncio.wait_for(
                    self._attempt(candidate, messages, tool_schemas, on_delta=on_delta),
                    timeout=attempt_timeout,
                )
            except TimeoutError:
                response = LLMResponse(
                    finish_reason=FinishReason.ERROR,
                    error=f"provider attempt exceeded {attempt_timeout:.1f}s deadline",
                    model=candidate.model_id,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.exception(
                    "Unexpected failure from LLM route %s/%s",
                    candidate.provider_name,
                    candidate.model_id,
                )
                response = LLMResponse(
                    finish_reason=FinishReason.ERROR,
                    error=f"{type(exc).__name__}: {exc}",
                    model=candidate.model_id,
                )
            response.provider = candidate.provider_name
            if not response.model:
                response.model = candidate.model_id
            classified = classify_provider_error(response.error) if not response.ok else None
            if classified and not response.error_code:
                response.error_code = classified.code
            if response.ok or retry == 1 or not (classified and classified.retryable):
                break
            await asyncio.sleep(0.4 * (retry + 1))
        await _record_result(self.db, candidate, response)
        await self._log(candidate, response, started, streamed=bool(response.streamed))
        return response

    def _candidates_sync(self, candidates: list[Candidate]) -> list[Candidate]:
        if self.model_override:
            exact = [c for c in candidates if c.model_id == self.model_override]
            if exact:
                return exact
        return candidates

    async def complete(
        self, messages: list[LLMMessage], tool_schemas: list[dict[str, Any]]
    ) -> LLMResponse:
        candidates = self._candidates_sync(await load_candidates(self.db))
        errors: list[str] = []
        deadline = time.monotonic() + settings.LLM_ROUTE_TIMEOUT_SECONDS

        for candidate in candidates:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                errors.append(
                    "routing deadline exhausted before all candidates were attempted"
                )
                break
            response = await self._candidate_response(
                candidate, messages, tool_schemas, min(settings.LLM_TIMEOUT_SECONDS, remaining)
            )
            if response.ok:
                return response
            errors.append(
                f"{candidate.provider_name}/{candidate.model_id}: {response.error}"
            )
            log.warning("LLM route failed; trying next candidate: %s", errors[-1][:500])

        fallback = MockAdapter()
        response = await fallback.complete(messages, tool_schemas)
        response.provider = fallback.name
        response.fallback_reason = "; ".join(errors)[:800] if errors else "no live model route is enabled"
        await self._log(None, response, time.monotonic() - 0.001)
        if errors:
            log.error(
                "All live LLM routes failed; using labelled offline planner: %s",
                " | ".join(errors)[:1500],
            )
        return response

    async def stream(
        self,
        messages: list[LLMMessage],
        tool_schemas: list[dict[str, Any]],
        on_delta: Callable[[str], Awaitable[None]],
    ) -> LLMResponse:
        """Stream only from a route that actually succeeds.

        Candidate deltas are buffered locally: a route that fails halfway never
        leaks partial text into the user's message. The successful buffer is
        flushed in order, then the offline planner's clearly labelled reply is
        used if every live route failed.
        """
        candidates = self._candidates_sync(await load_candidates(self.db))
        errors: list[str] = []
        deadline = time.monotonic() + settings.LLM_ROUTE_TIMEOUT_SECONDS

        for candidate in candidates:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                errors.append("routing deadline exhausted before all candidates were attempted")
                break
            buffer: list[str] = []

            async def collect(piece: str) -> None:
                buffer.append(piece)

            response = await self._candidate_response(
                candidate,
                messages,
                tool_schemas,
                min(settings.LLM_TIMEOUT_SECONDS, remaining),
                on_delta=collect,
            )
            if response.ok:
                for piece in buffer:
                    await on_delta(piece)
                return response
            errors.append(f"{candidate.provider_name}/{candidate.model_id}: {response.error}")

        fallback = MockAdapter()
        response = await fallback.stream(messages, tool_schemas, on_delta)
        response.provider = fallback.name
        response.fallback_reason = "; ".join(errors)[:800] if errors else "no live model route is enabled"
        await self._log(None, response, time.monotonic() - 0.001)
        return response


async def probe_model(db: AsyncSession, model_id: str) -> LLMResponse:
    row = (
        await db.execute(
            select(LLMModelConfig, LLMProvider)
            .join(LLMProvider, LLMProvider.id == LLMModelConfig.provider_id)
            .where(LLMModelConfig.id == model_id)
        )
    ).first()
    if row is None:
        raise LookupError("Model route not found")
    model, provider = row
    candidate = Candidate(
        model_pk=model.id,
        provider_pk=provider.id,
        provider_name=provider.name,
        provider_kind=provider.kind,
        base_url=provider.base_url,
        api_key_encrypted=provider.api_key_encrypted,
        model_id=model.model_id,
        priority=model.priority,
        weight=model.weight,
        max_tokens=min(model.max_tokens, 32),
        supports_tools=model.supports_tools,
    )

    async def attempt() -> LLMResponse:
        await validate_provider_url(candidate.base_url)
        return await _adapter(candidate).complete(
            [LLMMessage(role="user", content="Reply with exactly: OK")], []
        )

    try:
        response = await asyncio.wait_for(
            attempt(), timeout=settings.LLM_TIMEOUT_SECONDS
        )
    except TimeoutError:
        response = LLMResponse(
            finish_reason=FinishReason.ERROR,
            error=f"provider probe exceeded {settings.LLM_TIMEOUT_SECONDS:.1f}s deadline",
            model=candidate.model_id,
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.exception("Unexpected failure probing %s/%s", provider.name, model.model_id)
        response = LLMResponse(
            finish_reason=FinishReason.ERROR,
            error=f"{type(exc).__name__}: {exc}",
            model=candidate.model_id,
        )
    response.provider = candidate.provider_name
    await _record_result(db, candidate, response, commit=True)
    return response


async def provider_status_async(db: AsyncSession) -> dict[str, Any]:
    total = int(
        (
            await db.execute(
                select(func.count(LLMModelConfig.id))
                .join(LLMProvider, LLMProvider.id == LLMModelConfig.provider_id)
                .where(LLMModelConfig.enabled.is_(True), LLMProvider.enabled.is_(True))
            )
        ).scalar_one()
    )
    healthy = int(
        (
            await db.execute(
                select(func.count(LLMModelConfig.id))
                .join(LLMProvider, LLMProvider.id == LLMModelConfig.provider_id)
                .where(
                    LLMModelConfig.enabled.is_(True),
                    LLMProvider.enabled.is_(True),
                    LLMModelConfig.status == "healthy",
                )
            )
        ).scalar_one()
    )
    unverified = int(
        (
            await db.execute(
                select(func.count(LLMModelConfig.id))
                .join(LLMProvider, LLMProvider.id == LLMModelConfig.provider_id)
                .where(
                    LLMModelConfig.enabled.is_(True),
                    LLMProvider.enabled.is_(True),
                    LLMModelConfig.status == "unknown",
                )
            )
        ).scalar_one()
    )
    first = (
        await db.execute(
            select(LLMModelConfig, LLMProvider)
            .join(LLMProvider, LLMProvider.id == LLMModelConfig.provider_id)
            .where(LLMModelConfig.enabled.is_(True), LLMProvider.enabled.is_(True))
            .order_by(LLMModelConfig.priority.asc(), LLMModelConfig.weight.desc())
            .limit(1)
        )
    ).first()
    model_rows = (
        await db.execute(
            select(LLMModelConfig, LLMProvider)
            .join(LLMProvider, LLMProvider.id == LLMModelConfig.provider_id)
            .where(LLMModelConfig.enabled.is_(True), LLMProvider.enabled.is_(True))
            .order_by(LLMModelConfig.priority.asc(), LLMModelConfig.weight.desc())
        )
    ).all()
    return {
        "provider": first[1].name if first else "mock",
        "model": first[0].model_id if first else "offline-rules-v1",
        "models": [
            {
                "id": m.id,
                "provider": p.name,
                "model": m.model_id,
                "display_name": m.display_name or m.model_id,
                "status": m.status,
                "supports_tools": m.supports_tools,
                "priority": m.priority,
                "last_error": m.last_error,
                "last_success_at": m.last_success_at.isoformat() if m.last_success_at else None,
            }
            for m, p in model_rows
        ],
        # `live` means configured/enabled, not that a completion probe passed.
        # Callers must use `ready`/`readiness` for an honest health indicator.
        "live": bool(first),
        "ready": healthy > 0,
        "readiness": (
            "verified"
            if healthy > 0
            else "unverified"
            if unverified > 0
            else "degraded"
            if total > 0
            else "offline"
        ),
        "routing": settings.LLM_ROUTING_STRATEGY,
        "enabled_models": total,
        "healthy_models": healthy,
        "unverified_models": unverified,
        "configured_provider": settings.LLM_PROVIDER,
        "key_pool_size": total,
    }


async def seed_environment_providers(db: AsyncSession) -> int:
    """Upsert environment-owned routes so Render variables work immediately."""
    if not settings.LLM_SECRETS_KEY:
        if any(
            (
                settings.GROQ_API_KEY,
                settings.OPENAI_API_KEY,
                settings.anthropic_key_pool,
            )
        ):
            log.warning(
                "Live LLM keys are set but LLM_SECRETS_KEY is missing; environment routes were not seeded"
            )
        return 0

    # Environment-owned providers mirror current Render variables: removing a
    # key disables its old route instead of silently retaining a stale secret.
    await db.execute(
        update(LLMProvider)
        .where(LLMProvider.source == "environment")
        .values(enabled=False)
    )

    definitions: list[dict[str, Any]] = []
    if settings.GROQ_API_KEY:
        definitions.append(
            {
                "name": "groq",
                "display_name": "Groq",
                "kind": "openai_compatible",
                "base_url": settings.GROQ_BASE_URL,
                "api_key": settings.GROQ_API_KEY,
                "model_id": settings.GROQ_MODEL,
                "model_name": "Meta Llama 3.3 70B",
                "priority": 10,
            }
        )
    if settings.OPENAI_API_KEY:
        definitions.append(
            {
                "name": "openai",
                "display_name": "OpenAI",
                "kind": "openai_compatible",
                "base_url": settings.OPENAI_BASE_URL,
                "api_key": settings.OPENAI_API_KEY,
                "model_id": settings.OPENAI_MODEL,
                "model_name": settings.OPENAI_MODEL,
                "priority": 20,
            }
        )
    for index, key in enumerate(settings.anthropic_key_pool, start=1):
        definitions.append(
            {
                "name": "anthropic" if index == 1 else f"anthropic-{index}",
                "display_name": "Anthropic" if index == 1 else f"Anthropic key {index}",
                "kind": "anthropic",
                "base_url": settings.ANTHROPIC_BASE_URL,
                "api_key": key,
                "model_id": settings.ANTHROPIC_MODEL,
                "model_name": settings.ANTHROPIC_MODEL,
                "priority": 20,
            }
        )

    changed = 0
    for item in definitions:
        provider = (
            await db.execute(
                select(LLMProvider).where(LLMProvider.name == item["name"])
            )
        ).scalar_one_or_none()
        encrypted = encrypt_secret(item["api_key"])
        if provider is None:
            provider = LLMProvider(
                name=item["name"],
                display_name=item["display_name"],
                kind=item["kind"],
                base_url=item["base_url"],
                api_key_encrypted=encrypted,
                api_key_hint=secret_hint(item["api_key"]),
                enabled=True,
                source="environment",
            )
            db.add(provider)
            await db.flush()
            changed += 1
        elif provider.source == "environment":
            provider.display_name = item["display_name"]
            provider.kind = item["kind"]
            provider.base_url = item["base_url"]
            provider.api_key_encrypted = encrypted
            provider.api_key_hint = secret_hint(item["api_key"])
            provider.enabled = True

        await db.execute(
            update(LLMModelConfig)
            .where(
                LLMModelConfig.provider_id == provider.id,
                LLMModelConfig.model_id != item["model_id"],
            )
            .values(enabled=False)
        )
        model = (
            await db.execute(
                select(LLMModelConfig).where(
                    LLMModelConfig.provider_id == provider.id,
                    LLMModelConfig.model_id == item["model_id"],
                )
            )
        ).scalar_one_or_none()
        if model is None:
            db.add(
                LLMModelConfig(
                    provider_id=provider.id,
                    model_id=item["model_id"],
                    display_name=item["model_name"],
                    enabled=True,
                    priority=item["priority"],
                    weight=100,
                    supports_tools=True,
                    max_tokens=settings.LLM_MAX_TOKENS,
                )
            )
            changed += 1
        else:
            model.display_name = item["model_name"]
            model.enabled = True
            model.priority = item["priority"]
            model.max_tokens = settings.LLM_MAX_TOKENS
    await db.commit()
    return changed
