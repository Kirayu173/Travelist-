"""Stage 8 ai_tasks table for deep planning async execution.

Notes:
- Some environments already have an `ai_tasks` table (legacy schema).
- This migration is defensive: if `ai_tasks` already exists, it won't recreate it.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "20251214_03"
down_revision = "20251121_02"
branch_labels = None
depends_on = None

BIGINT = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("ai_tasks"):
        return

    is_postgres = bind.dialect.name == "postgresql"
    json_type = sa.JSON().with_variant(
        postgresql.JSONB(astext_type=sa.Text()),
        "postgresql",
    )
    json_default_obj = sa.text("'{}'::jsonb") if is_postgres else sa.text("'{}'")

    op.create_table(
        "ai_tasks",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("user_id", BIGINT, nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'queued'"),
        ),
        sa.Column(
            "request_json",
            json_type,
            nullable=False,
            server_default=json_default_obj,
        ),
        sa.Column("result_json", json_type, nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_ai_tasks_user_id", "ai_tasks", ["user_id"])
    op.create_index("ix_ai_tasks_status", "ai_tasks", ["status"])
    op.create_index("ix_ai_tasks_created_at", "ai_tasks", ["created_at"])
    op.create_index("ix_ai_tasks_finished_at", "ai_tasks", ["finished_at"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("ai_tasks"):
        return

    existing_indexes = {
        idx.get("name") for idx in inspector.get_indexes("ai_tasks") if idx.get("name")
    }
    for index_name in (
        "ix_ai_tasks_finished_at",
        "ix_ai_tasks_created_at",
        "ix_ai_tasks_status",
        "ix_ai_tasks_user_id",
    ):
        if index_name in existing_indexes:
            op.drop_index(index_name, table_name="ai_tasks")
