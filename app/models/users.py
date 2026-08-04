"""Request models for the String / Hash / JSON endpoints (the "user" domain)."""

from typing import Any

from pydantic import BaseModel, Field


class SessionCreate(BaseModel):
    user_id: str = Field(min_length=1, max_length=64, examples=["alice"])
    ttl_seconds: int = Field(default=900, ge=1, le=86_400)


class UserCreate(BaseModel):
    """Flat by design — this is the Hash example."""

    id: str = Field(min_length=1, max_length=64, examples=["alice"])
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(examples=["alice@example.com"])
    country: str = Field(default="NL", max_length=2, min_length=2)
    role: str = Field(default="member")
    karma: int = 0


class KarmaUpdate(BaseModel):
    by: int = Field(default=1, ge=-1000, le=1000)


class ProfileCreate(BaseModel):
    """Nested by design — this is the JSON example. Note the arrays."""

    name: str
    email: str
    interests: list[str] = Field(default_factory=list, examples=[["redis", "python"]])
    devices: list[dict[str, Any]] = Field(
        default_factory=list, examples=[[{"type": "phone", "os": "ios"}]]
    )
    prefs: dict[str, Any] = Field(
        default_factory=dict, examples=[{"theme": "dark", "notifications": {"email": True}}]
    )
    stats: dict[str, Any] = Field(default_factory=lambda: {"logins": 0})


class InterestsAppend(BaseModel):
    interests: list[str] = Field(min_length=1, examples=[["kafka"]])


__all__ = [
    "InterestsAppend",
    "KarmaUpdate",
    "ProfileCreate",
    "SessionCreate",
    "UserCreate",
]
