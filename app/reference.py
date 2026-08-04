"""The decision matrix — the single most useful artefact in this repo.

Served at GET /demo/types and rendered by `rdp types`. The "common mistake" column is the
part you cannot get from the Redis docs: the plausible-looking wrong choice for each problem.
"""

from typing import Any

DECISION_MATRIX: list[dict[str, str]] = [
    {
        "requirement": "A single value, or a value that must expire",
        "type": "String",
        "why": "One key, one value, one TTL. INCR is atomic.",
        "common_mistake": "A Hash with one field — you cannot expire a field as easily as a key.",
    },
    {
        "requirement": "A flat object whose fields change independently",
        "type": "Hash",
        "why": "HSET/HINCRBY touch one field atomically; listpack encoding is compact.",
        "common_mistake": "JSON in a String — every update is a read-modify-write race.",
    },
    {
        "requirement": "A nested document, or arrays inside a document",
        "type": "JSON",
        "why": "JSONPath reads and writes one leaf without touching the rest.",
        "common_mistake": "A Hash with dotted field names, re-inventing paths by hand.",
    },
    {
        "requirement": "An ordered queue, or a capped 'recent items' feed",
        "type": "List",
        "why": "O(1) at both ends; LPUSH+LTRIM caps it, LPUSH+RPOP makes it FIFO.",
        "common_mistake": "A Sorted Set scored by timestamp when you never query by score.",
    },
    {
        "requirement": "A unique collection with fast membership tests",
        "type": "Set",
        "why": "O(1) SISMEMBER, structural uniqueness, and SINTER/SDIFF run server-side.",
        "common_mistake": "A List — membership becomes O(N) and duplicates corrupt counts.",
    },
    {
        "requirement": "Ranking by score (leaderboard, top-N, priority)",
        "type": "Sorted Set",
        "why": "Ordering is maintained on write; top-N never sorts at read time.",
        "common_mistake": "A Hash of user→points plus a client-side sort of the whole table.",
    },
    {
        "requirement": "Boolean state for millions of entities",
        "type": "Bitmap",
        "why": "1 bit each — 1M users is 125 KB/day, and BITOP does set algebra on it.",
        "common_mistake": "A Set of ids per day: correct, and roughly 50x the memory.",
    },
    {
        "requirement": "Several small integers per record, at huge scale",
        "type": "Bitfield",
        "why": "Pack level/streak/xp into 4 bytes with an explicit overflow policy.",
        "common_mistake": "Reaching for it before memory is measurably the problem.",
    },
    {
        "requirement": "'What is near this point?'",
        "type": "Geospatial",
        "why": "Geohash scores in a Sorted Set turn radius search into range scans.",
        "common_mistake": "Storing lat/lon in a Hash and computing haversine in the app.",
    },
    {
        "requirement": "An event log many consumers read independently",
        "type": "Stream",
        "why": "Entries persist after reading; consumer groups add acks and replay.",
        "common_mistake": "A List you RPOP — destructive, single-consumer, no history.",
    },
    {
        "requirement": "Timestamped numeric measurements",
        "type": "Time Series",
        "why": "Compression, retention and server-side aggregation, all built in.",
        "common_mistake": "A Sorted Set scored by timestamp — no retention, no aggregation.",
    },
    {
        "requirement": "'Have I definitely never seen this?'",
        "type": "Bloom Filter",
        "why": "No false negatives, so a 'no' is a guarantee — a cheap gate before an exact check.",
        "common_mistake": "An exact Set of every id ever seen, growing without bound.",
    },
    {
        "requirement": "'How many distinct?' at huge cardinality",
        "type": "HyperLogLog",
        "why": "12 KB flat, ~0.81% error, and PFMERGE unions periods correctly.",
        "common_mistake": "Summing daily unique counts — that double-counts returning users.",
    },
    {
        "requirement": "'How often did THIS happen?' over a wide stream",
        "type": "Count-Min Sketch",
        "why": "Fixed memory; over-counts on collision, never under-counts.",
        "common_mistake": "A Hash keyed by user-supplied text — unbounded cardinality.",
    },
    {
        "requirement": "'Which are the biggest?' over a wide stream",
        "type": "Top-K",
        "why": "Bounded memory, and unlike a CMS it can enumerate its members.",
        "common_mistake": "A Sorted Set with one member per distinct term.",
    },
    {
        "requirement": "'What is similar to this?'",
        "type": "Vector Set",
        "why": "HNSW nearest-neighbour search ranks by distance rather than filtering.",
        "common_mistake": "Set intersection on tags — exact, boolean, and blind to near matches.",
    },
]


def matrix() -> dict[str, Any]:
    return {"count": len(DECISION_MATRIX), "matrix": DECISION_MATRIX}
