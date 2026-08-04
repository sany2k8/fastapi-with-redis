"""The 12-step end-to-end scenario: every Redis data type, in one story.

Exposed twice — as `GET /demo/scenario` and as `rdp demo` — from this one implementation.
Each step reports the Redis commands it issued, because that mapping is the lesson.
"""

from typing import Any

import redis.asyncio as aioredis

from app.core import keys
from app.core.client import bootstrap
from app.core.logging import get_logger
from app.redis_ops import (
    bitfields,
    bitmaps,
    geo,
    hashes,
    jsondoc,
    lists,
    probabilistic,
    sets,
    sortedsets,
    streams,
    strings,
    timeseries,
    vectors,
)

log = get_logger(__name__)

USERS = {
    "alice": {"name": "Alice", "email": "alice@example.com", "country": "NL", "role": "member"},
    "bob": {"name": "Bob", "email": "bob@example.com", "country": "DE", "role": "member"},
    "carol": {"name": "Carol", "email": "carol@example.com", "country": "NL", "role": "admin"},
}
# Amsterdam, Utrecht (~35 km), Berlin (~577 km) — far enough apart to make a radius search
# actually mean something.
LOCATIONS = {
    "alice": (4.8952, 52.3702),
    "bob": (5.1214, 52.0907),
    "carol": (13.4050, 52.5200),
}
TAGS = {
    "alice": ["redis", "python", "databases"],
    "bob": ["redis", "python", "kafka"],
    "carol": ["cooking", "travel", "photography"],
}


def _step(n: int, title: str, type_: str, commands: list[str], result: Any) -> dict[str, Any]:
    return {"step": n, "title": title, "type": type_, "commands": commands, "result": result}


async def reset(client: aioredis.Redis) -> int:
    """Delete everything this app owns, by prefix. SCAN, never KEYS — KEYS blocks the server.

    Then re-bootstrap. This is not optional housekeeping: the Count-Min Sketch and Top-K keys
    live under the same prefix, and unlike a Bloom filter they do NOT auto-create on first
    write. Deleting them without re-reserving leaves every later CMS.INCRBY failing with
    "CMS: key does not exist". Resetting must restore an empty *usable* state, not just an
    empty one.
    """
    # The HTTP latency series is operational data written by the middleware, not demo data.
    # Wiping it would make GET /timeseries/http-latency permanently empty right after the one
    # command people run first, which is the opposite of the point.
    preserve = {keys.metric(keys.HTTP_LATENCY_METRIC)}

    deleted = 0
    cursor = 0
    while True:
        cursor, batch = await client.scan(cursor=cursor, match=keys.scan_pattern(), count=500)
        doomed = [key for key in batch if key not in preserve]
        if doomed:
            deleted += int(await client.delete(*doomed))
        if cursor == 0:
            break

    await bootstrap(client)
    log.info("demo.reset", deleted_keys=deleted)
    return deleted


async def run(client: aioredis.Redis, only: str | None = None) -> dict[str, Any]:
    """Run the scenario. `only` filters to one data type (e.g. "sets")."""
    steps: list[dict[str, Any]] = []

    # --- 1. HASH: the user record -------------------------------------------------
    created = {}
    for user_id, fields in USERS.items():
        await hashes.upsert_user(client, user_id, dict(fields))
        created[user_id] = await hashes.get_user(client, user_id)
    await hashes.increment_karma(client, "alice", 5)
    steps.append(
        _step(
            1,
            "Create three users — a flat object with independently updatable fields",
            "hashes",
            ["HSET rdp:user:alice name Alice email …", "HINCRBY rdp:user:alice karma 5"],
            {"users": created, "alice_karma": await hashes.get_fields(client, "alice", ["karma"])},
        )
    )

    # --- 2. JSON: the nested profile, with arrays ---------------------------------
    await jsondoc.set_profile(
        client,
        "alice",
        {
            "name": "Alice",
            "email": "alice@example.com",
            "interests": ["redis", "python"],
            "devices": [{"type": "phone", "os": "ios"}, {"type": "laptop", "os": "linux"}],
            "prefs": {"theme": "dark", "notifications": {"email": True, "push": False}},
            "stats": {"logins": 0},
        },
    )
    appended = await jsondoc.append_interests(client, "alice", ["databases"])
    theme = await jsondoc.get_profile(client, "alice", "$.prefs.notifications.email")
    steps.append(
        _step(
            2,
            "Store a nested profile and append to an array inside it — no read-modify-write",
            "json",
            [
                "JSON.SET rdp:profile:alice $ '{…}'",
                "JSON.ARRAPPEND rdp:profile:alice $.interests '\"databases\"'",
                "JSON.GET rdp:profile:alice $.prefs.notifications.email",
            ],
            {
                "interests_after_append": appended,
                "nested_path_read": theme,
                "note": "A Hash cannot nest; a JSON-in-a-String cannot append atomically.",
            },
        )
    )

    # --- 3. STRING: session with TTL ----------------------------------------------
    session = await strings.create_session(client, "alice", ttl_seconds=900)
    for _ in range(3):
        views = await strings.increment_views(client, "post-1")
    steps.append(
        _step(
            3,
            "Alice logs in — a self-expiring session and an atomic view counter",
            "strings",
            [
                "SET rdp:session:alice <token> EX 900",
                "TTL rdp:session:alice",
                "INCR rdp:post:post-1:views",
            ],
            {"session": session, "post_views": views},
        )
    )

    # --- 4. BITMAP: daily activity + retention ------------------------------------
    today, yesterday = bitmaps.today(), bitmaps.yesterday()
    await bitmaps.seed_day(client, yesterday, ["alice", "bob", "carol"])
    await bitmaps.seed_day(client, today, ["alice", "bob"])
    steps.append(
        _step(
            4,
            "Track daily actives in bits, then compute retention entirely inside Redis",
            "bitmaps",
            [
                f"SETBIT rdp:activity:{today} 0 1",
                f"BITCOUNT rdp:activity:{today}",
                f"BITOP AND scratch rdp:activity:{yesterday} rdp:activity:{today}",
            ],
            {
                "today": await bitmaps.day_stats(client, today, "alice"),
                "retention": await bitmaps.retention(client, yesterday, today),
                "note": "3 users cost 1 byte. A million would cost 125 KB per day.",
            },
        )
    )

    # --- 5. SET: the follow graph --------------------------------------------------
    await sets.follow(client, "alice", "bob")
    await sets.follow(client, "alice", "carol")
    await sets.follow(client, "bob", "carol")
    await sets.follow(client, "alice", "bob")  # idempotent — SADD returns 0, nothing breaks
    steps.append(
        _step(
            5,
            "Follow relationships — unique, O(1) membership, set algebra server-side",
            "sets",
            [
                "SADD rdp:following:alice bob",
                "SISMEMBER rdp:following:alice bob",
                "SINTER rdp:following:alice rdp:following:bob",
            ],
            {
                "alice_following": await sets.list_following(client, "alice"),
                "mutual_alice_bob": await sets.mutual_following(client, "alice", "bob"),
                "double_follow_was_idempotent": True,
            },
        )
    )

    # --- 6. LIST: the notification inbox -------------------------------------------
    await lists.push_notification(client, "alice", "new_follower", "bob started following you")
    await lists.push_notification(client, "alice", "system", "Welcome to the playground")
    popped = await lists.pop_oldest(client, "alice")
    steps.append(
        _step(
            6,
            "A capped notification inbox — LPUSH+LTRIM to cap it, RPOP to consume FIFO",
            "lists",
            [
                "LPUSH rdp:notifications:alice '{…}'",
                "LTRIM rdp:notifications:alice 0 99",
                "RPOP rdp:notifications:alice",
            ],
            {
                "inbox": await lists.list_notifications(client, "alice"),
                "popped_oldest": popped,
                "note": "RPOP is destructive — gone from Redis. Compare with the Stream in step 9.",
            },
        )
    )

    # --- 7. SORTED SET: the leaderboard --------------------------------------------
    await sortedsets.add_points(client, "alice", 1200)
    await sortedsets.add_points(client, "bob", 1800)
    await sortedsets.add_points(client, "carol", 1500)
    await sortedsets.add_points(client, "alice", 700)  # 1200 + 700 = 1900, alice takes the lead
    steps.append(
        _step(
            7,
            "Points and ranking — ordering maintained on write, never sorted on read",
            "sortedsets",
            [
                "ZINCRBY rdp:leaderboard:global 700 alice",
                "ZREVRANGE rdp:leaderboard:global 0 9 WITHSCORES",
                "ZREVRANK rdp:leaderboard:global alice",
            ],
            {
                "leaderboard": await sortedsets.top(client, 10),
                "alice_rank": await sortedsets.rank_of(client, "alice"),
            },
        )
    )

    # --- 8. GEO: nearby users -------------------------------------------------------
    for user_id, (lon, lat) in LOCATIONS.items():
        await geo.set_location(client, user_id, lon, lat)
    steps.append(
        _step(
            8,
            "Locations and proximity — a Sorted Set of geohashes underneath",
            "geo",
            [
                "GEOADD rdp:geo:users 4.8952 52.3702 alice",
                "GEOSEARCH rdp:geo:users FROMLONLAT 4.8952 52.3702 BYRADIUS 50 km ASC WITHDIST",
                "GEODIST rdp:geo:users alice carol km",
            ],
            {
                "within_50km_of_amsterdam": await geo.nearby(client, 4.8952, 52.3702, 50),
                "amsterdam_to_berlin_km": await geo.distance_between(client, "alice", "carol"),
                "note": "GEOADD takes (longitude, latitude) — the reverse of how people say it.",
            },
        )
    )

    # --- 9. STREAM: the event log ----------------------------------------------------
    for event_type, payload in (
        ("user_registered", {"user_id": "alice"}),
        ("user_followed", {"follower": "alice", "followee": "bob"}),
        ("post_created", {"user_id": "alice", "post_id": "post-1"}),
    ):
        await streams.add_event(client, event_type, payload)
    consumed = await streams.consume(client, consumer="demo-worker", count=10)
    steps.append(
        _step(
            9,
            "Append events, then consume them through a group — history survives the read",
            "streams",
            [
                "XADD rdp:stream:events MAXLEN ~ 1000 * type user_registered …",
                "XGROUP CREATE rdp:stream:events analytics 0 MKSTREAM",
                "XREADGROUP GROUP analytics demo-worker COUNT 10 STREAMS rdp:stream:events >",
                "XACK rdp:stream:events analytics <id>",
            ],
            {
                "consumed": consumed,
                "still_in_stream": await streams.info(client),
                "note": "Consumed AND still there — unlike the List in step 6.",
            },
        )
    )

    # --- 10. TIME SERIES: metrics -----------------------------------------------------
    now = timeseries.now_ms()
    for i, latency in enumerate([12.0, 18.5, 9.75, 30.0, 14.25]):
        await timeseries.record(
            client, "demo_latency_ms", latency, now - (5 - i) * 1000, {"kind": "demo", "unit": "ms"}
        )
    steps.append(
        _step(
            10,
            "Timestamped measurements with retention and server-side aggregation",
            "timeseries",
            [
                "TS.CREATE rdp:metric:demo_latency_ms RETENTION 86400000"
                " DUPLICATE_POLICY LAST LABELS kind demo",
                "TS.ADD rdp:metric:demo_latency_ms <ts> 12.0",
                "TS.RANGE rdp:metric:demo_latency_ms - + AGGREGATION avg 5000",
            ],
            {
                "raw": await timeseries.range_query(client, "demo_latency_ms"),
                "downsampled_avg_5s": await timeseries.range_query(
                    client, "demo_latency_ms", bucket_ms=5000, aggregation="avg"
                ),
                "real_http_latency": await timeseries.range_query(
                    client, keys.HTTP_LATENCY_METRIC, from_ms=now - 300_000, bucket_ms=60_000
                ),
            },
        )
    )

    # --- 11. PROBABILISTIC: four sketches ---------------------------------------------
    await probabilistic.add_email(client, "alice@example.com")
    for user_id, term in (
        ("alice", "redis streams"),
        ("bob", "redis streams"),
        ("carol", "redis streams"),
        ("alice", "bitmaps"),
        ("bob", "vector search"),
        ("alice", "redis streams"),
    ):
        await probabilistic.track_search(client, user_id, term)
    steps.append(
        _step(
            11,
            "Approximate analytics — four structures answering four different questions",
            "probabilistic",
            [
                "BF.ADD rdp:bloom:emails alice@example.com",
                "BF.EXISTS rdp:bloom:emails bob@example.com",
                "PFADD rdp:hll:visitors:<day> alice",
                "PFCOUNT rdp:hll:visitors:<day>",
                "CMS.INCRBY rdp:cms:searches 'redis streams' 1",
                "CMS.QUERY rdp:cms:searches 'redis streams'",
                "TOPK.ADD rdp:topk:searches 'redis streams'",
                "TOPK.LIST rdp:topk:searches WITHCOUNT",
            ],
            {
                "seen_email": await probabilistic.check_email(client, "alice@example.com"),
                "unseen_email": await probabilistic.check_email(client, "nobody@example.com"),
                "stats": await probabilistic.search_stats(client),
                "memory": await probabilistic.info(client),
            },
        )
    )

    # --- 12. BITFIELD: packed state ----------------------------------------------------
    await bitfields.set_state(client, "alice", {"level": 7, "streak": 12, "xp": 65_500})
    saturated = await bitfields.add_xp(client, "alice", 100)  # would wrap to 64 without SAT
    steps.append(
        _step(
            12,
            "Level, streak and xp packed into 4 bytes — with a deliberate overflow policy",
            "bitfields",
            [
                "BITFIELD rdp:state:alice SET u8 0 7 SET u8 8 12 SET u16 16 65500",
                "BITFIELD rdp:state:alice OVERFLOW SAT INCRBY u16 16 100",
                "BITFIELD rdp:state:alice GET u8 0 GET u8 8 GET u16 16",
            ],
            {
                "state": await bitfields.get_state(client, "alice"),
                "after_saturating_add": saturated,
                "note": "65500 + 100 saturates at 65535. The default WRAP would have given 64.",
            },
        )
    )

    # --- 13. VECTOR SET: similar users --------------------------------------------------
    for user_id, tags in TAGS.items():
        await vectors.upsert(client, user_id, tags)
    steps.append(
        _step(
            13,
            "Similarity search — ranked by distance, not filtered by exact match",
            "vectors",
            [
                "VADD rdp:vectors:users VALUES 8 <v1..v8> alice",
                "VSIM rdp:vectors:users ELE alice WITHSCORES COUNT 6",
            ],
            {
                "similar_to_alice": await vectors.similar(client, "alice", 3),
                "search_by_taste": await vectors.search_by_tags(client, ["redis", "python"], 3),
                "index": await vectors.info(client),
                "note": "bob shares 2 of 3 tags with alice and ranks above carol, who shares none.",
            },
        )
    )

    if only:
        steps = [s for s in steps if s["type"] == only]

    return {
        "scenario": "Redis Activity & Analytics Playground",
        "types_covered": sorted({s["type"] for s in steps}),
        "step_count": len(steps),
        "steps": steps,
    }
