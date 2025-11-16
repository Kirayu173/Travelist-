from __future__ import annotations

from datetime import date, datetime, time
from enum import StrEnum
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from app.models import Base

JSONType = sa.JSON().with_variant(
    postgresql.JSONB(astext_type=sa.Text()),
    "postgresql",
)
BIGINT_TYPE = sa.BigInteger().with_variant(sa.Integer, "sqlite")


class PointGeography(TypeDecorator):
    """Portable geography column storing WGS84 coordinates when Postgres is available."""

    impl = sa.String(255)
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            from geoalchemy2 import Geography

            return dialect.type_descriptor(Geography(geometry_type="POINT", srid=4326))
        return dialect.type_descriptor(sa.String(255))


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )


class TransportMode(StrEnum):
    WALK = "walk"
    BIKE = "bike"
    DRIVE = "drive"
    TRANSIT = "transit"


TRANSPORT_ENUM = sa.Enum(
    TransportMode,
    name="transport",
    native_enum=False,
    validate_strings=True,
    values_callable=lambda enum_cls: [member.value for member in enum_cls],
)


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(
        BIGINT_TYPE,
        primary_key=True,
        autoincrement=True,
    )
    email: Mapped[str] = mapped_column(sa.String(255), unique=True, index=True)
    name: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    preferences: Mapped[dict[str, Any]] = mapped_column(
        JSONType,
        default=dict,
    )

    trips: Mapped[list["Trip"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    favorites: Mapped[list["Favorite"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )


class Trip(TimestampMixin, Base):
    __tablename__ = "trips"

    id: Mapped[int] = mapped_column(
        BIGINT_TYPE,
        primary_key=True,
        autoincrement=True,
    )
    user_id: Mapped[int] = mapped_column(
        BIGINT_TYPE,
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(sa.String(255))
    destination: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    start_date: Mapped[date | None] = mapped_column(sa.Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(sa.Date, nullable=True)
    status: Mapped[str] = mapped_column(
        sa.String(32),
        default="draft",
        server_default=sa.text("'draft'"),
    )
    meta: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)

    user: Mapped["User"] = relationship(back_populates="trips")
    day_cards: Mapped[list["DayCard"]] = relationship(
        back_populates="trip",
        cascade="all, delete-orphan",
        order_by="DayCard.day_index",
    )


class DayCard(TimestampMixin, Base):
    __tablename__ = "day_cards"
    __table_args__ = (
        sa.UniqueConstraint("trip_id", "day_index", name="uq_day_cards_trip_day"),
    )

    id: Mapped[int] = mapped_column(
        BIGINT_TYPE,
        primary_key=True,
        autoincrement=True,
    )
    trip_id: Mapped[int] = mapped_column(
        BIGINT_TYPE,
        sa.ForeignKey("trips.id", ondelete="CASCADE"),
        nullable=False,
    )
    day_index: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    date: Mapped[date | None] = mapped_column(sa.Date, nullable=True)
    note: Mapped[str | None] = mapped_column(sa.Text, nullable=True)

    trip: Mapped["Trip"] = relationship(back_populates="day_cards")
    sub_trips: Mapped[list["SubTrip"]] = relationship(
        back_populates="day_card",
        cascade="all, delete-orphan",
        order_by="SubTrip.order_index",
    )


class Poi(TimestampMixin, Base):
    __tablename__ = "pois"
    __table_args__ = (
        sa.UniqueConstraint(
            "provider",
            "provider_id",
            name="uq_pois_provider_identifier",
        ),
    )

    id: Mapped[int] = mapped_column(
        BIGINT_TYPE,
        primary_key=True,
        autoincrement=True,
    )
    provider: Mapped[str] = mapped_column(sa.String(32))
    provider_id: Mapped[str] = mapped_column(sa.String(64))
    name: Mapped[str] = mapped_column(sa.String(255))
    category: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)
    addr: Mapped[str | None] = mapped_column(sa.String(512), nullable=True)
    rating: Mapped[float | None] = mapped_column(sa.Numeric(3, 2), nullable=True)
    geom: Mapped[str | None] = mapped_column(PointGeography(), nullable=True)
    ext: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)

    sub_trips: Mapped[list["SubTrip"]] = relationship(back_populates="poi")
    favorites: Mapped[list["Favorite"]] = relationship(back_populates="poi")


class SubTrip(TimestampMixin, Base):
    __tablename__ = "sub_trips"
    __table_args__ = (
        sa.UniqueConstraint("day_card_id", "order_index", name="uq_sub_trips_day_order"),
    )

    id: Mapped[int] = mapped_column(
        BIGINT_TYPE,
        primary_key=True,
        autoincrement=True,
    )
    day_card_id: Mapped[int] = mapped_column(
        BIGINT_TYPE,
        sa.ForeignKey("day_cards.id", ondelete="CASCADE"),
        nullable=False,
    )
    order_index: Mapped[int] = mapped_column(
        sa.Integer,
        nullable=False,
        server_default=sa.text("0"),
    )
    activity: Mapped[str] = mapped_column(sa.String(255))
    poi_id: Mapped[int | None] = mapped_column(
        BIGINT_TYPE,
        sa.ForeignKey("pois.id", ondelete="SET NULL"),
        nullable=True,
    )
    loc_name: Mapped[str | None] = mapped_column(sa.String(255))
    transport: Mapped[TransportMode | None] = mapped_column(
        TRANSPORT_ENUM,
        nullable=True,
    )
    start_time: Mapped[time | None] = mapped_column(sa.Time, nullable=True)
    end_time: Mapped[time | None] = mapped_column(sa.Time, nullable=True)
    geom: Mapped[str | None] = mapped_column(PointGeography(), nullable=True)
    ext: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)

    day_card: Mapped["DayCard"] = relationship(back_populates="sub_trips")
    poi: Mapped["Poi"] = relationship(back_populates="sub_trips")


class Favorite(Base):
    __tablename__ = "favorites"
    __table_args__ = (
        sa.UniqueConstraint("user_id", "poi_id", name="uq_favorites_user_poi"),
    )

    id: Mapped[int] = mapped_column(
        BIGINT_TYPE,
        primary_key=True,
        autoincrement=True,
    )
    user_id: Mapped[int] = mapped_column(
        BIGINT_TYPE,
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    poi_id: Mapped[int] = mapped_column(
        BIGINT_TYPE,
        sa.ForeignKey("pois.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )

    user: Mapped["User"] = relationship(back_populates="favorites")
    poi: Mapped["Poi"] = relationship(back_populates="favorites")


__all__ = [
    "User",
    "Trip",
    "DayCard",
    "SubTrip",
    "Poi",
    "Favorite",
    "TransportMode",
]
