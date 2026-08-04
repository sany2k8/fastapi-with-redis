"""Probabilistic structures: the semantics, not the exact numbers.

These tests assert what each structure GUARANTEES — no false negatives, never under-counts,
approximate cardinality within tolerance — because asserting exact values would be asserting
the wrong thing about an approximate structure.
"""

import pytest

from app.redis_ops import probabilistic


@pytest.fixture(autouse=True)
async def _requires_bloom(module_check):
    await module_check("bf")


async def test_bloom_has_no_false_negatives(redis_client):
    """The core guarantee: something added is ALWAYS reported as present."""
    for i in range(200):
        await probabilistic.add_email(redis_client, f"user{i}@example.com")

    for i in range(200):
        result = await probabilistic.check_email(redis_client, f"user{i}@example.com")
        assert result["verdict"] == "probably_seen"


async def test_bloom_definitely_new_is_certain(redis_client):
    await probabilistic.add_email(redis_client, "alice@example.com")
    result = await probabilistic.check_email(redis_client, "nobody-at-all@example.com")

    assert result["verdict"] == "definitely_new"
    assert result["certain"] is True


async def test_bloom_add_reports_novelty(redis_client):
    assert (await probabilistic.add_email(redis_client, "a@example.com"))["added"] is True
    assert (await probabilistic.add_email(redis_client, "a@example.com"))["added"] is False


async def test_hyperloglog_estimates_distinct_users(redis_client):
    """500 distinct users, counted in ~12 KB, within HLL's ~0.81% standard error."""
    for i in range(500):
        await probabilistic.track_search(redis_client, f"user{i}", "redis")

    stats = await probabilistic.search_stats(redis_client)
    estimate = stats["hyperloglog"]["unique_users"]
    assert 480 <= estimate <= 520


async def test_count_min_sketch_never_under_counts(redis_client):
    """Collisions can only inflate the estimate — that is the guarantee you rely on."""
    for _ in range(30):
        await probabilistic.track_search(redis_client, "alice", "redis streams")
    for _ in range(5):
        await probabilistic.track_search(redis_client, "alice", "bitmaps")

    stats = await probabilistic.search_stats(redis_client, terms=["redis streams", "bitmaps"])
    counts = {row["term"]: row["approx_count"] for row in stats["count_min_sketch"]["counts"]}

    assert counts["redis streams"] >= 30
    assert counts["bitmaps"] >= 5


async def test_topk_enumerates_the_heavy_hitters(redis_client):
    """The thing a Count-Min Sketch cannot do: list its own members."""
    for _ in range(50):
        await probabilistic.track_search(redis_client, "alice", "popular")
    for _ in range(2):
        await probabilistic.track_search(redis_client, "bob", "rare")

    stats = await probabilistic.search_stats(redis_client)
    terms = [row["term"] for row in stats["top_k"]["terms"]]

    assert terms[0] == "popular"
    assert "rare" in terms  # only 2 distinct terms, so both fit in a k=5 sketch


async def test_memory_stays_bounded(redis_client):
    """20k events into fixed-size sketches — the entire point of using them."""
    for i in range(2_000):
        await probabilistic.track_search(redis_client, f"user{i}", f"term-{i % 50}")

    info = await probabilistic.info(redis_client)
    assert info["hll_visitors"]["bytes"] < 20_000  # HLL is capped at ~12 KB + overhead
