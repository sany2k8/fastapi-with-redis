"""Sets: uniqueness, membership and server-side set algebra."""

from app.redis_ops import sets


async def test_follow_is_idempotent(redis_client):
    first = await sets.follow(redis_client, "alice", "bob")
    second = await sets.follow(redis_client, "alice", "bob")

    assert first["created"] is True
    assert second["created"] is False  # SADD returned 0 — no duplicate, no error
    assert (await sets.list_following(redis_client, "alice"))["following_count"] == 1


async def test_both_directions_are_written(redis_client):
    await sets.follow(redis_client, "alice", "bob")

    assert await sets.is_following(redis_client, "alice", "bob") is True
    assert await sets.is_following(redis_client, "bob", "alice") is False
    assert (await sets.list_following(redis_client, "bob"))["followers_count"] == 1


async def test_sinter_finds_mutual_follows(redis_client):
    for follower, followee in (
        ("alice", "carol"),
        ("alice", "dave"),
        ("bob", "carol"),
        ("bob", "erin"),
    ):
        await sets.follow(redis_client, follower, followee)

    mutual = await sets.mutual_following(redis_client, "alice", "bob")
    assert mutual["mutual"] == ["carol"]


async def test_sdiff_suggests_who_to_follow(redis_client):
    await sets.follow(redis_client, "alice", "carol")
    await sets.follow(redis_client, "bob", "carol")
    await sets.follow(redis_client, "bob", "erin")

    assert (await sets.suggestions(redis_client, "alice", "bob"))["suggestions"] == ["erin"]


async def test_unfollow_removes_both_edges(redis_client):
    await sets.follow(redis_client, "alice", "bob")
    await sets.unfollow(redis_client, "alice", "bob")

    assert await sets.is_following(redis_client, "alice", "bob") is False
    assert (await sets.list_following(redis_client, "bob"))["followers_count"] == 0
