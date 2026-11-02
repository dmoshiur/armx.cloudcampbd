"""Linked and managed-device models (consent based; owner controlled)."""
from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
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
    """Server -> device command queue. Every supported command is user-visible."""

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
    """Legacy mirror-session record retained for migration compatibility."""

    __tablename__ = "screen_share_sessions"

    device_id: Mapped[str] = mapped_column(ForeignKey("linked_devices.id", ondelete="CASCADE"), index=True)
    started_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_by: Mapped[str | None] = mapped_column(String(32), nullable=True)


class ManagedDevicePolicy(IDFormatMixin, TimestampMixin, Base):
    """Owner-authored policy that still requires local passcode approval to apply."""

    __tablename__ = "managed_device_policies"

    device_id: Mapped[str] = mapped_column(
        ForeignKey("linked_devices.id", ondelete="CASCADE"), unique=True, index=True, nullable=False
    )
    policy_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    kiosk_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    launcher_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    usage_telemetry_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    allowed_packages: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    restrictions: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    local_approval_required: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    updated_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    last_applied_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str] = mapped_column(String(500), default="", nullable=False)


class DeviceAppUsage(IDFormatMixin, Base):
    """Permission-scoped aggregate only: package, duration and launch count."""

    __tablename__ = "device_app_usage"
    __table_args__ = (
        UniqueConstraint("device_id", "package_name", "window_start", "window_end", name="uq_device_usage_window"),
    )

    device_id: Mapped[str] = mapped_column(
        ForeignKey("linked_devices.id", ondelete="CASCADE"), index=True, nullable=False
    )
    package_name: Mapped[str] = mapped_column(String(255), nullable=False)
    foreground_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    launch_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class DeviceConsentSession(IDFormatMixin, Base):
    """Explicit device decision and visible indicator for mirror/voice sessions."""

    __tablename__ = "device_consent_sessions"

    device_id: Mapped[str] = mapped_column(
        ForeignKey("linked_devices.id", ondelete="CASCADE"), index=True, nullable=False
    )
    requested_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)  # screen_share | voice
    status: Mapped[str] = mapped_column(String(24), default="requested", nullable=False)
    scopes: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    visible_indicator: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consented_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_by: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    device_note: Mapped[str] = mapped_column(String(300), default="", nullable=False)
