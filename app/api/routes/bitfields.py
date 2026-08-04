"""HTTP layer for Bitfields — a 4-byte user state record."""

from typing import Annotated, Any

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, status

from app.core.client import get_redis
from app.models.activity import StateSet, XpAdd
from app.redis_ops import bitfields

router = APIRouter(prefix="/bitfields", tags=["8 · Bitfields"])

Redis = Annotated[aioredis.Redis, Depends(get_redis)]


@router.put("/state/{user_id}", summary="Pack level/streak/xp (BITFIELD SET)")
async def set_state(user_id: str, body: StateSet, redis: Redis) -> dict[str, Any]:
    values = {k: v for k, v in body.model_dump().items() if v is not None}
    try:
        return await bitfields.set_state(redis, user_id, values)
    except ValueError as exc:
        # Domain error -> HTTP error at the edge; never swallowed.
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc


@router.get("/state/{user_id}", summary="Unpack it (BITFIELD GET x3)")
async def get_state(user_id: str, redis: Redis) -> dict[str, Any]:
    return await bitfields.get_state(redis, user_id)


@router.post("/state/{user_id}/xp", summary="Add xp (BITFIELD OVERFLOW SAT INCRBY)")
async def add_xp(user_id: str, body: XpAdd, redis: Redis) -> dict[str, Any]:
    """SAT clamps at 65535. The default WRAP would silently reset the player to near zero."""
    return await bitfields.add_xp(redis, user_id, body.amount)


@router.get("/layout", summary="The bit layout, since nothing else documents it")
async def layout() -> dict[str, Any]:
    return {
        "fields": [
            {"name": name, "type": spec, "bit_offset": offset}
            for name, spec, offset in bitfields.LAYOUT
        ],
        "total_bytes": 4,
        "warning": "Changing this layout silently invalidates every stored record.",
    }
