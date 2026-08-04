"""BITMAPS — daily active users.

WHAT IT IS
    Not a real type: bit-level operations on a String. Bit N of the value is user N's flag.

THE PROBLEM IT SOLVES HERE
    "Was this user active on 2026-08-04?", "how many were active that day?", and
    "how many were active on BOTH days?" — retention, in one command.

HOW REDIS STORES IT
    One key per day, one bit per user. 1,000,000 users = 1,000,000 bits = 125 KB per day.
    A whole year of daily activity for a million users is ~45 MB. The equivalent as a Set of
    user ids per day would be tens of gigabytes.

THE PAYOFF
    BITOP AND destination day_a day_b, then BITCOUNT destination. Day-over-day retention
    computed entirely inside Redis, over the compressed representation, with no user ids
    crossing the network. BITOP OR gives you "active in the last 7 days" over 7 keys.

WHY NOT ANOTHER TYPE
    vs SET of active user ids per day: correct, obvious, and ~50x the memory. Fine at 10k
      users; ruinous at 10M. The Set does let you *enumerate* who was active — the bitmap
      answers "how many" and "was this one", which is what dashboards actually ask.
    vs HYPERLOGLOG: an HLL would also count unique actives in 12 KB flat — but only
      approximately, and it can never answer "was user 42 active?". Bitmaps are exact and
      queryable per user. Pick by whether you need the per-member question.

THE CATCH — dense integer ids
    Bit offsets are positions, so ids must be small and dense. User id 9_000_000_000 alone
    allocates a 1 GB string. Real systems have a numeric primary key; this project has string
    ids, so it assigns dense offsets through a Redis hash (see _offset_for). That mapping is
    itself the lesson: bitmaps require you to own an integer id space.

LIMITATIONS
    Sparse ids waste enormous memory. You cannot list who is set without scanning every bit.
    Deleting a user leaves a hole you must never reuse carelessly.
"""

from datetime import UTC, date, datetime
from typing import Any, cast

import redis.asyncio as aioredis

from app.core import keys


def today() -> str:
    return datetime.now(UTC).date().isoformat()


async def _offset_for(client: aioredis.Redis, user_id: str) -> int:
    """Assign a stable, dense bit offset to a user id.

    HSETNX + INCR gives each new user the next free offset exactly once, even under
    concurrency: the INCR only happens for the writer that wins the HSETNX.
    """
    existing = cast(str | None, await client.hget(keys.bit_index(), user_id))
    if existing is not None:
        return int(existing)

    offset = await client.incr(keys.bit_index_seq()) - 1
    claimed = await client.hsetnx(keys.bit_index(), user_id, offset)
    if not claimed:
        # Someone else registered this user first; their offset is authoritative.
        return int(cast(str, await client.hget(keys.bit_index(), user_id)))
    return offset


async def mark_active(
    client: aioredis.Redis, user_id: str, day: str | None = None
) -> dict[str, Any]:
    """SETBIT — flip one bit. O(1), and the string grows automatically to fit the offset."""
    day = day or today()
    offset = await _offset_for(client, user_id)
    previous = await client.setbit(keys.activity(day), offset, 1)
    return {"user_id": user_id, "day": day, "bit_offset": offset, "already_active": bool(previous)}


async def day_stats(client: aioredis.Redis, day: str, user_id: str | None = None) -> dict[str, Any]:
    """BITCOUNT = daily active users. GETBIT = "was this specific user active?"."""
    active_count = await client.bitcount(keys.activity(day))
    size_bytes = await client.strlen(keys.activity(day))

    result: dict[str, Any] = {
        "day": day,
        "active_users": active_count,
        "bitmap_bytes": size_bytes,
    }
    if user_id is not None:
        offset = await _offset_for(client, user_id)
        result["user_id"] = user_id
        result["was_active"] = bool(await client.getbit(keys.activity(day), offset))
    return result


async def retention(client: aioredis.Redis, day_a: str, day_b: str) -> dict[str, Any]:
    """BITOP AND + BITCOUNT — the entire retention calculation, server-side.

    Nothing but two key names goes over the wire, and nothing but three integers comes back.
    """
    scratch = keys.activity_scratch(f"{day_a}_{day_b}")
    try:
        async with client.pipeline(transaction=True) as pipe:
            pipe.bitop("AND", scratch, keys.activity(day_a), keys.activity(day_b))
            pipe.bitcount(keys.activity(day_a))
            pipe.bitcount(keys.activity(day_b))
            _, count_a, count_b = await pipe.execute()
        both = await client.bitcount(scratch)
    finally:
        await client.delete(scratch)  # scratch keys must never outlive the query

    retained_pct = round(100 * both / count_a, 2) if count_a else 0.0
    return {
        "day_a": day_a,
        "day_b": day_b,
        "active_day_a": cast(int, count_a),
        "active_day_b": cast(int, count_b),
        "active_both_days": both,
        "retention_pct": retained_pct,
    }


async def seed_day(client: aioredis.Redis, day: str, user_ids: list[str]) -> int:
    """Convenience for the demo: mark several users active on a given day."""
    for user_id in user_ids:
        await mark_active(client, user_id, day)
    return len(user_ids)


def yesterday() -> str:
    d = datetime.now(UTC).date()
    return date.fromordinal(d.toordinal() - 1).isoformat()
