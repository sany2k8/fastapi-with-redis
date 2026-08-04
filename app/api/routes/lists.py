"""HTTP layer for Redis Lists — the notification inbox."""

from typing import Annotated, Any

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, status

from app.core.client import get_redis
from app.models.social import NotificationCreate
from app.redis_ops import lists

router = APIRouter(prefix="/lists", tags=["4 · Lists"])

Redis = Annotated[aioredis.Redis, Depends(get_redis)]


@router.post("/{user_id}/notifications", summary="Push (LPUSH + LTRIM = capped feed)")
async def push(user_id: str, body: NotificationCreate, redis: Redis) -> dict[str, Any]:
    return await lists.push_notification(redis, user_id, body.kind, body.message)


@router.get("/{user_id}/notifications", summary="Newest first (LRANGE + LLEN)")
async def read(user_id: str, redis: Redis, limit: int = 20) -> dict[str, Any]:
    return await lists.list_notifications(redis, user_id, limit)


@router.post("/{user_id}/notifications/pop", summary="Consume oldest (RPOP = FIFO)")
async def pop(user_id: str, redis: Redis) -> dict[str, Any]:
    item = await lists.pop_oldest(redis, user_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "inbox is empty")
    return item


@router.delete("/{user_id}/notifications", summary="Clear the inbox (DEL)")
async def clear(user_id: str, redis: Redis) -> dict[str, Any]:
    return {"deleted": await lists.clear(redis, user_id)}
