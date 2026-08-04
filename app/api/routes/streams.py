"""HTTP layer for Redis Streams — the event log and its consumer group."""

from typing import Annotated, Any

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends

from app.core.client import get_redis
from app.models.activity import EventCreate
from app.redis_ops import streams

router = APIRouter(prefix="/streams", tags=["10 · Streams"])

Redis = Annotated[aioredis.Redis, Depends(get_redis)]


@router.post("/events", summary="Append an event (XADD MAXLEN ~)")
async def add_event(body: EventCreate, redis: Redis) -> dict[str, Any]:
    return await streams.add_event(redis, body.type, body.payload)


@router.get("/events", summary="Read history, non-destructively (XREVRANGE)")
async def read_events(redis: Redis, count: int = 20) -> dict[str, Any]:
    return {
        "events": await streams.read_events(redis, count),
        "stream": await streams.info(redis),
    }


@router.post("/events/consume", summary="Consumer group cycle (XGROUP + XREADGROUP + XACK)")
async def consume(
    redis: Redis, consumer: str = "worker-1", count: int = 10, group: str = streams.CONSUMER_GROUP
) -> dict[str, Any]:
    """One request = one poll of the group. A real worker loops this with BLOCK; the events
    stay in the stream either way, which is the whole difference from a List."""
    return await streams.consume(redis, consumer=consumer, count=count, group=group)
