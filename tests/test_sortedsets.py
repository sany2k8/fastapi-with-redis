"""Sorted sets: score-ordered ranking maintained on write."""

from app.redis_ops import sortedsets


async def test_ranking_reorders_itself_on_write(redis_client):
    await sortedsets.add_points(redis_client, "alice", 1200)
    await sortedsets.add_points(redis_client, "bob", 1800)
    await sortedsets.add_points(redis_client, "carol", 1500)

    assert [row["user_id"] for row in await sortedsets.top(redis_client, 3)] == [
        "bob",
        "carol",
        "alice",
    ]

    await sortedsets.add_points(redis_client, "alice", 700)  # 1900 — takes the lead
    assert (await sortedsets.top(redis_client, 1))[0]["user_id"] == "alice"


async def test_zincrby_accumulates_rather_than_overwrites(redis_client):
    await sortedsets.add_points(redis_client, "alice", 10)
    result = await sortedsets.add_points(redis_client, "alice", 5)

    assert result["score"] == 15


async def test_rank_is_one_based_with_a_denominator(redis_client):
    await sortedsets.add_points(redis_client, "alice", 100)
    await sortedsets.add_points(redis_client, "bob", 200)

    rank = await sortedsets.rank_of(redis_client, "alice")
    assert rank == {"user_id": "alice", "rank": 2, "score": 100.0, "out_of": 2}


async def test_unranked_user_is_none(redis_client):
    assert await sortedsets.rank_of(redis_client, "nobody") is None
