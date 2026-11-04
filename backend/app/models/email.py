"""Durable Resend delivery ledger.

A 2xx response from Resend means the API *accepted* a request. It does not mean
the message reached the mailbox. Webhook events advance the status to sent,
delivered, bounced, complained or failed. Nothing here stores an API key or raw
reset/verification token.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IDFormatMixin, TimestampMixin, utcnow


class EmailDelivery(IDFormatMixin, TimestampMixin, Base):
    __tablename__ = "email_deliveries"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_email_delivery_idempotency"),
        Index("ix_email_delivery_recipient_purpose", "recipient", "purpose", "created_at"),
        Index("ix_email_delivery_provider_message", "provider_message_id"),
    )

    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True
    )
    recipient: Mapped[str] = mapped_column(String(320), nullable=False)
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)  # password_reset | email_verification
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), default="resend", nullable=False)
    provider_message_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    # requested -> accepted -> sent -> delivered | bounced | complained | failed
    status: Mapped[str] = mapped_column(String(24), default="requested", nullable=False, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(256), nullable=False)
    request_id: Mapped[str] = mapped_column(String(64), default="", nullable=False, index=True)
    last_error: Mapped[str] = mapped_column(Text, default="", nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EmailDeliveryEvent(IDFormatMixin, Base):
    """One row per Svix event id: Resend retries are at-least-once."""

    __tablename__ = "email_delivery_events"
    __table_args__ = (UniqueConstraint("event_id", name="uq_email_delivery_event_id"),)

    delivery_id: Mapped[str | None] = mapped_column(
        ForeignKey("email_deliveries.id", ondelete="SET NULL"), index=True, nullable=True
    )
    event_id: Mapped[str] = mapped_column(String(160), nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="", nullable=False)
    provider_message_id: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    detail: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


__all__ = ["EmailDelivery", "EmailDeliveryEvent"]
