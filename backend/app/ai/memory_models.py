from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel


class MemoryLevel(StrEnum):
    user = "user"
    trip = "trip"
    session = "session"


class MemoryItem(BaseModel):
    id: str
    text: str
    score: float | None = None
    metadata: dict | None = None
