"""HTTP layer for Redis Time Series — application metrics."""

from typing import Annotated, Any

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends

from app.core import keys
from app.core.client import get_redis
from app.models.analytics import MetricIn
from app.redis_ops import timeseries

router = APIRouter(prefix="/timeseries", tags=["12 · Time Series"])

Redis = Annotated[aioredis.Redis, Depends(get_redis)]


@router.post("/metrics/{name}", summary="Record a sample (TS.CREATE once + TS.ADD)")
async def record(name: str, body: MetricIn, redis: Redis) -> dict[str, Any]:
    return await timeseries.record(redis, name, body.value, body.timestamp_ms, {"kind": "custom"})


@router.get("/metrics/{name}", summary="Range, optionally downsampled (TS.RANGE AGGREGATION)")
async def range_query(
    name: str,
    redis: Redis,
    from_ms: int | None = None,
    to_ms: int | None = None,
    bucket_ms: Annotated[int | None, "Bucket size; omit for raw samples"] = None,
    aggregation: str = "avg",
) -> dict[str, Any]:
    return await timeseries.range_query(redis, name, from_ms, to_ms, bucket_ms, aggregation)


@router.get("/http-latency", summary="Real request latency recorded by the middleware")
async def http_latency(redis: Redis, minutes: int = 5, bucket_ms: int = 10_000) -> dict[str, Any]:
    """Every request to this API writes a sample, so this returns real data immediately."""
    now = timeseries.now_ms()
    return await timeseries.range_query(
        redis,
        keys.HTTP_LATENCY_METRIC,
        from_ms=now - minutes * 60_000,
        to_ms=now,
        bucket_ms=bucket_ms,
        aggregation="avg",
    )


@router.get("/by-label", summary="Every series matching a label (TS.MRANGE)")
async def by_label(redis: Redis, label: str = "kind", value: str = "http") -> dict[str, Any]:
    return {"series": await timeseries.multi_range(redis, label, value)}
