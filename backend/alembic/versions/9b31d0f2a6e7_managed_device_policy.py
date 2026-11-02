"""add managed-device policy, aggregate usage and consent sessions

Revision ID: 9b31d0f2a6e7
Revises: 6a2f7c4d91b8
Create Date: 2026-11-02 15:10:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "9b31d0f2a6e7"
down_revision: Union[str, None] = "6a2f7c4d91b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "managed_device_policies",
        sa.Column("device_id", sa.String(length=32), nullable=False),
        sa.Column("policy_version", sa.Integer(), nullable=False),
        sa.Column("kiosk_enabled", sa.Boolean(), nullable=False),
        sa.Column("launcher_enabled", sa.Boolean(), nullable=False),
        sa.Column("usage_telemetry_enabled", sa.Boolean(), nullable=False),
        sa.Column("allowed_packages", sa.Text(), nullable=False),
        sa.Column("restrictions", sa.Text(), nullable=False),
        sa.Column("local_approval_required", sa.Boolean(), nullable=False),
        sa.Column("updated_by", sa.String(length=32), nullable=False),
        sa.Column("last_applied_version", sa.Integer(), nullable=False),
        sa.Column("last_applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=500), nullable=False),
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["linked_devices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_managed_device_policies_device_id"), "managed_device_policies", ["device_id"], unique=True)

    op.create_table(
        "device_app_usage",
        sa.Column("device_id", sa.String(length=32), nullable=False),
        sa.Column("package_name", sa.String(length=255), nullable=False),
        sa.Column("foreground_seconds", sa.Integer(), nullable=False),
        sa.Column("launch_count", sa.Integer(), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["linked_devices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("device_id", "package_name", "window_start", "window_end", name="uq_device_usage_window"),
    )
    op.create_index(op.f("ix_device_app_usage_device_id"), "device_app_usage", ["device_id"], unique=False)

    op.create_table(
        "device_consent_sessions",
        sa.Column("device_id", sa.String(length=32), nullable=False),
        sa.Column("requested_by", sa.String(length=32), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("scopes", sa.Text(), nullable=False),
        sa.Column("visible_indicator", sa.Boolean(), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consented_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_by", sa.String(length=32), nullable=False),
        sa.Column("device_note", sa.String(length=300), nullable=False),
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["linked_devices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_device_consent_sessions_device_id"), "device_consent_sessions", ["device_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_device_consent_sessions_device_id"), table_name="device_consent_sessions")
    op.drop_table("device_consent_sessions")
    op.drop_index(op.f("ix_device_app_usage_device_id"), table_name="device_app_usage")
    op.drop_table("device_app_usage")
    op.drop_index(op.f("ix_managed_device_policies_device_id"), table_name="managed_device_policies")
    op.drop_table("managed_device_policies")
