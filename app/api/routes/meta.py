"""Health, the end-to-end demo, keyspace inspection, and the decision matrix."""

from typing import Annotated, Any

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, Query

from app import demo, reference
from app.core import keys
from app.core.client import REQUIRED_MODULES, get_redis, module_names
from app.core.config import get_settings

router = APIRouter(tags=["0 · Meta"])

Redis = Annotated[aioredis.Redis, Depends(get_redis)]

DATA_TYPES = [
    "strings",
    "hashes",
    "json",
    "lists",
    "sets",
    "sortedsets",
    "bitmaps",
    "bitfields",
    "geo",
    "streams",
    "probabilistic",
    "timeseries",
    "vectors",
]


@router.get("/health", summary="Redis reachability + which modules are loaded")
async def health(redis: Redis) -> dict[str, Any]:
    await redis.ping()
    modules = await module_names(redis)
    return {
        "status": "ok",
        "version": get_settings().app_version,
        "redis": "up",
        "modules": sorted(modules),
        "all_types_available": set(REQUIRED_MODULES).issubset(modules),
    }


@router.get("/demo/scenario", summary="Run all 13 types end to end")
async def scenario(
    redis: Redis,
    reset: Annotated[bool, Query(description="Clear the demo keyspace first")] = True,
    only: Annotated[str | None, Query(description=f"One of: {', '.join(DATA_TYPES)}")] = None,
) -> dict[str, Any]:
    """Resetting first makes the output deterministic — counts and ranks are reproducible."""
    if reset:
        await demo.reset(redis)
    return await demo.run(redis, only=only)


@router.post("/demo/reset", summary="Delete every key this app owns (SCAN by prefix)")
async def reset_keyspace(redis: Redis) -> dict[str, Any]:
    """SCAN, never KEYS: KEYS blocks the whole server while it walks the keyspace."""
    return {"deleted_keys": await demo.reset(redis)}


@router.get("/demo/keys", summary="Inspect the keyspace this app built")
async def inspect_keys(redis: Redis, limit: int = 200) -> dict[str, Any]:
    """Seeing the keys and their TYPE is half the lesson — the naming convention made real."""
    found: list[dict[str, Any]] = []
    cursor = 0
    while len(found) < limit:
        cursor, batch = await redis.scan(cursor=cursor, match=keys.scan_pattern(), count=200)
        for key in batch:
            key_type = await redis.type(key)
            memory = await redis.execute_command("MEMORY", "USAGE", key)
            found.append({"key": key, "type": key_type, "bytes": int(memory) if memory else 0})
        if cursor == 0:
            break

    by_type: dict[str, int] = {}
    for entry in found:
        by_type[entry["type"]] = by_type.get(entry["type"], 0) + 1

    return {
        "total": len(found),
        "by_type": dict(sorted(by_type.items())),
        "total_bytes": sum(e["bytes"] for e in found),
        "keys": sorted(found, key=lambda e: e["key"])[:limit],
    }


@router.get("/demo/types", summary="Which Redis type for which problem, and the common mistake")
async def decision_matrix() -> dict[str, Any]:
    return reference.matrix()
