"""Resend auth email delivery ledger and webhook event deduplication.

Additive only: existing users, password hashes, sessions and reset tokens are
preserved. No plaintext token or API key is stored.

Revision ID: c9f2a1d34e77
Revises: b7e41c9d2a10
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c9f2a1d34e77"
down_revision: Union[str, None] = "b7e41c9d2a10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "email_deliveries",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_id", sa.String(length=32), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("recipient", sa.String(length=320), nullable=False),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("subject", sa.String(length=200), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False, server_default=sa.text("'resend'")),
        sa.Column("provider_message_id", sa.String(length=160), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False, server_default=sa.text("'requested'")),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("idempotency_key", sa.String(length=256), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=False, server_default=sa.text("''")),
        sa.Column("last_error", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("idempotency_key", name="uq_email_delivery_idempotency"),
    )
    op.create_index("ix_email_deliveries_user_id", "email_deliveries", ["user_id"])
    op.create_index("ix_email_deliveries_status", "email_deliveries", ["status"])
    op.create_index("ix_email_deliveries_request_id", "email_deliveries", ["request_id"])
    op.create_index("ix_email_deliveries_provider_message_id", "email_deliveries", ["provider_message_id"])
    op.create_index(
        "ix_email_delivery_recipient_purpose",
        "email_deliveries",
        ["recipient", "purpose", "created_at"],
    )

    op.create_table(
        "email_delivery_events",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("delivery_id", sa.String(length=32), sa.ForeignKey("email_deliveries.id", ondelete="SET NULL"), nullable=True),
        sa.Column("event_id", sa.String(length=160), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default=sa.text("''")),
        sa.Column("provider_message_id", sa.String(length=160), nullable=False, server_default=sa.text("''")),
        sa.Column("detail", sa.Text(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("event_id", name="uq_email_delivery_event_id"),
    )
    op.create_index("ix_email_delivery_events_delivery_id", "email_delivery_events", ["delivery_id"])


def downgrade() -> None:
    op.drop_index("ix_email_delivery_events_delivery_id", table_name="email_delivery_events")
    op.drop_table("email_delivery_events")
    op.drop_index("ix_email_delivery_recipient_purpose", table_name="email_deliveries")
    op.drop_index("ix_email_deliveries_provider_message_id", table_name="email_deliveries")
    op.drop_index("ix_email_deliveries_request_id", table_name="email_deliveries")
    op.drop_index("ix_email_deliveries_status", table_name="email_deliveries")
    op.drop_index("ix_email_deliveries_user_id", table_name="email_deliveries")
    op.drop_table("email_deliveries")
