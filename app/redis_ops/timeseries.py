"""TIME SERIES — API latency and other metrics.

WHAT IT IS
    A purpose-built structure for (timestamp, double) pairs, with retention, downsampling and
    label-based lookup across many series.

THE PROBLEM IT SOLVES HERE
    Every HTTP request records its latency (see the middleware in app/main.py). We then ask
    "average latency per 10-second bucket over the last 5 minutes" — which is what a metrics
    dashboard actually needs.

HOW REDIS STORES IT
    Fixed-size chunks of compressed samples (Gorilla-style delta-of-delta). Roughly a few
    bits per sample rather than ~16 bytes, and samples are chronologically ordered by
    construction so a range query is a seek plus a scan.

WHAT YOU GET THAT YOU WOULD OTHERWISE BUILD
    RETENTION       old samples are evicted automatically. No cleanup job, ever.
    AGGREGATION     avg/min/max/sum/count per time bucket, computed server-side.
    LABELS + MRANGE query many series at once by label, e.g. every series where kind=http.
    RULES           TS.CREATERULE can downsample a raw series into a 1-minute rollup for you.

WHY NOT ANOTHER TYPE
    vs SORTED SET scored by timestamp: this is the tempting one, and it half-works. You get
      ordering and range queries. You do NOT get compression (each sample is a full member
      string), retention (you must write a trimming job), or aggregation (you fetch every raw
      sample and average it in Python). And scores are doubles, so millisecond timestamps are
      fine but nanoseconds silently lose precision.
    vs LIST: no time-range query at all. You would scan.
    vs STREAM: a Stream *is* time-ordered and does retain history, and for events it is the
      right answer. But it stores field/value maps, not numbers, and it cannot aggregate.
      Streams are for "what happened"; Time Series is for "what was the number".

LIMITATIONS
    Doubles only — no strings, no tags per sample (labels are per *series*). One value per
    timestamp per series, so the duplicate policy matters (we use LAST). Not a replacement
    for Prometheus at scale, but excellent for last-24h operational metrics next to your data.
"""

import time
from typing import Any, cast

import redis.asyncio as aioredis
from redis.exceptions import ResponseError

from app.core import keys
from app.core.logging import get_logger

log = get_logger(__name__)


async def ensure_series(
    client: aioredis.Redis,
    name: str,
    retention_ms: int = 86_400_000,
    labels: dict[str, str] | None = None,
) -> bool:
    """TS.CREATE, idempotently.

    GOTCHA: TS.ADD auto-creates a missing series, but with NO retention, NO labels and NO
    duplicate policy — so it would grow forever and be invisible to TS.MRANGE. Always create
    explicitly. "key already exists" is success.
    """
    args: list[Any] = [
        "TS.CREATE",
        keys.metric(name),
        "RETENTION",
        retention_ms,
        "DUPLICATE_POLICY",
        "LAST",
    ]
    if labels:
        args.append("LABELS")
        for key, value in labels.items():
            args += [key, value]

    try:
        await client.execute_command(*args)
        return True
    except ResponseError as exc:
        if "exists" in str(exc).lower():
            return False
        raise


async def record(
    client: aioredis.Redis,
    name: str,
    value: float,
    timestamp_ms: int | None = None,
    labels: dict[str, str] | None = None,
) -> dict[str, Any]:
    """TS.ADD. `*` means "server time now".

    DUPLICATE_POLICY LAST (set at creation) is what stops two requests landing in the same
    millisecond from raising "TSDB: Error at upsert, update is not supported".
    """
    await ensure_series(client, name, labels=labels)
    ts_arg: Any = timestamp_ms if timestamp_ms is not None else "*"
    written = cast(int, await client.execute_command("TS.ADD", keys.metric(name), ts_arg, value))
    return {"metric": name, "timestamp_ms": written, "value": value}


async def range_query(
    client: aioredis.Redis,
    name: str,
    from_ms: int | None = None,
    to_ms: int | None = None,
    bucket_ms: int | None = None,
    aggregation: str = "avg",
) -> dict[str, Any]:
    """TS.RANGE, optionally with AGGREGATION — downsampling happens in Redis, not here.

    Without a bucket you get raw samples; with one you get a fraction of the data and the
    server does the arithmetic. On a busy series that is the difference between 100k samples
    over the wire and 30.
    """
    start: Any = from_ms if from_ms is not None else "-"
    end: Any = to_ms if to_ms is not None else "+"
    args: list[Any] = ["TS.RANGE", keys.metric(name), start, end]
    if bucket_ms:
        args += ["AGGREGATION", aggregation, bucket_ms]

    try:
        rows = cast(list[list[Any]], await client.execute_command(*args))
    except ResponseError as exc:
        if "key does not exist" in str(exc).lower():
            return {"metric": name, "points": [], "count": 0}
        raise

    # With decode_responses=True the value comes back as a string — float() it.
    points = [{"timestamp_ms": int(ts), "value": float(value)} for ts, value in rows]
    return {
        "metric": name,
        "aggregation": aggregation if bucket_ms else "raw",
        "bucket_ms": bucket_ms,
        "count": len(points),
        "points": points,
    }


async def multi_range(
    client: aioredis.Redis,
    label: str,
    value: str,
    from_ms: int | None = None,
    to_ms: int | None = None,
) -> list[dict[str, Any]]:
    """TS.MRANGE — every series matching a label filter, in one command.

    This is what labels are for: you never have to know the series names in advance.
    """
    start: Any = from_ms if from_ms is not None else "-"
    end: Any = to_ms if to_ms is not None else "+"
    raw = await client.execute_command(
        "TS.MRANGE", start, end, "WITHLABELS", "FILTER", f"{label}={value}"
    )

    # GOTCHA: redis-py's response callback turns TS.MRANGE into
    #   {key: [labels_dict, aggregators, [[ts, value], …]]}
    # rather than the flat array the raw protocol returns. Accept both shapes so this does not
    # break when the client version changes.
    series: list[dict[str, Any]] = []
    entries = raw.items() if isinstance(raw, dict) else ((e[0], e[1:]) for e in raw)
    for key, rest in entries:
        labels_raw, samples = rest[0], rest[-1]
        labels = (
            labels_raw
            if isinstance(labels_raw, dict)
            else {pair[0]: pair[1] for pair in labels_raw}
        )
        series.append(
            {
                "key": key,
                "labels": labels,
                "count": len(samples),
                "points": [{"timestamp_ms": int(ts), "value": float(v)} for ts, v in samples],
            }
        )
    return series


def now_ms() -> int:
    return int(time.time() * 1000)
