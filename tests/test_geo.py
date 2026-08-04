"""Geospatial: radius search and distance."""

from app.redis_ops import geo

AMSTERDAM = (4.8952, 52.3702)
UTRECHT = (5.1214, 52.0907)
BERLIN = (13.4050, 52.5200)


async def _seed(client):
    await geo.set_location(client, "alice", *AMSTERDAM)
    await geo.set_location(client, "bob", *UTRECHT)
    await geo.set_location(client, "carol", *BERLIN)


async def test_roundtrip_is_lossy_but_close(redis_client):
    """Geohash quantisation costs ~0.6 m — irrelevant for 'nearby', fatal for surveying."""
    await geo.set_location(redis_client, "alice", *AMSTERDAM)
    location = await geo.get_location(redis_client, "alice")

    assert location is not None
    assert abs(location["longitude"] - AMSTERDAM[0]) < 0.001
    assert abs(location["latitude"] - AMSTERDAM[1]) < 0.001


async def test_radius_excludes_the_far_member(redis_client):
    await _seed(redis_client)
    nearby = await geo.nearby(redis_client, *AMSTERDAM, radius_km=50)

    assert [row["user_id"] for row in nearby] == ["alice", "bob"]  # sorted by distance
    assert "carol" not in [row["user_id"] for row in nearby]  # Berlin is ~577 km away


async def test_widening_the_radius_includes_berlin(redis_client):
    await _seed(redis_client)
    nearby = await geo.nearby(redis_client, *AMSTERDAM, radius_km=700)

    assert {row["user_id"] for row in nearby} == {"alice", "bob", "carol"}


async def test_distance_between_two_members(redis_client):
    await _seed(redis_client)
    km = await geo.distance_between(redis_client, "alice", "carol")

    assert km is not None
    assert 570 < km < 590


async def test_missing_member_returns_none(redis_client):
    await _seed(redis_client)
    assert await geo.distance_between(redis_client, "alice", "ghost") is None
    assert await geo.get_location(redis_client, "ghost") is None
