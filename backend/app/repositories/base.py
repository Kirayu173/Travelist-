from __future__ import annotations

from sqlalchemy.orm import Session


class BaseRepository:
    """Lightweight repository wrapper used by domain services."""

    def __init__(self, session: Session) -> None:
        self.session = session
