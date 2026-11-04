"""Tool registry persistence, approvals, audit chain, integrations, projects."""
from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IDFormatMixin, TimestampMixin, utcnow


class ToolDefinition(IDFormatMixin, TimestampMixin, Base):
    __tablename__ = "tool_definitions"

    name: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    description: Mapped[str] = mapped_column(String(400), default="", nullable=False)
    risk_tier: Mapped[str] = mapped_column(String(16), nullable=False)
    scopes: Mapped[str] = mapped_column(String(400), default="", nullable=False)
    enabled_global: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    confirm_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    rate_limit_per_minute: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    dry_run_supported: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class ToolUserOverride(IDFormatMixin, Base):
    __tablename__ = "tool_user_overrides"
    __table_args__ = (UniqueConstraint("user_id", "tool_name", name="uq_tool_user"),)

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    tool_name: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class LLMProvider(IDFormatMixin, TimestampMixin, Base):
    """An administrator-managed API endpoint. Credentials are encrypted."""

    __tablename__ = "llm_providers"

    name: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)  # openai_compatible | anthropic
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    api_key_encrypted: Mapped[str] = mapped_column(Text, default="", nullable=False)
    api_key_hint: Mapped[str] = mapped_column(String(32), default="not set", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    source: Mapped[str] = mapped_column(String(24), default="admin", nullable=False)  # admin | environment
    status: Mapped[str] = mapped_column(String(24), default="unknown", nullable=False)
    last_error: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LLMModelConfig(IDFormatMixin, TimestampMixin, Base):
    """A routable model. Equal priority values form a weighted balance tier."""

    __tablename__ = "llm_models"
    __table_args__ = (UniqueConstraint("provider_id", "model_id", name="uq_llm_provider_model"),)

    provider_id: Mapped[str] = mapped_column(
        ForeignKey("llm_providers.id", ondelete="CASCADE"), index=True, nullable=False
    )
    model_id: Mapped[str] = mapped_column(String(160), nullable=False)
    display_name: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    weight: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    supports_tools: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    max_tokens: Mapped[int] = mapped_column(Integer, default=4096, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="unknown", nullable=False)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    circuit_open_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ApprovalStatus(str, enum.Enum):
    PENDING = "pending"
    CONSUMED = "consumed"
    DENIED = "denied"
    EXPIRED = "expired"


class Approval(IDFormatMixin, Base):
    """A MEDIUM/HIGH action is bound to a hash of tool+args+actor+session+expiry.

    Changing any single argument produces a different hash and invalidates it.
    """

    __tablename__ = "approvals"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    session_id: Mapped[str] = mapped_column(String(32), nullable=False)
    run_id: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    tool_name: Mapped[str] = mapped_column(String(64), nullable=False)
    risk_tier: Mapped[str] = mapped_column(String(16), nullable=False)
    args_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    args_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    action_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), default=ApprovalStatus.PENDING.value, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class AuditEvent(IDFormatMixin, Base):
    """Append-only, hash-chained audit log (tamper evident)."""

    __tablename__ = "audit_events"

    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True, nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    actor_email: Mapped[str] = mapped_column(String(320), default="", nullable=False)
    actor_role: Mapped[str] = mapped_column(String(16), default="", nullable=False)
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    risk_tier: Mapped[str] = mapped_column(String(16), default="", nullable=False)
    target: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="ok", nullable=False)
    ip_address: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    user_agent: Mapped[str] = mapped_column(String(400), default="", nullable=False)
    detail: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    prev_hash: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    entry_hash: Mapped[str] = mapped_column(String(64), default="", nullable=False, index=True)


class IntegrationConnection(IDFormatMixin, TimestampMixin, Base):
    """Only *references* to secrets are stored - never the secret itself."""

    __tablename__ = "integration_connections"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    secret_ref: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    config: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="connected", nullable=False)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class GeneratedProject(IDFormatMixin, TimestampMixin, Base):
    __tablename__ = "generated_projects"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="draft", nullable=False)  # draft|preview|deployed|failed
    files: Mapped[str] = mapped_column(Text, default="{}", nullable=False)  # JSON {path: content}
    lint_status: Mapped[str] = mapped_column(String(16), default="unknown", nullable=False)
    lint_report: Mapped[str] = mapped_column(Text, default="{}", nullable=False)

    repo_owner: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    repo_full_name: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    repo_url: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    repo_is_platform_owned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    vercel_project: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    vercel_url: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    deploy_status: Mapped[str] = mapped_column(String(24), default="", nullable=False)
    turso_db_ref: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    # Provider-confirmed deployment tracking. Empty = no provider confirmation.
    deployment_id: Mapped[str] = mapped_column(String(200), default="", nullable=False, server_default="")
    deploy_provider: Mapped[str] = mapped_column(String(40), default="", nullable=False, server_default="")
    deploy_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deploy_message: Mapped[str] = mapped_column(Text, default="", nullable=False, server_default="")
    simulated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, server_default="0")


class MessagingProfile(IDFormatMixin, TimestampMixin, Base):
    __tablename__ = "messaging_profiles"
    __table_args__ = (UniqueConstraint("user_id", "channel", "contact_id", name="uq_msg_profile"),)

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    channel: Mapped[str] = mapped_column(String(24), default="whatsapp", nullable=False)
    contact_id: Mapped[str] = mapped_column(String(120), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    personality: Mapped[str] = mapped_column(Text, default="", nullable=False)
    auto_send: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)  # approved contact only
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class AutomationRule(IDFormatMixin, TimestampMixin, Base):
    __tablename__ = "automation_rules"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    trigger: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    action: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class SystemFlag(IDFormatMixin, TimestampMixin, Base):
    __tablename__ = "system_flags"

    key: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    value: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    updated_by: Mapped[str] = mapped_column(String(32), default="", nullable=False)


class Conversation(IDFormatMixin, TimestampMixin, Base):
    __tablename__ = "conversations"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(160), default="New chat", nullable=False)
    # Durable conversation management (migration b7e41c9d2a10).
    archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, server_default="0")
    pinned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, server_default="0")
    model: Mapped[str] = mapped_column(String(160), default="", nullable=False, server_default="")
    token_usage: Mapped[int] = mapped_column(Integer, default=0, nullable=False, server_default="0")
    project_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False, server_default="")
    message_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False, server_default="0")


class Message(IDFormatMixin, Base):
    __tablename__ = "messages"

    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, default="", nullable=False)
    tool_calls: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    # Exact model + accounting for this message (never guessed on the client).
    model: Mapped[str] = mapped_column(String(160), default="", nullable=False, server_default="")
    provider: Mapped[str] = mapped_column(String(64), default="", nullable=False, server_default="")
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False, server_default="0")
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False, server_default="0")
    status: Mapped[str] = mapped_column(String(16), default="complete", nullable=False, server_default="complete")
    error: Mapped[str] = mapped_column(Text, default="", nullable=False, server_default="")
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ChatRun(IDFormatMixin, TimestampMixin, Base):
    """Durable harness state so an approval can resume exactly where it paused."""

    __tablename__ = "chat_runs"

    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    session_id: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="running", nullable=False)
    messages_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    pending_approval_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    paused_call_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    steps: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    request_id: Mapped[str] = mapped_column(String(32), default="", nullable=False, server_default="")
    provider: Mapped[str] = mapped_column(String(64), default="", nullable=False, server_default="")
    model: Mapped[str] = mapped_column(String(160), default="", nullable=False, server_default="")
    stopped: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, server_default="0")


# ---------------------------------------------------------------------------
# Workspace intelligence (migration b7e41c9d2a10)
# ---------------------------------------------------------------------------
class UserPreference(IDFormatMixin, TimestampMixin, Base):
    """Server-side, per-user UI/AI preferences. No secrets are stored here."""

    __tablename__ = "user_preferences"

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True, nullable=False
    )
    settings: Mapped[str] = mapped_column(Text, default="{}", nullable=False)


class MemoryItem(IDFormatMixin, TimestampMixin, Base):
    """Structured long-term memory. Chat history is NOT memory by default."""

    __tablename__ = "memory_items"
    __table_args__ = (UniqueConstraint("user_id", "content_hash", name="uq_memory_user_hash"),)

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    category: Mapped[str] = mapped_column(String(40), default="explicit_instruction", nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(24), default="explicit", nullable=False)
    source_conversation_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    importance: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    keywords: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    use_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class MessageFeedback(IDFormatMixin, Base):
    __tablename__ = "message_feedback"
    __table_args__ = (UniqueConstraint("user_id", "message_id", name="uq_feedback_user_message"),)

    user_id: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    message_id: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    rating: Mapped[str] = mapped_column(String(16), nullable=False)  # up | down
    comment: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class LLMRequestLog(IDFormatMixin, Base):
    """Per-attempt provider observability. Contains no prompts or keys."""

    __tablename__ = "llm_request_logs"

    user_id: Mapped[str] = mapped_column(String(32), default="", index=True, nullable=False)
    conversation_id: Mapped[str] = mapped_column(String(32), default="", index=True, nullable=False)
    request_id: Mapped[str] = mapped_column(String(32), default="", index=True, nullable=False)
    provider: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    model: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="ok", nullable=False)
    error_code: Mapped[str] = mapped_column(String(48), default="", nullable=False)
    error: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    streamed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class ProjectVersion(IDFormatMixin, Base):
    """Immutable snapshot of generated project files, for real version history."""

    __tablename__ = "project_versions"
    __table_args__ = (UniqueConstraint("project_id", "version", name="uq_project_version"),)

    project_id: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    files_json: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    created_by: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class RateLimitCounter(IDFormatMixin, Base):
    __tablename__ = "rate_limit_counters"

    bucket: Mapped[str] = mapped_column(String(160), index=True, nullable=False)
    window_start: Mapped[int] = mapped_column(Integer, nullable=False)
    count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class SearchLog(IDFormatMixin, Base):
    """Web/tool output is DATA. We keep a copy for prompt-injection review."""

    __tablename__ = "tool_output_log"

    user_id: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    tool_name: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class Ticket(IDFormatMixin, Base):
    """Short-lived, single-use proof issued after an out-of-band check.

    Used where a secret must never travel through the LLM: verifying a linked
    device's unlink password in the UI mints a ticket that a tool can spend,
    instead of the tool ever handling the password.
    """

    __tablename__ = "tickets"

    kind: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    user_id: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    subject: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
