"""HTTP layer for the four probabilistic structures."""

from typing import Annotated, Any

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, Query

from app.core.client import get_redis
from app.models.analytics import EmailIn, SearchIn
from app.redis_ops import probabilistic

router = APIRouter(prefix="/probabilistic", tags=["11 · Probabilistic"])

Redis = Annotated[aioredis.Redis, Depends(get_redis)]


@router.post("/emails", summary="Remember an email (BF.ADD)")
async def add_email(body: EmailIn, redis: Redis) -> dict[str, Any]:
    return await probabilistic.add_email(redis, body.email)


@router.get("/emails/{email}", summary="Seen before? (BF.EXISTS)")
async def check_email(email: str, redis: Redis) -> dict[str, Any]:
    """'definitely_new' is a guarantee; 'probably_seen' is not. That asymmetry is the point."""
    return await probabilistic.check_email(redis, email)


@router.post("/search", summary="One event → HyperLogLog + Count-Min Sketch + Top-K")
async def track_search(body: SearchIn, redis: Redis) -> dict[str, Any]:
    return await probabilistic.track_search(redis, body.user_id, body.term)


@router.get("/search/stats", summary="Three sketches, three answers, side by side")
async def search_stats(
    redis: Redis,
    term: Annotated[list[str] | None, Query(description="Terms to ask the CMS about")] = None,
    day: str | None = None,
) -> dict[str, Any]:
    stats = await probabilistic.search_stats(redis, term, day)
    stats["memory"] = await probabilistic.info(redis)
    return stats
