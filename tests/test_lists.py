"""Lists: FIFO consumption and the capped-feed idiom."""

from app.redis_ops import lists


async def test_newest_first(redis_client):
    await lists.push_notification(redis_client, "alice", "system", "first")
    await lists.push_notification(redis_client, "alice", "system", "second")

    inbox = await lists.list_notifications(redis_client, "alice")
    assert [item["message"] for item in inbox["items"]] == ["second", "first"]


async def test_rpop_is_fifo(redis_client):
    """LPUSH + RPOP == FIFO: the oldest notification comes out first."""
    await lists.push_notification(redis_client, "alice", "system", "first")
    await lists.push_notification(redis_client, "alice", "system", "second")

    popped = await lists.pop_oldest(redis_client, "alice")
    assert popped is not None
    assert popped["message"] == "first"


async def test_pop_is_destructive(redis_client):
    """Contrast with Streams: once popped, the item is gone from Redis entirely."""
    await lists.push_notification(redis_client, "alice", "system", "only")
    await lists.pop_oldest(redis_client, "alice")

    assert await lists.list_notifications(redis_client, "alice") == {"items": [], "total": 0}
    assert await lists.pop_oldest(redis_client, "alice") is None


async def test_ltrim_caps_the_inbox(redis_client):
    """Without the LTRIM this key would grow without bound."""
    for i in range(lists.MAX_NOTIFICATIONS + 20):
        result = await lists.push_notification(redis_client, "alice", "system", f"n{i}")

    assert result["length"] == lists.MAX_NOTIFICATIONS
