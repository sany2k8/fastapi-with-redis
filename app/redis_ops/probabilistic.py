"""PROBABILISTIC STRUCTURES — four sketches, one event stream.

THE BIG IDEA
    Each of these trades a bounded, quantified amount of accuracy for a colossal reduction in
    memory. They answer questions about a stream you could never afford to answer exactly.
    The four answer genuinely *different* questions, which is why this module feeds one
    search event into three of them at once — so you can see the difference, not read about it.

        HyperLogLog     "how many DISTINCT terms/users?"     ~0.81% error, 12 KB, forever
        Count-Min Sketch "how often THIS one?"                over-counts, never under-counts
        Top-K            "which are the biggest?"             the heavy hitters, not all counts
        Bloom filter     "have I DEFINITELY not seen this?"   no false negatives, some false +

----------------------------------------------------------------------------------------
BLOOM FILTER — has this email been seen before?
    A bit array plus k hash functions. Answers "definitely not present" or "probably present".
    False positives yes, false negatives never — so a "no" is a guarantee.
    USE IT: as a cheap gate in front of an expensive exact check. "Probably seen" -> query the
    database; "definitely new" -> skip the query entirely. That inversion is the whole value.
    NOT A SET: an exact Set of 100M emails is gigabytes; this is ~100 MB at 0.1% error, and
    it can never tell you *which* emails it holds — you cannot enumerate a Bloom filter.

HYPERLOGLOG — how many unique visitors today?
    Counts distinct items in a fixed 12 KB, whether you feed it a thousand items or a billion.
    ~0.81% standard error. PFMERGE unions two HLLs, so daily HLLs merge into a weekly unique
    count *correctly* — which summing daily counts does not do.
    NOT A SET: a Set of 10M visitor ids is ~400 MB and grows; the HLL stays 12 KB. The Set can
    answer "was user X here?"; the HLL cannot, ever. That is the entire trade.

COUNT-MIN SKETCH — how often has this term been searched?
    A 2D array of counters and d hash functions; the estimate is the minimum across rows.
    Collisions can only ever inflate a count, so it OVER-estimates and never under-estimates.
    NOT A HASH of term -> count: exact, but unbounded — a hash keyed by user-supplied search
    text grows to the cardinality of the internet. The sketch is fixed-size by construction.
    You must know the term to ask about it: a CMS cannot list its own keys.

TOP-K — which terms are the most searched?
    Keeps the k heaviest hitters (HeavyKeepers). It *can* enumerate, which is precisely what
    the Count-Min Sketch cannot do — hence keeping both.
    NOT A SORTED SET: a ZSET ranks exactly, but needs one member per distinct term. For high
    cardinality streams that is the unbounded-memory problem again. Top-K is bounded.
----------------------------------------------------------------------------------------

LIMITATIONS (all four)
    Approximate by design — never use them for billing, quotas or anything auditable. Sizing
    is chosen up front and cannot be changed without rebuilding. CMS and Top-K must be
    created before first write (see core/client.bootstrap) — unlike BF.ADD, which auto-creates.
"""

from typing import Any, cast

import redis.asyncio as aioredis

from app.core import keys
from app.redis_ops.bitmaps import today


# --- Bloom filter --------------------------------------------------------------------
async def add_email(client: aioredis.Redis, email: str) -> dict[str, Any]:
    """BF.ADD returns 1 if newly added, 0 if it was (probably) already there.

    BF.ADD auto-creates the filter with default parameters. CMS and Top-K do not — that
    asymmetry is the most common Redis-probabilistic bug.
    """
    added = cast(int, await client.execute_command("BF.ADD", keys.bloom_emails(), email))
    return {"email": email, "added": bool(added), "probably_seen_before": not bool(added)}


async def check_email(client: aioredis.Redis, email: str) -> dict[str, Any]:
    """BF.EXISTS. Read the answer carefully — 0 is certain, 1 is not."""
    exists = bool(await client.execute_command("BF.EXISTS", keys.bloom_emails(), email))
    return {
        "email": email,
        "verdict": "probably_seen" if exists else "definitely_new",
        "certain": not exists,
        "note": (
            "A Bloom filter can produce false positives but never false negatives, "
            "so 'definitely_new' is a guarantee and 'probably_seen' is not."
        ),
    }


# --- One event, three sketches -------------------------------------------------------
async def track_search(client: aioredis.Redis, user_id: str, term: str) -> dict[str, Any]:
    """A single search event fanned out to HyperLogLog, Count-Min Sketch and Top-K.

    Same input, three structures, three different questions answered later. Pipelined
    because they are independent — one round trip for all three.
    """
    term = term.strip().lower()
    day = today()

    async with client.pipeline(transaction=False) as pipe:
        pipe.execute_command("PFADD", keys.hll_visitors(day), user_id)  # distinct users
        pipe.execute_command("CMS.INCRBY", keys.cms_searches(), term, 1)  # frequency of term
        pipe.execute_command("TOPK.ADD", keys.topk_searches(), term)  # heavy hitters
        results = await pipe.execute()

    return {
        "term": term,
        "user_id": user_id,
        "day": day,
        "hll_new_user": bool(results[0]),
        "cms_estimate": int(results[1][0]) if results[1] else 0,
        "topk_evicted": results[2][0] if results[2] and results[2][0] else None,
    }


async def search_stats(
    client: aioredis.Redis, terms: list[str] | None = None, day: str | None = None
) -> dict[str, Any]:
    """PFCOUNT + TOPK.LIST WITHCOUNT + CMS.QUERY — the three answers, side by side."""
    day = day or today()

    unique_users = cast(int, await client.execute_command("PFCOUNT", keys.hll_visitors(day)))

    # TOPK.LIST WITHCOUNT returns a flat [member, count, member, count, ...].
    flat = cast(
        list[Any],
        await client.execute_command("TOPK.LIST", keys.topk_searches(), "WITHCOUNT"),
    )
    top_terms = [
        {"term": flat[i], "approx_count": int(flat[i + 1])} for i in range(0, len(flat), 2)
    ]

    # Ask the CMS about whichever terms we care about — it cannot enumerate its own contents,
    # so we default to the terms Top-K just told us about. The two structures complement.
    query_terms = terms or [t["term"] for t in top_terms]
    cms_counts: list[dict[str, Any]] = []
    if query_terms:
        raw = cast(
            list[int],
            await client.execute_command("CMS.QUERY", keys.cms_searches(), *query_terms),
        )
        cms_counts = [
            {"term": t, "approx_count": int(c)} for t, c in zip(query_terms, raw, strict=True)
        ]

    return {
        "day": day,
        "hyperloglog": {
            "unique_users": unique_users,
            "answers": "how many DISTINCT users searched",
            "memory": "~12 KB regardless of cardinality",
        },
        "count_min_sketch": {
            "counts": cms_counts,
            "answers": "how OFTEN a specific term was searched (never under-counts)",
        },
        "top_k": {
            "terms": top_terms,
            "answers": "WHICH terms are the heaviest hitters (the only one that enumerates)",
        },
    }


async def info(client: aioredis.Redis) -> dict[str, Any]:
    """Sizes, so you can see the memory claim rather than take it on faith."""
    out: dict[str, Any] = {}
    for label, key in (
        ("bloom_emails", keys.bloom_emails()),
        ("hll_visitors", keys.hll_visitors(today())),
        ("cms_searches", keys.cms_searches()),
        ("topk_searches", keys.topk_searches()),
    ):
        used = await client.execute_command("MEMORY", "USAGE", key)
        out[label] = {"bytes": int(used) if used else 0}
    return out
