"""Hashes: independent field updates."""

import asyncio

from app.redis_ops import hashes


async def test_upsert_and_read(redis_client):
    await hashes.upsert_user(redis_client, "alice", {"name": "Alice", "country": "NL"})
    user = await hashes.get_user(redis_client, "alice")

    assert user == {"id": "alice", "name": "Alice", "country": "NL"}


async def test_missing_user_is_none(redis_client):
    """HGETALL returns {} for a missing key; we normalise that to None."""
    assert await hashes.get_user(redis_client, "ghost") is None


async def test_hincrby_does_not_disturb_other_fields(redis_client):
    await hashes.upsert_user(redis_client, "alice", {"name": "Alice", "karma": 0})
    await hashes.increment_karma(redis_client, "alice", 5)

    user = await hashes.get_user(redis_client, "alice")
    assert user is not None
    assert user["karma"] == "5"
    assert user["name"] == "Alice"  # untouched — this is why a Hash beats JSON-in-a-String


async def test_concurrent_karma_increments_do_not_lose_writes(redis_client):
    await hashes.upsert_user(redis_client, "alice", {"karma": 0})
    await asyncio.gather(*(hashes.increment_karma(redis_client, "alice", 1) for _ in range(50)))

    assert await hashes.increment_karma(redis_client, "alice", 0) == 50


async def test_hmget_and_hdel(redis_client):
    await hashes.upsert_user(redis_client, "alice", {"name": "Alice", "role": "admin"})

    assert await hashes.get_fields(redis_client, "alice", ["name", "missing"]) == {
        "name": "Alice",
        "missing": None,
    }
    assert await hashes.delete_field(redis_client, "alice", "role") == 1
    assert await hashes.user_exists(redis_client, "alice") is True
