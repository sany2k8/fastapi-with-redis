"""One shared async Redis client, plus the structures that must exist before first use.

`decode_responses=True` means every reply comes back as `str`, not `bytes`. That is convenient
almost everywhere, but note the consequences the ops modules deal with:
  - JSON.GET returns a JSON *string* you must json.loads
  - TS.RANGE returns values as strings you must float()
"""

from typing import Any, cast

import redis.asyncio as aioredis
from redis.exceptions import ResponseError

from app.core import keys
from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)

_client: aioredis.Redis | None = None

# The names MODULE LIST reports, lowercased, mapped to their human names. Note it is
# "rejson", not "json" — guessing here is how you get a startup check that checks nothing.
REQUIRED_MODULES = {
    "rejson": "RedisJSON",
    "bf": "RedisBloom (Bloom, CMS, Top-K)",
    "timeseries": "RedisTimeSeries",
    "vectorset": "Vector sets",
}


def get_redis() -> aioredis.Redis:
    """FastAPI dependency. The client is created once in the app lifespan."""
    if _client is None:
        raise RuntimeError("Redis client not initialised — app lifespan did not run")
    return _client


async def connect() -> aioredis.Redis:
    global _client
    settings = get_settings()
    _client = aioredis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=5,
        health_check_interval=30,
    )
    await _client.ping()
    log.info("redis.connected", host=settings.redis_host, port=settings.redis_port)
    return _client


async def disconnect() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
        log.info("redis.disconnected")


async def module_names(client: aioredis.Redis) -> set[str]:
    """Which Redis modules are loaded. Used to fail loudly and early, not cryptically."""
    raw = cast(list[dict[str, Any]], await client.execute_command("MODULE", "LIST"))
    names = {str(m.get("name", "")).lower() for m in raw}
    # Vector sets are BUILT IN to Redis 8 rather than a loadable .so, so they appear in
    # MODULE LIST with an empty path. Probing the command is the honest check.
    return names


async def bootstrap(client: aioredis.Redis) -> None:
    """Create the structures that do NOT auto-create on first write.

    This is the single most common Redis-modules trip-up:
      - BF.ADD  auto-creates a Bloom filter with default params.
      - CMS.INCRBY and TOPK.ADD do NOT — they error until the sketch is reserved.
      - TS.ADD auto-creates, but with no retention, no labels and no duplicate policy,
        so we create it explicitly to get all three.
    Every call below is idempotent: "already exists" is success, not an error.
    """
    await _ignore_exists(
        client.execute_command("CMS.INITBYPROB", keys.cms_searches(), "0.001", "0.01"),
        what="cms",
    )
    await _ignore_exists(
        client.execute_command("TOPK.RESERVE", keys.topk_searches(), 5, 200, 7, 0.925),
        what="topk",
    )
    await _ignore_exists(
        client.execute_command(
            "TS.CREATE",
            keys.metric(keys.HTTP_LATENCY_METRIC),
            "RETENTION",
            86_400_000,  # 24h in ms — old points are evicted for us
            "DUPLICATE_POLICY",
            "LAST",  # two requests can land on the same ms; without this, TS.ADD errors
            "LABELS",
            "kind",
            "http",
            "unit",
            "ms",
        ),
        what="timeseries",
    )
    log.info("redis.bootstrap.done")


async def _ignore_exists(coro: Any, *, what: str) -> None:
    try:
        await coro
    except ResponseError as exc:
        msg = str(exc).lower()
        if "exists" in msg:
            return  # idempotent: the structure is already there, which is what we wanted
        log.error("redis.bootstrap.failed", structure=what, error=str(exc))
        raise
