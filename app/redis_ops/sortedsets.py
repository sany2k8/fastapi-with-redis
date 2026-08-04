"""SORTED SETS — the leaderboard.

WHAT IT IS
    A Set where every member also carries a float score, and Redis keeps the members ordered
    by that score at all times.

THE PROBLEM IT SOLVES HERE
    A global points leaderboard: top 10, plus "what rank am I?" for an arbitrary user.

HOW REDIS STORES IT
    A skip list (ordered traversal) alongside a hash table (member -> score lookup). That
    pairing is why both "give me ranks 0-9" and "what is this member's score" are fast:
    ZADD/ZINCRBY are O(log N), ZRANGE is O(log N + M), ZSCORE is O(1).

THE KEY INSIGHT
    The ordering is maintained on *write*. There is no sort at read time, ever. A leaderboard
    over 10 million players answers "top 10" in microseconds.

WHY NOT ANOTHER TYPE
    vs SET: same uniqueness, but no score and no order. If you find yourself fetching a Set
      and sorting it in Python, you wanted a Sorted Set.
    vs HASH of user -> points: you can store the scores, but "top 10" means HGETALL plus a
      client-side sort of every player — O(N log N) in your app, and the whole table over the
      wire. "What rank is user X?" becomes unanswerable without the full scan.
    vs LIST: order would be insertion order, not score order; re-ranking would mean rebuilding.

LIMITATIONS
    Scores are IEEE-754 doubles — beyond 2^53 integers lose precision, so do not use raw
    nanosecond timestamps as scores. Ties break lexicographically by member, which is
    arbitrary but at least deterministic. Memory is roughly 2x a plain Set.
"""

from typing import Any, cast

import redis.asyncio as aioredis

from app.core import keys


async def add_points(client: aioredis.Redis, user_id: str, points: float) -> dict[str, Any]:
    """ZINCRBY — atomic read-modify-write of one member's score, and the ranking updates itself.

    ZADD would *set* the score (last writer wins, concurrent awards lost). For "award points"
    the increment is almost always what you want.
    """
    score = cast(float, await client.zincrby(keys.leaderboard(), points, user_id))
    rank = cast(int | None, await client.zrevrank(keys.leaderboard(), user_id))
    return {"user_id": user_id, "score": score, "rank": (rank + 1) if rank is not None else None}


async def set_score(client: aioredis.Redis, user_id: str, score: float) -> float:
    """ZADD — absolute set, for imports or corrections."""
    await client.zadd(keys.leaderboard(), {user_id: score})
    return score


async def top(client: aioredis.Redis, limit: int = 10) -> list[dict[str, Any]]:
    """ZREVRANGE WITHSCORES — highest first. No sorting happens at read time."""
    rows = cast(
        list[tuple[str, float]],
        await client.zrange(keys.leaderboard(), 0, limit - 1, desc=True, withscores=True),
    )
    return [
        {"rank": i + 1, "user_id": member, "score": score} for i, (member, score) in enumerate(rows)
    ]


async def rank_of(client: aioredis.Redis, user_id: str) -> dict[str, Any] | None:
    """ZREVRANK is 0-based; humans count from 1. ZCARD gives the "out of N" denominator."""
    async with client.pipeline(transaction=False) as pipe:
        pipe.zrevrank(keys.leaderboard(), user_id)
        pipe.zscore(keys.leaderboard(), user_id)
        pipe.zcard(keys.leaderboard())
        rank, score, total = await pipe.execute()

    if rank is None:
        return None
    return {
        "user_id": user_id,
        "rank": cast(int, rank) + 1,
        "score": cast(float, score),
        "out_of": cast(int, total),
    }
