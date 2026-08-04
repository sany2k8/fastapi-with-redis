"""Request models for the List / Set / Sorted Set endpoints (the "social" domain)."""

from pydantic import BaseModel, Field


class NotificationCreate(BaseModel):
    kind: str = Field(default="system", examples=["new_follower"])
    message: str = Field(min_length=1, max_length=500)


class FollowRequest(BaseModel):
    follower_id: str = Field(min_length=1, examples=["alice"])
    followee_id: str = Field(min_length=1, examples=["bob"])


class PointsAward(BaseModel):
    points: float = Field(default=10, examples=[10])
