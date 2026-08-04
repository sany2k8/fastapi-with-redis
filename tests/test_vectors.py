"""Vector sets: similarity ranking, not exact matching."""

import pytest

from app.redis_ops import vectors


@pytest.fixture(autouse=True)
async def _requires_vectorset(module_check):
    await module_check("vectorset")


def test_embedding_is_deterministic_and_normalised():
    """Same tags in, same vector out — no model, no randomness."""
    first = vectors.embed(["redis", "python"])
    second = vectors.embed(["redis", "python"])

    assert first == second
    assert len(first) == vectors.DIM
    assert abs(sum(component**2 for component in first) - 1.0) < 0.01  # unit length


def test_tag_order_and_case_do_not_matter():
    assert vectors.embed(["Redis", "Python"]) == vectors.embed(["python", "redis"])


async def test_shared_tags_rank_above_unrelated_ones(redis_client):
    await vectors.upsert(redis_client, "alice", ["redis", "python", "databases"])
    await vectors.upsert(redis_client, "bob", ["redis", "python", "kafka"])
    await vectors.upsert(redis_client, "carol", ["cooking", "travel", "photography"])

    result = await vectors.similar(redis_client, "alice", k=2)
    neighbours = [row["user_id"] for row in result["neighbours"]]

    assert neighbours[0] == "bob"  # 2 of 3 tags shared
    assert neighbours.index("bob") < neighbours.index("carol")


async def test_the_query_element_is_excluded(redis_client):
    await vectors.upsert(redis_client, "alice", ["redis"])
    await vectors.upsert(redis_client, "bob", ["redis"])

    result = await vectors.similar(redis_client, "alice", k=5)
    assert "alice" not in [row["user_id"] for row in result["neighbours"]]


async def test_search_by_tags_needs_no_stored_user(redis_client):
    """The semantic-search shape: embed a query, search the same index."""
    await vectors.upsert(redis_client, "alice", ["redis", "python", "databases"])
    await vectors.upsert(redis_client, "carol", ["cooking", "travel"])

    result = await vectors.search_by_tags(redis_client, ["redis", "python", "databases"], k=2)
    assert result["matches"][0]["user_id"] == "alice"
    assert result["matches"][0]["similarity"] > 0.99  # identical tags -> identical vector


async def test_unknown_member_is_handled(redis_client):
    await vectors.upsert(redis_client, "alice", ["redis"])
    result = await vectors.similar(redis_client, "ghost")

    assert result["neighbours"] == []
