"""Strings: TTL behaviour and atomic counters."""

import asyncio

from app.redis_ops import strings


async def test_session_roundtrip(redis_client):
    created = await strings.create_session(redis_client, "alice", ttl_seconds=60)
    fetched = await strings.get_session(redis_client, "alice")

    assert fetched is not None
    assert fetched["token"] == created["token"]
    assert 0 < fetched["ttl_seconds"] <= 60  # TTL is counting down, not absent (-1) or gone (-2)


async def test_session_expires(redis_client):
    """The key evicts itself — no cleanup code anywhere in this project."""
    await strings.create_session(redis_client, "ephemeral", ttl_seconds=1)
    await asyncio.sleep(1.2)

    assert await strings.get_session(redis_client, "ephemeral") is None


async def test_missing_session_is_none_not_error(redis_client):
    assert await strings.get_session(redis_client, "nobody") is None


async def test_incr_is_atomic_under_concurrency(redis_client):
    """100 concurrent increments must total exactly 100 — the whole point of INCR."""
    await asyncio.gather(*(strings.increment_views(redis_client, "post-1") for _ in range(100)))

    assert await strings.get_views(redis_client, "post-1") == 100


async def test_unknown_counter_reads_as_zero(redis_client):
    assert await strings.get_views(redis_client, "never-viewed") == 0
