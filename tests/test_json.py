"""RedisJSON: paths, nesting and arrays."""

import pytest

from app.redis_ops import jsondoc

PROFILE = {
    "name": "Alice",
    "interests": ["redis", "python"],
    "prefs": {"theme": "dark", "notifications": {"email": True}},
    "stats": {"logins": 0},
}


@pytest.fixture(autouse=True)
async def _requires_json(module_check):
    await module_check("rejson")


async def test_set_and_get_whole_document(redis_client):
    await jsondoc.set_profile(redis_client, "alice", PROFILE)

    assert await jsondoc.get_profile(redis_client, "alice") == PROFILE


async def test_read_a_nested_path(redis_client):
    """A `$`-rooted JSONPath returns a list of matches; a single hit is unwrapped."""
    await jsondoc.set_profile(redis_client, "alice", PROFILE)

    assert await jsondoc.get_profile(redis_client, "alice", "$.prefs.notifications.email") is True


async def test_array_append_does_not_rewrite_the_document(redis_client):
    await jsondoc.set_profile(redis_client, "alice", PROFILE)
    result = await jsondoc.append_interests(redis_client, "alice", ["databases"])

    assert result["length"] == 3
    assert result["interests"] == ["redis", "python", "databases"]
    # The rest of the document survived untouched.
    assert await jsondoc.get_profile(redis_client, "alice", "$.prefs.theme") == "dark"


async def test_numincrby_on_a_nested_leaf(redis_client):
    await jsondoc.set_profile(redis_client, "alice", PROFILE)
    await jsondoc.increment_path(redis_client, "alice", "$.stats.logins", 3)

    assert await jsondoc.get_profile(redis_client, "alice", "$.stats.logins") == 3


async def test_missing_profile_is_none(redis_client):
    assert await jsondoc.get_profile(redis_client, "ghost") is None
