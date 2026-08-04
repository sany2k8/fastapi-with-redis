"""SETS — the follow graph.

WHAT IT IS
    An unordered collection of unique strings. Membership tests are O(1).

THE PROBLEM IT SOLVES HERE
    Who follows whom. "Is A following B?" must be instant, following twice must be a no-op,
    and "who do A and B both follow?" should not require shipping two lists to the client.

HOW REDIS STORES IT
    intset (a sorted array) when every member is an integer and the set is small; otherwise a
    hash table. Uniqueness is structural — SADD of an existing member returns 0 and changes
    nothing, so "follow" is idempotent without any application logic.

WHY NOT ANOTHER TYPE
    vs LIST: LIST membership is O(N) and allows duplicates. Following someone twice would
      corrupt your follower count, and SISMEMBER-equivalent would be a linear scan.
    vs SORTED SET: only if you need an order or a score. "Followers ranked by when they
      followed" is a Sorted Set; "the set of followers" is a Set, at lower memory.

THE PAYOFF
    SINTER / SUNION / SDIFF run *inside* Redis. "Mutual follows" is one command against two
    keys, instead of two round trips plus a client-side intersection. For big sets that is
    the difference between a megabyte over the wire and a few hundred bytes.

LIMITATIONS
    No ordering at all — SMEMBERS order is an implementation detail you must not rely on.
    SMEMBERS on a huge set is O(N) and blocks; use SSCAN. SINTER over several large sets is
    expensive enough to be worth SINTERCARD if you only need the count.
"""

from typing import Any, cast

import redis.asyncio as aioredis

from app.core import keys


async def follow(client: aioredis.Redis, follower_id: str, followee_id: str) -> dict[str, Any]:
    """Both directions in one transaction — a half-written follow edge is a real bug.

    SADD is idempotent, so a double-submit cannot inflate anyone's counts.
    """
    async with client.pipeline(transaction=True) as pipe:
        pipe.sadd(keys.following(follower_id), followee_id)
        pipe.sadd(keys.followers(followee_id), follower_id)
        added = await pipe.execute()

    return {"created": bool(added[0]), "follower_id": follower_id, "followee_id": followee_id}


async def unfollow(client: aioredis.Redis, follower_id: str, followee_id: str) -> dict[str, Any]:
    async with client.pipeline(transaction=True) as pipe:
        pipe.srem(keys.following(follower_id), followee_id)
        pipe.srem(keys.followers(followee_id), follower_id)
        removed = await pipe.execute()

    return {"removed": bool(removed[0]), "follower_id": follower_id, "followee_id": followee_id}


async def is_following(client: aioredis.Redis, follower_id: str, followee_id: str) -> bool:
    """SISMEMBER — O(1) regardless of whether they follow 10 people or 10 million."""
    return bool(await client.sismember(keys.following(follower_id), followee_id))


async def list_following(client: aioredis.Redis, user_id: str) -> dict[str, Any]:
    """SCARD is O(1) — never len(SMEMBERS(...)) just to count."""
    async with client.pipeline(transaction=False) as pipe:
        pipe.smembers(keys.following(user_id))
        pipe.scard(keys.following(user_id))
        pipe.scard(keys.followers(user_id))
        members, following_count, followers_count = await pipe.execute()

    return {
        "following": sorted(cast(set[str], members)),
        "following_count": cast(int, following_count),
        "followers_count": cast(int, followers_count),
    }


async def mutual_following(client: aioredis.Redis, a: str, b: str) -> dict[str, Any]:
    """SINTER — "people you both follow", computed server-side in one round trip."""
    common = cast(set[str], await client.sinter([keys.following(a), keys.following(b)]))
    return {"a": a, "b": b, "mutual": sorted(common), "count": len(common)}


async def suggestions(client: aioredis.Redis, a: str, b: str) -> dict[str, Any]:
    """SDIFF — "followed by B but not by A": a one-command friend suggestion."""
    diff = cast(set[str], await client.sdiff([keys.following(b), keys.following(a)]))
    return {"for_user": a, "based_on": b, "suggestions": sorted(diff)}
