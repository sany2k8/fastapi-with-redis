"""HTTP layer for Vector Sets — similarity search."""

from typing import Annotated, Any

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, Query

from app.core.client import get_redis
from app.models.analytics import VectorIn
from app.redis_ops import vectors

router = APIRouter(prefix="/vectors", tags=["13 · Vector Sets"])

Redis = Annotated[aioredis.Redis, Depends(get_redis)]


@router.put("/users/{user_id}", summary="Store an embedding (VADD)")
async def upsert(user_id: str, body: VectorIn, redis: Redis) -> dict[str, Any]:
    """The vector is derived deterministically from the tags — no ML model needed to learn
    the Redis side. Swap `embed()` for a real model and nothing else changes."""
    return await vectors.upsert(redis, user_id, body.tags)


@router.get("/users/{user_id}/similar", summary="Nearest neighbours (VSIM … ELE)")
async def similar(user_id: str, redis: Redis, k: int = 5) -> dict[str, Any]:
    return await vectors.similar(redis, user_id, k)


@router.get("/search", summary="Search by taste, not by user (VSIM … VALUES)")
async def search(
    redis: Redis,
    tag: Annotated[list[str], Query(description="Repeat for each tag")],
    k: int = 5,
) -> dict[str, Any]:
    return await vectors.search_by_tags(redis, tag, k)


@router.get("/info", summary="Index size (VCARD + VDIM)")
async def info(redis: Redis) -> dict[str, Any]:
    return await vectors.info(redis)
