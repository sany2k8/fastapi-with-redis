"""STREAMS — the application event log.

WHAT IT IS
    An append-only log of entries, each with an auto-generated, monotonically increasing id
    of the form <milliseconds>-<sequence>, and each holding a flat field/value map.

THE PROBLEM IT SOLVES HERE
    Every meaningful thing that happens (user_registered, post_created, user_followed) is
    appended once, then read by anyone who cares — now, or later, or twice.

HOW REDIS STORES IT
    A radix tree of listpack-packed entries, so it is compact and range queries by id (which
    is to say, by time) are fast. Entries stay after being read. That is the defining
    difference from every other Redis structure here.

CONSUMER GROUPS — the part worth understanding
    XREADGROUP hands each entry to exactly one consumer *within* a group, and moves it to
    that consumer's Pending Entries List. It stays pending until XACK. If the consumer dies,
    the entry is still there and another consumer can claim it (XAUTOCLAIM).
    Multiple groups over the same stream each get the full history independently: your
    analytics pipeline and your email sender both see every event without coordinating.

WHY NOT ANOTHER TYPE
    vs LIST as a queue: RPOP is destructive and unacknowledged. One consumer, no history,
      no replay, and a crash between pop and handle loses the message forever. A List is
      right for an inbox; a Stream is right for an event log.
    vs PUB/SUB: fire-and-forget. A subscriber that is offline misses the message entirely,
      and there is no record it existed. Streams persist.
    vs SORTED SET keyed by timestamp: you would rebuild ids, ranges and trimming by hand, and
      still have no consumer groups or acknowledgements.

LIMITATIONS
    Unbounded unless you trim (MAXLEN). It is a log, not a broker: no routing, no topics
    beyond the key name, no partition rebalancing. For millions of events per second across a
    cluster you have outgrown it, and that is what Kafka is for.
"""

from typing import Any, cast

import redis.asyncio as aioredis
from redis.exceptions import ResponseError
from redis.typing import EncodableT, FieldT

from app.core import keys
from app.core.logging import get_logger

log = get_logger(__name__)

MAX_STREAM_LEN = 1000
CONSUMER_GROUP = "analytics"


async def add_event(
    client: aioredis.Redis, event_type: str, payload: dict[str, Any]
) -> dict[str, Any]:
    """XADD with MAXLEN ~ — the `~` means "approximately", letting Redis trim on node
    boundaries. Exact trimming costs measurably more and nobody needs exactly 1000."""
    # Stream fields are a flat map; annotated with redis-py's own alias (see hashes.py).
    fields: dict[FieldT, EncodableT] = {
        "type": event_type,
        **{k: str(v) for k, v in payload.items()},
    }
    event_id = cast(
        str,
        await client.xadd(keys.events(), fields, maxlen=MAX_STREAM_LEN, approximate=True),
    )
    return {"id": event_id, "type": event_type, "fields": fields}


async def read_events(client: aioredis.Redis, count: int = 20) -> list[dict[str, Any]]:
    """XREVRANGE — newest first. Non-destructive: reading changes nothing."""
    rows = cast(
        list[tuple[str, dict[str, str]]],
        await client.xrevrange(keys.events(), max="+", min="-", count=count),
    )
    return [{"id": event_id, **fields} for event_id, fields in rows]


async def ensure_group(client: aioredis.Redis, group: str = CONSUMER_GROUP) -> bool:
    """XGROUP CREATE with MKSTREAM.

    GOTCHA: re-running this raises BUSYGROUP. That error means "the group already exists",
    which is precisely the state we want — so it is success, not failure.
    """
    try:
        await client.xgroup_create(keys.events(), group, id="0", mkstream=True)
        return True
    except ResponseError as exc:
        if "BUSYGROUP" in str(exc):
            return False
        raise


async def consume(
    client: aioredis.Redis,
    consumer: str = "worker-1",
    count: int = 10,
    group: str = CONSUMER_GROUP,
) -> dict[str, Any]:
    """XREADGROUP then XACK — the at-least-once delivery cycle, in one request.

    `>` means "entries never delivered to any consumer in this group". A real worker loops
    this with BLOCK; doing it per-request keeps the demo inspectable and needs no daemon.
    """
    await ensure_group(client, group)

    response = cast(
        list[tuple[str, list[tuple[str, dict[str, str]]]]] | None,
        await client.xreadgroup(
            groupname=group, consumername=consumer, streams={keys.events(): ">"}, count=count
        ),
    )
    if not response:
        pending_now = await pending_count(client, group)
        return {"group": group, "consumer": consumer, "consumed": [], "pending": pending_now}

    _, entries = response[0]
    ids = [entry_id for entry_id, _ in entries]

    # Acknowledge only what we actually processed. Skip the XACK and these entries stay in
    # the PEL forever, which is exactly the safety net you want for work that can fail.
    if ids:
        await client.xack(keys.events(), group, *ids)
        log.info("stream.consumed", group=group, consumer=consumer, count=len(ids))

    return {
        "group": group,
        "consumer": consumer,
        "consumed": [{"id": entry_id, **fields} for entry_id, fields in entries],
        "pending": await pending_count(client, group),
    }


async def pending_count(client: aioredis.Redis, group: str = CONSUMER_GROUP) -> int:
    """XPENDING — entries delivered but not yet acknowledged."""
    try:
        summary = await client.xpending(keys.events(), group)
        return int(summary.get("pending", 0))
    except ResponseError:
        return 0


async def info(client: aioredis.Redis) -> dict[str, Any]:
    try:
        raw = await client.xinfo_stream(keys.events())
    except ResponseError:
        return {"length": 0, "groups": 0}
    return {
        "length": raw.get("length", 0),
        "groups": raw.get("groups", 0),
        "last_id": raw.get("last-generated-id"),
    }
