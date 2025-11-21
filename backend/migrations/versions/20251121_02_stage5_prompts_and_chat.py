"""Stage 5 prompt registry and chat session tables."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "20251121_02"
down_revision = "20241114_01"
branch_labels = None
depends_on = None

BIGINT = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"
    json_type = sa.JSON().with_variant(
        postgresql.JSONB(astext_type=sa.Text()),
        "postgresql",
    )
    json_default_obj = sa.text("'{}'::jsonb") if is_postgres else sa.text("'{}'")
    json_default_array = sa.text("'[]'::jsonb") if is_postgres else sa.text("'[]'")

    op.create_table(
        "ai_prompts",
        sa.Column("id", BIGINT, primary_key=True, autoincrement=True),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column(
            "role", sa.String(length=32), nullable=False, server_default="system"
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column(
            "tags",
            json_type,
            nullable=False,
            server_default=json_default_array,
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("updated_by", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint("key", name="uq_ai_prompts_key"),
    )
    op.create_index("ix_ai_prompts_key", "ai_prompts", ["key"], unique=True)

    op.create_table(
        "chat_sessions",
        sa.Column("id", BIGINT, primary_key=True, autoincrement=True),
        sa.Column("user_id", BIGINT, nullable=False),
        sa.Column("trip_id", BIGINT, nullable=True),
        sa.Column(
            "opened_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "meta",
            json_type,
            nullable=False,
            server_default=json_default_obj,
        ),
    )
    op.create_index("ix_chat_sessions_user_id", "chat_sessions", ["user_id"])
    op.create_index("ix_chat_sessions_trip_id", "chat_sessions", ["trip_id"])

    op.create_table(
        "messages",
        sa.Column("id", BIGINT, primary_key=True, autoincrement=True),
        sa.Column("session_id", BIGINT, nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("intent", sa.String(length=64), nullable=True),
        sa.Column("tokens", sa.Integer(), nullable=True),
        sa.Column(
            "meta",
            json_type,
            nullable=False,
            server_default=json_default_obj,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["chat_sessions.id"],
            ondelete="CASCADE",
            name="fk_messages_session_id_chat_sessions",
        ),
    )
    op.create_index(
        "ix_messages_session_created",
        "messages",
        ["session_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_messages_session_created", table_name="messages")
    op.drop_table("messages")
    op.drop_index("ix_chat_sessions_trip_id", table_name="chat_sessions")
    op.drop_index("ix_chat_sessions_user_id", table_name="chat_sessions")
    op.drop_table("chat_sessions")
    op.drop_index("ix_ai_prompts_key", table_name="ai_prompts")
    op.drop_table("ai_prompts")
