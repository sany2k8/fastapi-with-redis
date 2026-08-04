"""HTTP layer for Geospatial indexes — nearby users."""

from typing import Annotated, Any

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, status

from app.core.client import get_redis
from app.models.analytics import LocationIn
from app.redis_ops import geo

router = APIRouter(prefix="/geo", tags=["9 · Geospatial"])

Redis = Annotated[aioredis.Redis, Depends(get_redis)]


@router.put("/locations/{user_id}", summary="Store a location (GEOADD)")
async def set_location(user_id: str, body: LocationIn, redis: Redis) -> dict[str, Any]:
    return await geo.set_location(redis, user_id, body.longitude, body.latitude)


@router.get("/locations/{user_id}", summary="Read it back (GEOPOS)")
async def get_location(user_id: str, redis: Redis) -> dict[str, Any]:
    location = await geo.get_location(redis, user_id)
    if location is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no location for {user_id!r}")
    return location


@router.get("/nearby", summary="Radius search, nearest first (GEOSEARCH)")
async def nearby(
    longitude: float, latitude: float, redis: Redis, km: float = 5.0, count: int = 10
) -> dict[str, Any]:
    results = await geo.nearby(redis, longitude, latitude, km, count)
    return {
        "centre": {"longitude": longitude, "latitude": latitude},
        "radius_km": km,
        "found": len(results),
        "users": results,
    }


@router.get("/distance", summary="Distance between two users (GEODIST)")
async def distance(a: str, b: str, redis: Redis, unit: str = "km") -> dict[str, Any]:
    value = await geo.distance_between(redis, a, b, unit)
    if value is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "one or both users have no location")
    return {"a": a, "b": b, "distance": value, "unit": unit}
