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


class Message(IDFormatMixin, Base):
    __tablename__ = "messages"

    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, default="", nullable=False)
    tool_calls: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


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
