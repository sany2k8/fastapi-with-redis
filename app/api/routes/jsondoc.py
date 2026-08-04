"""HTTP layer for RedisJSON — and the answer to "where are arrays?"."""

from typing import Annotated, Any

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.client import get_redis
from app.models.users import InterestsAppend, ProfileCreate
from app.redis_ops import jsondoc

router = APIRouter(prefix="/json", tags=["3 · JSON (+ arrays)"])

Redis = Annotated[aioredis.Redis, Depends(get_redis)]


@router.put("/profiles/{user_id}", summary="Store a nested document (JSON.SET $)")
async def set_profile(user_id: str, body: ProfileCreate, redis: Redis) -> dict[str, Any]:
    await jsondoc.set_profile(redis, user_id, body.model_dump())
    return {"user_id": user_id, "profile": await jsondoc.get_profile(redis, user_id)}


@router.get("/profiles/{user_id}", summary="Read a document or one path (JSON.GET)")
async def get_profile(
    user_id: str,
    redis: Redis,
    path: Annotated[str, Query(description="JSONPath, e.g. $.prefs.theme or $.interests")] = "$",
) -> dict[str, Any]:
    value = await jsondoc.get_profile(redis, user_id, path)
    if value is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no profile {user_id!r} at path {path!r}")
    return {"user_id": user_id, "path": path, "value": value}


@router.post("/profiles/{user_id}/interests", summary="Append to an array (JSON.ARRAPPEND)")
async def append_interests(user_id: str, body: InterestsAppend, redis: Redis) -> dict[str, Any]:
    if await jsondoc.get_profile(redis, user_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no profile {user_id!r}")
    return await jsondoc.append_interests(redis, user_id, body.interests)


@router.post("/profiles/{user_id}/logins", summary="Increment a nested number (JSON.NUMINCRBY)")
async def increment_logins(user_id: str, redis: Redis, by: float = 1) -> dict[str, Any]:
    return {"stats.logins": await jsondoc.increment_path(redis, user_id, "$.stats.logins", by)}
