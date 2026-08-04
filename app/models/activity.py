"""Request models for the Bitmap / Bitfield / Stream endpoints."""

from typing import Any

from pydantic import BaseModel, Field


class ActivityMark(BaseModel):
    user_id: str = Field(min_length=1, examples=["alice"])
    day: str | None = Field(default=None, description="ISO date; defaults to today (UTC)")


class StateSet(BaseModel):
    """Bounds mirror the bitfield widths in redis_ops/bitfields.LAYOUT."""

    level: int | None = Field(default=None, ge=0, le=255)
    streak: int | None = Field(default=None, ge=0, le=255)
    xp: int | None = Field(default=None, ge=0, le=65_535)


class XpAdd(BaseModel):
    amount: int = Field(default=100, ge=-65_535, le=65_535)


class EventCreate(BaseModel):
    type: str = Field(min_length=1, examples=["post_created"])
    payload: dict[str, Any] = Field(default_factory=dict, examples=[{"user_id": "alice"}])
