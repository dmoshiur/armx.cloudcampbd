"""Linked-device models (consent based pairing, owner-password unlink)."""
from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IDFormatMixin, TimestampMixin, utcnow


class DeviceStatus(str, enum.Enum):
    PENDING = "pending"
    ACTIVE = "active"
    REVOKED = "revoked"


class LinkedDevice(IDFormatMixin, TimestampMixin, Base):
    __tablename__ = "linked_devices"

    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    platform: Mapped[str] = mapped_column(String(32), default="android", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default=DeviceStatus.PENDING.value, nullable=False)

    # Pairing is always initiated on the device itself: the device generates the code.
    pairing_code_hash: Mapped[str | None] = mapped_column(String(128), nullable=True, unique=True)
    pairing_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    pairing_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Set by the DEVICE OWNER at pairing time. Never readable, never resettable by admin/VIP.
    unlink_password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    # Persistent "Linked" notification state - there is no silent mode.
    persistent_notification: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notification_ack_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    capabilities: Mapped[str] = mapped_column(Text, default="alarm,app_launch,state,calls", nullable=False)
    device_token_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)

    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ip_address: Mapped[str] = mapped_column(String(64), default="", nullable=False)


class DeviceUnlinkEvent(IDFormatMixin, Base):
    __tablename__ = "device_unlink_events"

    device_id: Mapped[str] = mapped_column(ForeignKey("linked_devices.id", ondelete="CASCADE"), index=True)
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    reason: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    password_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    ip_address: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class DeviceCommand(IDFormatMixin, Base):
    """Server -> device command queue the native app polls. No silent commands exist."""

    __tablename__ = "device_commands"

    device_id: Mapped[str] = mapped_column(ForeignKey("linked_devices.id", ondelete="CASCADE"), index=True)
    issued_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    command: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="queued", nullable=False)  # queued|delivered|done|failed
    result: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    visible_to_user: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ScreenShareSession(IDFormatMixin, Base):
    """Live mirroring is always a visibly-flagged, instantly endable session."""

    __tablename__ = "screen_share_sessions"

    device_id: Mapped[str] = mapped_column(ForeignKey("linked_devices.id", ondelete="CASCADE"), index=True)
    started_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
