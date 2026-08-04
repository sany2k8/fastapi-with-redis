"""API smoke tests: the HTTP layer wires up, and the demo runs all 13 types end to end."""

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """Runs the real lifespan, so this also asserts that bootstrap and module checks pass."""
    async with (
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http_client,
        app.router.lifespan_context(app),
    ):
        yield http_client


async def test_health_reports_every_module(client):
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json()["all_types_available"] is True


async def test_demo_scenario_covers_all_thirteen_types(client):
    response = await client.get("/demo/scenario")

    assert response.status_code == 200
    body = response.json()
    assert body["step_count"] == 13
    assert len(body["types_covered"]) == 13


async def test_demo_can_run_one_type(client):
    response = await client.get("/demo/scenario", params={"only": "sets", "reset": "true"})

    assert [step["type"] for step in response.json()["steps"]] == ["sets"]


async def test_keyspace_inspection_after_the_demo(client):
    await client.get("/demo/scenario")
    body = (await client.get("/demo/keys")).json()

    # Every underlying Redis type the playground creates should show up here.
    assert {"hash", "string", "list", "set", "zset", "stream", "ReJSON-RL"} <= set(body["by_type"])


async def test_reset_leaves_an_empty_but_usable_keyspace(client):
    """Reset re-reserves the sketches it deleted.

    CMS and Top-K do not auto-create on write, so a reset that merely deleted them would leave
    every later CMS.INCRBY failing. What survives is exactly those structures, holding no data.
    """
    await client.get("/demo/scenario")
    await client.post("/demo/reset")

    remaining = (await client.get("/demo/keys")).json()
    assert set(remaining["by_type"]) == {"CMSk-TYPE", "TopK-TYPE", "TSDB-TYPE"}

    # And the playground still works afterwards.
    tracked = await client.post("/probabilistic/search", json={"user_id": "alice", "term": "redis"})
    assert tracked.status_code == 200


async def test_decision_matrix_is_served(client):
    body = (await client.get("/demo/types")).json()

    assert body["count"] == 16
    required = {"requirement", "type", "why", "common_mistake"}
    assert all(required <= set(row) for row in body["matrix"])


async def test_a_round_trip_through_one_type(client):
    """Router -> redis_ops -> Redis, for one representative endpoint."""
    await client.post("/hashes/users", json={"id": "zoe", "name": "Zoe", "email": "z@e.com"})
    response = await client.get("/hashes/users/zoe")

    assert response.status_code == 200
    assert response.json()["name"] == "Zoe"
    assert (await client.get("/hashes/users/nobody")).status_code == 404
