"""Workspace intelligence: durable conversations, memory, usage, versions.

Adds only nullable/defaulted columns and new tables; existing rows and every
existing API remain valid. No data is migrated out of the browser.

Revision ID: b7e41c9d2a10
Revises: 9b31d0f2a6e7
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b7e41c9d2a10"
down_revision: Union[str, None] = "9b31d0f2a6e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _col(table: str, name: str, type_: sa.types.TypeEngine, *, server_default: str) -> None:
    op.add_column(
        table,
        sa.Column(name, type_, nullable=False, server_default=sa.text(server_default)),
    )


def upgrade() -> None:
    bool_false = "'0'"
    str_empty = "''"
    int_zero = "0"

    for name, type_, default in (
        ("archived", sa.Boolean(), bool_false),
        ("pinned", sa.Boolean(), bool_false),
        ("model", sa.String(160), str_empty),
        ("token_usage", sa.Integer(), int_zero),
        ("summary", sa.Text(), str_empty),
        ("message_count", sa.Integer(), int_zero),
    ):
        _col("conversations", name, type_, server_default=default)
    op.add_column("conversations", sa.Column("project_id", sa.String(32), nullable=True))

    for name, type_, default in (
        ("model", sa.String(160), str_empty),
        ("provider", sa.String(64), str_empty),
        ("input_tokens", sa.Integer(), int_zero),
        ("output_tokens", sa.Integer(), int_zero),
        ("status", sa.String(16), "'complete'"),
        ("error", sa.Text(), str_empty),
    ):
        _col("messages", name, type_, server_default=default)
    op.add_column("messages", sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True))

    for name, type_, default in (
        ("request_id", sa.String(32), str_empty),
        ("provider", sa.String(64), str_empty),
        ("model", sa.String(160), str_empty),
        ("stopped", sa.Boolean(), bool_false),
    ):
        _col("chat_runs", name, type_, server_default=default)

    for name, type_, default in (
        ("deployment_id", sa.String(200), str_empty),
        ("deploy_provider", sa.String(40), str_empty),
        ("deploy_message", sa.Text(), str_empty),
        ("simulated", sa.Boolean(), bool_false),
    ):
        _col("generated_projects", name, type_, server_default=default)
    op.add_column(
        "generated_projects",
        sa.Column("deploy_confirmed_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "user_preferences",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("user_id", sa.String(32), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True, index=True),
        sa.Column("settings", sa.Text(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "memory_items",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("user_id", sa.String(32), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("category", sa.String(40), nullable=False, server_default=sa.text("'explicit_instruction'")),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source", sa.String(24), nullable=False, server_default=sa.text("'explicit'")),
        sa.Column("source_conversation_id", sa.String(32), nullable=True),
        sa.Column("importance", sa.Integer(), nullable=False, server_default=sa.text("3")),
        sa.Column("keywords", sa.Text(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("use_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("pinned", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "content_hash", name="uq_memory_user_hash"),
    )
    op.create_table(
        "message_feedback",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("user_id", sa.String(32), nullable=False, index=True),
        sa.Column("message_id", sa.String(32), nullable=False, index=True),
        sa.Column("rating", sa.String(16), nullable=False),
        sa.Column("comment", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "message_id", name="uq_feedback_user_message"),
    )
    op.create_table(
        "llm_request_logs",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("user_id", sa.String(32), nullable=False, index=True, server_default=sa.text("''")),
        sa.Column("conversation_id", sa.String(32), nullable=False, index=True, server_default=sa.text("''")),
        sa.Column("request_id", sa.String(32), nullable=False, index=True, server_default=sa.text("''")),
        sa.Column("provider", sa.String(64), nullable=False, server_default=sa.text("''")),
        sa.Column("model", sa.String(160), nullable=False, server_default=sa.text("''")),
        sa.Column("status", sa.String(24), nullable=False, server_default=sa.text("'ok'")),
        sa.Column("error_code", sa.String(48), nullable=False, server_default=sa.text("''")),
        sa.Column("error", sa.String(500), nullable=False, server_default=sa.text("''")),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("streamed", sa.Boolean(), nullable=False, server_default=sa.text("'0'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "project_versions",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("project_id", sa.String(32), nullable=False, index=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("files_json", sa.Text(), nullable=False),
        sa.Column("note", sa.String(300), nullable=False, server_default=sa.text("''")),
        sa.Column("created_by", sa.String(32), nullable=False, server_default=sa.text("''")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("project_id", "version", name="uq_project_version"),
    )


def downgrade() -> None:
    for table in ("project_versions", "llm_request_logs", "message_feedback", "memory_items", "user_preferences"):
        op.drop_table(table)
    for name in ("deploy_confirmed_at", "simulated", "deploy_message", "deploy_provider", "deployment_id"):
        op.drop_column("generated_projects", name)
    for name in ("stopped", "model", "provider", "request_id"):
        op.drop_column("chat_runs", name)
    for name in ("edited_at", "error", "status", "output_tokens", "input_tokens", "provider", "model"):
        op.drop_column("messages", name)
    for name in ("project_id", "message_count", "summary", "token_usage", "model", "pinned", "archived"):
        op.drop_column("conversations", name)
