"""HTTP layer for Redis Hashes. See app/redis_ops/hashes.py for the why."""

from typing import Annotated, Any

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.client import get_redis
from app.models.users import KarmaUpdate, UserCreate
from app.redis_ops import hashes

router = APIRouter(prefix="/hashes", tags=["2 · Hashes"])

Redis = Annotated[aioredis.Redis, Depends(get_redis)]


@router.post("/users", summary="Create/replace a user (HSET)")
async def upsert_user(body: UserCreate, redis: Redis) -> dict[str, Any]:
    fields = body.model_dump()
    user_id = str(fields.pop("id"))
    added = await hashes.upsert_user(redis, user_id, fields)
    return {"user_id": user_id, "new_fields": added, "user": await hashes.get_user(redis, user_id)}


@router.get("/users/{user_id}", summary="Read a user (HGETALL)")
async def get_user(user_id: str, redis: Redis) -> dict[str, Any]:
    user = await hashes.get_user(redis, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no user {user_id!r}")
    return user


@router.get("/users/{user_id}/fields", summary="Read selected fields (HMGET)")
async def get_fields(
    user_id: str,
    redis: Redis,
    field: Annotated[list[str], Query(description="Repeat for each field")],
) -> dict[str, Any]:
    if not await hashes.user_exists(redis, user_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no user {user_id!r}")
    return await hashes.get_fields(redis, user_id, field)


@router.patch("/users/{user_id}/karma", summary="Bump one field atomically (HINCRBY)")
async def increment_karma(user_id: str, body: KarmaUpdate, redis: Redis) -> dict[str, Any]:
    return {"user_id": user_id, "karma": await hashes.increment_karma(redis, user_id, body.by)}


@router.delete("/users/{user_id}/fields/{field}", summary="Drop one field (HDEL)")
async def delete_field(user_id: str, field: str, redis: Redis) -> dict[str, Any]:
    return {"removed": await hashes.delete_field(redis, user_id, field)}
