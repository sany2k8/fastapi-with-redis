"""STRINGS — session tokens and view counters.

WHAT IT IS
    The simplest Redis type: one key, one binary-safe value (up to 512 MB). A "string" that
    happens to look like an integer gets integer operations for free.

THE PROBLEM IT SOLVES HERE
    Two things that need no structure at all: a login session that must expire on its own,
    and a per-post view counter incremented by many concurrent requests.

HOW REDIS STORES IT
    int encoding for numeric values, embstr for short strings, raw above 44 bytes.
    INCR/DECR are single-threaded and therefore atomic — no read-modify-write race, ever.
    TTL is a property of the *key*, so expiry is free and needs no cleanup job.

WHY NOT ANOTHER TYPE
    A Hash for a session would let you group fields, but you cannot expire a single hash
    *field* (before Redis 7.4's HEXPIRE, and even then it is extra machinery). A session that
    dies on its own is exactly one key with one TTL.
    For the counter: a Sorted Set would give you ranking you did not ask for, at more memory
    and more complexity. If you only ever need "the number for this key", use a String.

LIMITATIONS
    No partial updates — changing one attribute means rewriting the whole value. Once you find
    yourself packing "name|email|age" into one string, you wanted a Hash.
"""

import secrets
from datetime import UTC, datetime
from typing import Any, cast

import redis.asyncio as aioredis

from app.core import keys


async def create_session(client: aioredis.Redis, user_id: str, ttl_seconds: int) -> dict[str, Any]:
    """SET with EX — the token evicts itself when the session lapses."""
    token = secrets.token_urlsafe(16)
    now = datetime.now(UTC).isoformat()

    # MSET cannot carry a TTL, so two SETs in a pipeline: one round trip, both expiring together.
    async with client.pipeline(transaction=True) as pipe:
        pipe.set(keys.session(user_id), token, ex=ttl_seconds)
        pipe.set(keys.session_last_seen(user_id), now, ex=ttl_seconds)
        await pipe.execute()

    return {"user_id": user_id, "token": token, "last_seen": now, "ttl_seconds": ttl_seconds}


async def get_session(client: aioredis.Redis, user_id: str) -> dict[str, Any] | None:
    """MGET fetches both keys in one round trip; TTL reports the remaining life."""
    token, last_seen = cast(
        list[str | None],
        await client.mget([keys.session(user_id), keys.session_last_seen(user_id)]),
    )
    if token is None:
        return None  # expired or never existed — indistinguishable, and that is fine

    ttl = await client.ttl(keys.session(user_id))
    return {"user_id": user_id, "token": token, "last_seen": last_seen, "ttl_seconds": ttl}


async def clear_session(client: aioredis.Redis, user_id: str) -> int:
    return await client.delete(keys.session(user_id), keys.session_last_seen(user_id))


async def increment_views(client: aioredis.Redis, post_id: str, by: int = 1) -> int:
    """INCRBY is atomic: a thousand concurrent viewers cannot lose a count between them."""
    return await client.incrby(keys.post_views(post_id), by)


async def get_views(client: aioredis.Redis, post_id: str) -> int:
    """A missing counter reads as 0 rather than an error — GET returns None, we normalise."""
    raw = cast(str | None, await client.get(keys.post_views(post_id)))
    return int(raw) if raw is not None else 0
