"""HASHES — the user record.

WHAT IT IS
    A map of field -> value stored under one key. Redis's answer to "an object".

THE PROBLEM IT SOLVES HERE
    A user row: id, name, email, country, role, karma. Fields are read and written
    independently — bumping karma must not require reading or rewriting the name.

HOW REDIS STORES IT
    Small hashes (few fields, short values) use a listpack: a compact, cache-friendly array
    scanned linearly. Past hash-max-listpack-entries/-value it converts to a real hash table.
    That is why a hash of 10 fields is dramatically cheaper than 10 separate String keys —
    one key's overhead instead of ten.

WHY NOT ANOTHER TYPE
    vs STRING holding JSON: updating one field means GET, parse, mutate, serialise, SET —
      a read-modify-write race between two concurrent writers. HSET touches one field, atomically.
    vs REDISJSON: this record is flat. JSON's path queries and nested arrays buy you nothing
      here and cost you a module dependency. Reach for JSON when the document nests (see
      redis_ops/jsondoc.py — same user, but with preferences, devices and arrays).

LIMITATIONS
    Values are flat strings — no nesting, no arrays, no types. HGETALL on a huge hash is O(N)
    and blocks the server for the duration; use HSCAN past a few thousand fields.
"""

from typing import Any, cast

import redis.asyncio as aioredis
from redis.typing import EncodableT, FieldT

from app.core import keys


async def upsert_user(client: aioredis.Redis, user_id: str, fields: dict[str, Any]) -> int:
    """HSET writes many fields in one command; it returns the count of *new* fields."""
    # Annotated with redis-py's own alias: Mapping keys are invariant, so a plain
    # dict[str, str] does not satisfy the parameter type however compatible it looks.
    payload: dict[FieldT, EncodableT] = {k: str(v) for k, v in fields.items() if v is not None}
    payload["id"] = user_id
    return await client.hset(keys.user(user_id), mapping=payload)


async def get_user(client: aioredis.Redis, user_id: str) -> dict[str, str] | None:
    """HGETALL returns {} for a missing key — Redis has no concept of a null hash."""
    data = cast(dict[str, str], await client.hgetall(keys.user(user_id)))
    return data or None


async def get_fields(client: aioredis.Redis, user_id: str, fields: list[str]) -> dict[str, Any]:
    """HMGET when you need three fields out of thirty — do not pay for HGETALL."""
    values = cast(list[str | None], await client.hmget(keys.user(user_id), fields))
    return dict(zip(fields, values, strict=True))


async def user_exists(client: aioredis.Redis, user_id: str) -> bool:
    """HEXISTS is O(1) and does not transfer the value — cheaper than HGET-and-check."""
    return bool(await client.hexists(keys.user(user_id), "id"))


async def increment_karma(client: aioredis.Redis, user_id: str, by: int) -> int:
    """HINCRBY: atomic counter *inside* the object. This is the whole argument for Hashes.

    With a JSON-in-a-String user record, two concurrent +1s can produce +1.
    """
    return await client.hincrby(keys.user(user_id), "karma", by)


async def delete_field(client: aioredis.Redis, user_id: str, field: str) -> int:
    return await client.hdel(keys.user(user_id), field)
