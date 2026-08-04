"""LISTS — the notification inbox.

WHAT IT IS
    A doubly-linked sequence of strings. Push and pop at either end in O(1); indexing into
    the middle is O(N).

THE PROBLEM IT SOLVES HERE
    A per-user notification inbox: newest first, capped at 100, consumable oldest-first.

HOW REDIS STORES IT
    A quicklist — a linked list of listpack nodes. Ends are cheap, the middle is not.
    Two idioms cover most real uses, and this module shows both:
      LPUSH + LTRIM  -> a capped "recent items" feed that can never grow without bound
      LPUSH + RPOP   -> a FIFO queue (push one end, consume the other)

WHY NOT ANOTHER TYPE
    vs SET: a Set has no order and rejects duplicates. Two identical "you have a new
      follower" notifications are two events, and order is the entire point of an inbox.
    vs SORTED SET: you would have to invent a score (a timestamp) to recover the ordering a
      List gives you for free, and pay O(log N) writes for it. Worth it only if you need to
      query *by* that score.
    vs STREAM: this is the important one. Popping from a List is destructive — the item is
      gone, one consumer wins, there is no history and no replay. That is right for an inbox.
      When you need many independent readers, acknowledgements, and a retained log, you want
      a Stream (see streams.py).

LIMITATIONS
    No random access by id, no per-item TTL, LRANGE over a long list is O(N). Redis Lists are
    a decent job queue for simple cases, but they have no retries or dead-lettering — that is
    a Stream consumer group's job.
"""

import json
from datetime import UTC, datetime
from typing import Any, cast

import redis.asyncio as aioredis

from app.core import keys

MAX_NOTIFICATIONS = 100


async def push_notification(
    client: aioredis.Redis, user_id: str, kind: str, message: str
) -> dict[str, Any]:
    """LPUSH then LTRIM: the capped-feed idiom.

    Without the LTRIM this key grows forever. Doing both in one transaction means a reader
    can never observe the list at 101 entries.
    """
    item = {"kind": kind, "message": message, "at": datetime.now(UTC).isoformat()}
    key = keys.notifications(user_id)

    async with client.pipeline(transaction=True) as pipe:
        pipe.lpush(key, json.dumps(item))
        pipe.ltrim(key, 0, MAX_NOTIFICATIONS - 1)
        pipe.llen(key)
        results = await pipe.execute()

    return {"item": item, "length": cast(int, results[2])}


async def list_notifications(
    client: aioredis.Redis, user_id: str, limit: int = 20
) -> dict[str, Any]:
    """LRANGE 0..limit-1 — index 0 is the newest, because we LPUSH."""
    key = keys.notifications(user_id)
    async with client.pipeline(transaction=False) as pipe:
        pipe.lrange(key, 0, limit - 1)
        pipe.llen(key)
        raw, total = await pipe.execute()

    return {
        "items": [json.loads(entry) for entry in cast(list[str], raw)],
        "total": cast(int, total),
    }


async def pop_oldest(client: aioredis.Redis, user_id: str) -> dict[str, Any] | None:
    """RPOP against LPUSH == FIFO. (RPOP against RPUSH would be LIFO — a stack.)

    This is destructive: the notification is gone from Redis once returned. If the caller
    crashes before handling it, it is lost. That trade-off is why job queues that must not
    lose work use Streams with XACK instead.
    """
    raw = cast(str | None, await client.rpop(keys.notifications(user_id)))
    if raw is None:
        return None
    return cast(dict[str, Any], json.loads(raw))


async def clear(client: aioredis.Redis, user_id: str) -> int:
    return await client.delete(keys.notifications(user_id))
