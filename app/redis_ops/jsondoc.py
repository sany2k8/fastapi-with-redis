"""REDISJSON — the nested profile, and where "arrays" live in Redis.

WHAT IT IS
    A native JSON document type (Redis 8 bundles it; it was the RedisJSON module before).
    Values are addressed by JSONPath, so you can read or write one leaf of a deep document
    without touching the rest.

THE PROBLEM IT SOLVES HERE
    The same user as redis_ops/hashes.py, but the *rich* version: nested preferences, a list
    of devices, an array of interests. Appending an interest must not rewrite the document.

HOW REDIS STORES IT
    A parsed binary tree, not text. That is why JSON.ARRAPPEND is O(1)-ish on the array
    instead of "parse 4 KB of text, append, re-serialise". Path expressions starting with `$`
    are JSONPath and always return an *array* of matches — even for a single hit.

ON ARRAYS (the PRD's §9.4)
    Redis has two array-shaped things and they are not competitors:
      - LIST      — a standalone ordered collection you push and pop. A queue. See lists.py.
      - JSON array — an array that is *part of a document*, addressed by path.
    "user.interests" belongs to the user document, so it is a JSON array. "the user's pending
    notifications" is a queue with its own lifecycle, so it is a List.

WHY NOT ANOTHER TYPE
    vs HASH: a Hash cannot nest. You would end up with "prefs.theme" as a literal field name,
      re-inventing paths by hand, and arrays would become "devices.0", "devices.1" with manual
      index bookkeeping. At that point you have written a worse JSON.
    vs STRING of serialised JSON: no partial reads, no partial writes, and every update is a
      read-modify-write race.

LIMITATIONS
    Bigger than a Hash for flat data, and JSONPath has real semantics you must learn
    (`$.a` returns `[value]`, not `value`). Deep documents are easy to abuse as a schema.
"""

import json
from typing import Any, cast

import redis.asyncio as aioredis

from app.core import keys

# NOTE ON STYLE: core types (string/hash/list/set/zset/geo/stream) use redis-py's typed
# methods. Module commands like JSON.* go through execute_command so the code you read maps
# 1:1 onto the Redis command you would type in redis-cli. That is the point of this repo.


async def set_profile(client: aioredis.Redis, user_id: str, document: dict[str, Any]) -> bool:
    """JSON.SET at the root path `$` replaces the whole document."""
    await client.execute_command("JSON.SET", keys.profile(user_id), "$", json.dumps(document))
    return True


async def get_profile(client: aioredis.Redis, user_id: str, path: str = "$") -> Any | None:
    """JSON.GET with a JSONPath.

    GOTCHA: with decode_responses=True the reply is a JSON *string*, so json.loads it.
    A `$`-rooted path always yields a list of matches; we unwrap single hits for sanity.
    """
    raw = cast(str | None, await client.execute_command("JSON.GET", keys.profile(user_id), path))
    if raw is None:
        return None
    parsed = json.loads(raw)
    if isinstance(parsed, list) and len(parsed) == 1:
        return parsed[0]
    return parsed


async def append_interests(
    client: aioredis.Redis, user_id: str, interests: list[str]
) -> dict[str, Any]:
    """JSON.ARRAPPEND — push onto an array *inside* the document, server-side.

    No fetch, no re-serialise, no lost update if two requests append at once.
    """
    lengths = cast(
        list[int | None],
        await client.execute_command(
            "JSON.ARRAPPEND",
            keys.profile(user_id),
            "$.interests",
            *[json.dumps(i) for i in interests],
        ),
    )
    current = cast(list[str], await get_profile(client, user_id, "$.interests") or [])
    return {"length": lengths[0] if lengths else 0, "interests": current}


async def increment_path(client: aioredis.Redis, user_id: str, path: str, by: float) -> Any:
    """JSON.NUMINCRBY — atomic arithmetic on a numeric leaf, e.g. `$.stats.logins`.

    GOTCHA: redis-py registers response callbacks for some module commands, so this comes back
    already parsed as a list of matches — unlike JSON.GET, which hands you a raw JSON string.
    Handle both rather than assuming, because the shape depends on the client version.
    """
    raw = await client.execute_command("JSON.NUMINCRBY", keys.profile(user_id), path, by)
    parsed = json.loads(raw) if isinstance(raw, str) else raw
    if isinstance(parsed, list) and len(parsed) == 1:
        return parsed[0]
    return parsed


async def delete_profile(client: aioredis.Redis, user_id: str) -> int:
    deleted = cast(int, await client.execute_command("JSON.DEL", keys.profile(user_id), "$"))
    return deleted
