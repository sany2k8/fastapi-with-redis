"""GEOSPATIAL — find users nearby.

WHAT IT IS
    Not a separate type at all: a Sorted Set whose scores are 52-bit geohashes of
    (longitude, latitude). GEOADD writes the score; GEOSEARCH decodes it.

THE PROBLEM IT SOLVES HERE
    "Which users are within 5 km of this point, nearest first, with distances?" and
    "how far apart are these two users?"

WHY IT WORKS
    A geohash interleaves the bits of latitude and longitude, so points that are close on
    Earth have numerically close hashes. A radius search becomes a handful of *range* scans
    over a sorted set — which is why proximity search costs O(N + log M) rather than a full
    scan with a distance calculation per member.

    Because it is a Sorted Set underneath, ZREM removes a member and ZCARD counts them. That
    is not a hack; it is the actual storage.

WHY NOT ANOTHER TYPE
    vs HASH of user -> "lat,lon": you can store it, but every proximity query means loading
      every user and computing haversine in your app. O(N) over the network, per query.
    vs a real spatial database (PostGIS): Redis does radius and box searches on points, and
      that is all. No polygons, no intersections, no joins, no "within this city boundary".
      When the question outgrows circles, Redis is the wrong tool — but "drivers near me"
      almost never outgrows circles.

LIMITATIONS
    Points only. Accuracy is ~0.6 m from the geohash quantisation, irrelevant for "nearby"
    and fatal for surveying. No altitude. Valid latitude is ±85.05° (Mercator), not ±90.
"""

from typing import Any, cast

import redis.asyncio as aioredis

from app.core import keys


async def set_location(
    client: aioredis.Redis, user_id: str, longitude: float, latitude: float
) -> dict[str, Any]:
    """GEOADD — note the argument order is (lon, lat), which is the reverse of how most
    people say it out loud. This is the single most common geo bug."""
    await client.geoadd(keys.geo_users(), (longitude, latitude, user_id))
    return {"user_id": user_id, "longitude": longitude, "latitude": latitude}


async def get_location(client: aioredis.Redis, user_id: str) -> dict[str, Any] | None:
    """GEOPOS returns the *decoded* position, so it differs from the input by a few cm."""
    positions = cast(list[Any], await client.geopos(keys.geo_users(), user_id))
    if not positions or positions[0] is None:
        return None
    lon, lat = positions[0]
    return {"user_id": user_id, "longitude": float(lon), "latitude": float(lat)}


async def nearby(
    client: aioredis.Redis, longitude: float, latitude: float, radius_km: float, count: int = 10
) -> list[dict[str, Any]]:
    """GEOSEARCH FROMLONLAT BYRADIUS ... ASC — sorted by distance, computed server-side."""
    rows = cast(
        list[Any],
        await client.geosearch(
            keys.geo_users(),
            longitude=longitude,
            latitude=latitude,
            radius=radius_km,
            unit="km",
            sort="ASC",
            count=count,
            withdist=True,
            withcoord=True,
        ),
    )
    results: list[dict[str, Any]] = []
    for row in rows:
        member, distance, (lon, lat) = row[0], row[1], row[2]
        results.append(
            {
                "user_id": member,
                "distance_km": round(float(distance), 3),
                "longitude": float(lon),
                "latitude": float(lat),
            }
        )
    return results


async def distance_between(
    client: aioredis.Redis, user_a: str, user_b: str, unit: str = "km"
) -> float | None:
    """GEODIST — returns None if either member is missing, rather than erroring."""
    raw = await client.geodist(keys.geo_users(), user_a, user_b, unit=unit)
    return round(float(raw), 3) if raw is not None else None
