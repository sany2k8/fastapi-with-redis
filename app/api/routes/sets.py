"""HTTP layer for Redis Sets — the follow graph, and set algebra server-side."""

from typing import Annotated, Any

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends

from app.core.client import get_redis
from app.models.social import FollowRequest
from app.redis_ops import sets

router = APIRouter(prefix="/sets", tags=["5 · Sets"])

Redis = Annotated[aioredis.Redis, Depends(get_redis)]


@router.post("/follow", summary="Follow (SADD, idempotent)")
async def follow(body: FollowRequest, redis: Redis) -> dict[str, Any]:
    return await sets.follow(redis, body.follower_id, body.followee_id)


@router.delete("/follow", summary="Unfollow (SREM)")
async def unfollow(follower_id: str, followee_id: str, redis: Redis) -> dict[str, Any]:
    """Query params rather than a body: DELETE-with-body is legal but poorly supported."""
    return await sets.unfollow(redis, follower_id, followee_id)


@router.get("/{user_id}/following", summary="List + counts (SMEMBERS + SCARD)")
async def following(user_id: str, redis: Redis) -> dict[str, Any]:
    return await sets.list_following(redis, user_id)


@router.get("/is-following", summary="Membership test (SISMEMBER, O(1))")
async def is_following(follower_id: str, followee_id: str, redis: Redis) -> dict[str, Any]:
    return {
        "follower_id": follower_id,
        "followee_id": followee_id,
        "is_following": await sets.is_following(redis, follower_id, followee_id),
    }


@router.get("/mutual", summary="People you both follow (SINTER — the payoff)")
async def mutual(a: str, b: str, redis: Redis) -> dict[str, Any]:
    return await sets.mutual_following(redis, a, b)


@router.get("/suggestions", summary="Followed by B, not by A (SDIFF)")
async def suggestions(a: str, b: str, redis: Redis) -> dict[str, Any]:
    return await sets.suggestions(redis, a, b)
