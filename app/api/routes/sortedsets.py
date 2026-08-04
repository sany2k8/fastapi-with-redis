"""HTTP layer for Redis Sorted Sets — the leaderboard."""

from typing import Annotated, Any

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, status

from app.core.client import get_redis
from app.models.social import PointsAward
from app.redis_ops import sortedsets

router = APIRouter(prefix="/zsets", tags=["6 · Sorted Sets"])

Redis = Annotated[aioredis.Redis, Depends(get_redis)]


@router.post("/leaderboard/{user_id}/score", summary="Award points (ZINCRBY)")
async def award(user_id: str, body: PointsAward, redis: Redis) -> dict[str, Any]:
    return await sortedsets.add_points(redis, user_id, body.points)


@router.get("/leaderboard", summary="Top N (ZREVRANGE WITHSCORES)")
async def leaderboard(redis: Redis, top: int = 10) -> dict[str, Any]:
    return {"top": await sortedsets.top(redis, top)}


@router.get("/leaderboard/{user_id}/rank", summary="One user's rank (ZREVRANK + ZSCORE)")
async def rank(user_id: str, redis: Redis) -> dict[str, Any]:
    result = await sortedsets.rank_of(redis, user_id)
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{user_id!r} is not on the leaderboard")
    return result
