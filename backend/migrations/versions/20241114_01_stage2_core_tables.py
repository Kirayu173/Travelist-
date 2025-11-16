"""Stage 2 core tables and PostGIS setup."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from geoalchemy2 import Geography
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "20241114_01"
down_revision = None
branch_labels = None
depends_on = None

TRANSPORT_VALUES = ("walk", "bike", "drive", "transit")
BIGINT = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def _is_postgres() -> bool:
    bind = op.get_bind()
    return bind.dialect.name == "postgresql"


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"
    json_type = sa.JSON().with_variant(
        postgresql.JSONB(astext_type=sa.Text()),
        "postgresql",
    )
    json_default = sa.text("'{}'::jsonb") if is_postgres else sa.text("'{}'")

    transport_type: sa.types.TypeEngine | sa.types.TypeDecorator = sa.String(length=16)
    geom_type: sa.types.TypeEngine = sa.String(length=255)

    if is_postgres:
        op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
        transport_enum = postgresql.ENUM(*TRANSPORT_VALUES, name="transport")
        transport_enum.create(bind, checkfirst=True)
        transport_type = postgresql.ENUM(
            *TRANSPORT_VALUES,
            name="transport",
            create_type=False,
        )
        geom_type = Geography(geometry_type="POINT", srid=4326)
    op.create_table(
        "users",
        sa.Column("id", BIGINT, primary_key=True, autoincrement=True),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("preferences", json_type, nullable=False, server_default=json_default),
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
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "trips",
        sa.Column("id", BIGINT, primary_key=True, autoincrement=True),
        sa.Column("user_id", BIGINT, nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("destination", sa.String(length=255), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'draft'"),
        ),
        sa.Column("meta", json_type, nullable=False, server_default=json_default),
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
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
            name="fk_trips_user_id_users",
        ),
    )
    op.create_index("ix_trips_user_id", "trips", ["user_id"])

    op.create_table(
        "day_cards",
        sa.Column("id", BIGINT, primary_key=True, autoincrement=True),
        sa.Column("trip_id", BIGINT, nullable=False),
        sa.Column("day_index", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["trip_id"],
            ["trips.id"],
            ondelete="CASCADE",
            name="fk_day_cards_trip_id_trips",
        ),
        sa.UniqueConstraint("trip_id", "day_index", name="uq_day_cards_trip_day"),
    )
    op.create_index("ix_day_cards_trip_id", "day_cards", ["trip_id"])

    op.create_table(
        "pois",
        sa.Column("id", BIGINT, primary_key=True, autoincrement=True),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("category", sa.String(length=128), nullable=True),
        sa.Column("addr", sa.String(length=512), nullable=True),
        sa.Column("rating", sa.Numeric(3, 2), nullable=True),
        sa.Column("geom", geom_type, nullable=True),
        sa.Column("ext", json_type, nullable=False, server_default=json_default),
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
        sa.UniqueConstraint(
            "provider",
            "provider_id",
            name="uq_pois_provider_identifier",
        ),
    )

    op.create_table(
        "sub_trips",
        sa.Column("id", BIGINT, primary_key=True, autoincrement=True),
        sa.Column("day_card_id", BIGINT, nullable=False),
        sa.Column(
            "order_index",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("activity", sa.String(length=255), nullable=False),
        sa.Column("poi_id", BIGINT, nullable=True),
        sa.Column("loc_name", sa.String(length=255), nullable=True),
        sa.Column("transport", transport_type, nullable=True),
        sa.Column("start_time", sa.Time(), nullable=True),
        sa.Column("end_time", sa.Time(), nullable=True),
        sa.Column("geom", geom_type, nullable=True),
        sa.Column("ext", json_type, nullable=False, server_default=json_default),
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
        sa.ForeignKeyConstraint(
            ["day_card_id"],
            ["day_cards.id"],
            ondelete="CASCADE",
            name="fk_sub_trips_day_card_id_day_cards",
        ),
        sa.ForeignKeyConstraint(
            ["poi_id"],
            ["pois.id"],
            ondelete="SET NULL",
            name="fk_sub_trips_poi_id_pois",
        ),
        sa.UniqueConstraint("day_card_id", "order_index", name="uq_sub_trips_day_order"),
    )

    op.create_table(
        "favorites",
        sa.Column("id", BIGINT, primary_key=True, autoincrement=True),
        sa.Column("user_id", BIGINT, nullable=False),
        sa.Column("poi_id", BIGINT, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
            name="fk_favorites_user_id_users",
        ),
        sa.ForeignKeyConstraint(
            ["poi_id"],
            ["pois.id"],
            ondelete="CASCADE",
            name="fk_favorites_poi_id_pois",
        ),
        sa.UniqueConstraint("user_id", "poi_id", name="uq_favorites_user_poi"),
    )

    op.create_index("ix_sub_trips_day_card_id", "sub_trips", ["day_card_id"])
    op.create_index("ix_sub_trips_poi_id", "sub_trips", ["poi_id"])
    op.create_index("ix_favorites_user_id", "favorites", ["user_id"])
    if is_postgres:
        op.create_index(
            "ix_sub_trips_geom",
            "sub_trips",
            ["geom"],
            unique=False,
            postgresql_using="gist",
        )
        op.create_index(
            "ix_pois_geom",
            "pois",
            ["geom"],
            unique=False,
            postgresql_using="gist",
        )


def downgrade() -> None:
    is_postgres = _is_postgres()

    if is_postgres:
        op.drop_index("ix_sub_trips_geom", table_name="sub_trips")
        op.drop_index("ix_pois_geom", table_name="pois")

    op.drop_index("ix_sub_trips_day_card_id", table_name="sub_trips")
    op.drop_index("ix_sub_trips_poi_id", table_name="sub_trips")
    op.drop_index("ix_favorites_user_id", table_name="favorites")
    op.drop_table("favorites")
    op.drop_table("sub_trips")
    op.drop_table("pois")
    op.drop_index("ix_day_cards_trip_id", table_name="day_cards")
    op.drop_table("day_cards")
    op.drop_index("ix_trips_user_id", table_name="trips")
    op.drop_table("trips")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")

    if is_postgres:
        transport_enum = postgresql.ENUM(*TRANSPORT_VALUES, name="transport")
        transport_enum.drop(op.get_bind(), checkfirst=True)
