"""Streams: append-only history and consumer-group delivery."""

from app.redis_ops import streams


async def test_events_persist_after_being_consumed(redis_client):
    """The defining difference from a List: consuming does not remove."""
    await streams.add_event(redis_client, "user_registered", {"user_id": "alice"})
    await streams.add_event(redis_client, "post_created", {"post_id": "p1"})

    consumed = await streams.consume(redis_client, consumer="w1")
    assert len(consumed["consumed"]) == 2
    assert (await streams.info(redis_client))["length"] == 2  # still there


async def test_xack_clears_the_pending_list(redis_client):
    await streams.add_event(redis_client, "post_created", {"post_id": "p1"})
    result = await streams.consume(redis_client, consumer="w1")

    assert result["pending"] == 0  # consume() acks what it processed


async def test_a_second_poll_sees_no_new_entries(redis_client):
    """`>` means 'never delivered to this group' — each entry goes to one consumer."""
    await streams.add_event(redis_client, "post_created", {"post_id": "p1"})
    await streams.consume(redis_client, consumer="w1")

    assert (await streams.consume(redis_client, consumer="w2"))["consumed"] == []


async def test_a_second_group_sees_the_full_history(redis_client):
    """Independent groups each get every event — that is why analytics and email can coexist."""
    await streams.add_event(redis_client, "post_created", {"post_id": "p1"})
    await streams.consume(redis_client, consumer="w1", group="analytics")

    other = await streams.consume(redis_client, consumer="mailer", group="emails")
    assert len(other["consumed"]) == 1


async def test_creating_an_existing_group_is_success(redis_client):
    """BUSYGROUP means 'already exists', which is the state we wanted."""
    assert await streams.ensure_group(redis_client, "analytics") is True
    assert await streams.ensure_group(redis_client, "analytics") is False


async def test_read_events_is_newest_first(redis_client):
    await streams.add_event(redis_client, "first", {})
    await streams.add_event(redis_client, "second", {})

    assert [e["type"] for e in await streams.read_events(redis_client)] == ["second", "first"]
