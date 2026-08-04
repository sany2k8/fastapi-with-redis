"""HTTP layer for Bitmaps — daily active users and retention."""

from typing import Annotated, Any

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, Query

from app.core.client import get_redis
from app.models.activity import ActivityMark
from app.redis_ops import bitmaps

router = APIRouter(prefix="/bitmaps", tags=["7 · Bitmaps"])

Redis = Annotated[aioredis.Redis, Depends(get_redis)]


@router.post("/activity", summary="Mark a user active today (SETBIT)")
async def mark_active(body: ActivityMark, redis: Redis) -> dict[str, Any]:
    return await bitmaps.mark_active(redis, body.user_id, body.day)


@router.get("/activity/{day}", summary="DAU + per-user check (BITCOUNT + GETBIT)")
async def day_stats(
    day: str,
    redis: Redis,
    user_id: Annotated[str | None, Query(description="Optional: was THIS user active?")] = None,
) -> dict[str, Any]:
    return await bitmaps.day_stats(redis, day, user_id)


@router.get("/retention", summary="Active on both days (BITOP AND + BITCOUNT)")
async def retention(day_a: str, day_b: str, redis: Redis) -> dict[str, Any]:
    """The whole calculation happens in Redis — no user ids cross the network."""
    return await bitmaps.retention(redis, day_a, day_b)
