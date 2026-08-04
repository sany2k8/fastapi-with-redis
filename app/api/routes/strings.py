"""HTTP layer for Redis Strings. No Redis commands here — see app/redis_ops/strings.py."""

from typing import Annotated, Any

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, status

from app.core.client import get_redis
from app.models.users import SessionCreate
from app.redis_ops import strings

router = APIRouter(prefix="/strings", tags=["1 · Strings"])

Redis = Annotated[aioredis.Redis, Depends(get_redis)]


@router.post("/sessions", summary="Create a session (SET … EX)")
async def create_session(body: SessionCreate, redis: Redis) -> dict[str, Any]:
    return await strings.create_session(redis, body.user_id, body.ttl_seconds)


@router.get("/sessions/{user_id}", summary="Read a session (MGET + TTL)")
async def get_session(user_id: str, redis: Redis) -> dict[str, Any]:
    session = await strings.get_session(redis, user_id)
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no active session (expired or never set)")
    return session


@router.delete("/sessions/{user_id}", summary="Log out (DEL)")
async def clear_session(user_id: str, redis: Redis) -> dict[str, Any]:
    return {"deleted_keys": await strings.clear_session(redis, user_id)}


@router.post("/views/{post_id}", summary="Count a view (INCR)")
async def increment_views(post_id: str, redis: Redis, by: int = 1) -> dict[str, Any]:
    return {"post_id": post_id, "views": await strings.increment_views(redis, post_id, by)}


@router.get("/views/{post_id}", summary="Read the counter (GET)")
async def get_views(post_id: str, redis: Redis) -> dict[str, Any]:
    return {"post_id": post_id, "views": await strings.get_views(redis, post_id)}
