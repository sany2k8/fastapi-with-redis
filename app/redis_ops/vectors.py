"""VECTOR SETS — find similar users.

WHAT IT IS
    Redis 8's native vector similarity structure (built in, not a loadable module: it shows
    up in MODULE LIST as `vectorset` with an empty path). Conceptually a Sorted Set where the
    "score" is a high-dimensional vector and the ordering is by distance to a query vector.

THE PROBLEM IT SOLVES HERE
    "Show me users like this one." Nothing has to match exactly — two users who both like
    {redis, databases, python} should rank above one who likes {cooking}, without anyone
    writing a rule that says so.

HOW REDIS STORES IT
    An HNSW graph (hierarchical navigable small world). Search walks the graph rather than
    comparing against every vector, so it is approximate-nearest-neighbour: sub-linear, with
    a small chance of missing a true neighbour. Vectors are quantised to int8 by default,
    which cuts memory ~4x for a negligible recall cost.

ABOUT THE EMBEDDINGS HERE
    No ML model. Each interest tag is hashed to a deterministic 8-dimensional vector and the
    tags are averaged, then L2-normalised. Shared tags therefore produce nearby vectors — the
    same *shape* as real embeddings, with none of the setup. In production this is exactly
    where a sentence-transformer or an embeddings API output would go instead; the Redis
    calls do not change.

WHY NOT ANOTHER TYPE
    vs SET intersection on interests (see sets.py): that answers "who shares a tag", which is
      exact and boolean. It cannot rank by degree of similarity, and it finds nothing at all
      for a user whose tags are related-but-not-identical ({postgres} vs {databases}). Vector
      similarity is a distance, not a filter — that is the entire difference.
    vs SORTED SET: one dimension only. Similarity here is 8-dimensional.
    vs a dedicated vector DB: when you need billions of vectors, hybrid filtering and its own
      operational story. For "some vectors next to the data I already keep in Redis", this is
      far less machinery.

LIMITATIONS
    Approximate: recall is tunable (EF) but never guaranteed. Adding is more expensive than a
    plain write because the graph must be updated. Deleting is supported (VREM) but heavy
    churn degrades the graph. And the quality of results is entirely the quality of your
    embeddings — Redis cannot rescue a bad vector.
"""

import hashlib
import math
from typing import Any, cast

import redis.asyncio as aioredis
from redis.exceptions import ResponseError

from app.core import keys

DIM = 32


def embed(tags: list[str]) -> list[float]:
    """Deterministic stand-in for an embedding model, using the feature-hashing trick.

    Each tag is hashed to ONE dimension (plus a sign), so distinct tags land on near-orthogonal
    axes and shared tags add up on the same axis. Cosine similarity then tracks tag overlap
    directly: 3-of-3 shared tags ≈ 1.0, 2-of-3 ≈ 0.67, nothing shared ≈ 0.

    An earlier version spread every tag across all DIM components. It was deterministic and
    it technically ranked correctly, but every pair scored ~0.79 — the shared-tag pair beat
    the unrelated one by 0.002, which demonstrates nothing. Feature hashing keeps the vectors
    sparse, and sparsity is what makes the similarities legible.

    DIM=32 keeps hash collisions rare for a demo-sized tag vocabulary. A real model would
    produce dense vectors of 384-1536 dimensions; only `embed` would change, not the Redis calls.
    """
    if not tags:
        return [0.0] * DIM

    acc = [0.0] * DIM
    for tag in tags:
        digest = hashlib.sha256(tag.strip().lower().encode()).digest()
        index = int.from_bytes(digest[:4], "big") % DIM
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        acc[index] += sign

    magnitude = math.sqrt(sum(component * component for component in acc))
    if magnitude == 0:
        return [0.0] * DIM
    return [round(component / magnitude, 6) for component in acc]


async def upsert(client: aioredis.Redis, user_id: str, tags: list[str]) -> dict[str, Any]:
    """VADD key VALUES <dim> <v1..vn> <element>.

    VALUES takes plain floats; the FP32 form takes a packed binary blob and is what you would
    use with a real model. Re-adding the same element replaces its vector.
    """
    vector = embed(tags)
    await client.execute_command("VADD", keys.vector_users(), "VALUES", DIM, *vector, user_id)
    return {"user_id": user_id, "tags": tags, "vector": vector, "dimensions": DIM}


async def similar(client: aioredis.Redis, user_id: str, k: int = 5) -> dict[str, Any]:
    """VSIM ... ELE <element> WITHSCORES — nearest neighbours of an element already stored.

    The element itself always comes back first with a perfect score, so we ask for k+1 and
    drop it.

    READ THE SCORES CAREFULLY: VSIM maps cosine similarity onto [0, 1] as (1 + cos) / 2.
    So 1.0 is identical, **0.5 is orthogonal — no relationship at all** — and 0.0 is exactly
    opposite. A user sharing no tags scores 0.5, not 0. Treating 0.5 as "half similar" is the
    easiest mistake to make here.
    """
    try:
        raw = await client.execute_command(
            "VSIM", keys.vector_users(), "ELE", user_id, "WITHSCORES", "COUNT", k + 1
        )
    except ResponseError as exc:
        if "not found" in str(exc).lower():
            return {"user_id": user_id, "neighbours": [], "note": "user has no stored vector"}
        raise

    neighbours = [row for row in _pairs(raw) if row["user_id"] != user_id]
    return {"user_id": user_id, "neighbours": neighbours[:k], "count": len(neighbours[:k])}


def _pairs(raw: Any) -> list[dict[str, Any]]:
    """Normalise a VSIM … WITHSCORES reply.

    GOTCHA: the raw protocol returns a flat [member, score, member, score, …], but redis-py's
    response callback turns it into a {member: score} dict. Which one you get depends on the
    client version, so handle both — and note that a dict loses nothing here because VSIM
    already returns results in descending similarity order... except that Python dicts preserve
    insertion order, so the ranking survives.
    """
    if isinstance(raw, dict):
        rows = [
            {"user_id": member, "similarity": round(float(score), 4)}
            for member, score in raw.items()
        ]
        return sorted(rows, key=lambda row: row["similarity"], reverse=True)
    return [
        {"user_id": raw[i], "similarity": round(float(raw[i + 1]), 4)}
        for i in range(0, len(raw), 2)
    ]


async def search_by_tags(client: aioredis.Redis, tags: list[str], k: int = 5) -> dict[str, Any]:
    """VSIM with a raw query vector — "who is like *this taste*", for a user who does not exist.

    This is the semantic-search shape: embed the query, search the same index.
    """
    vector = embed(tags)
    raw = await client.execute_command(
        "VSIM", keys.vector_users(), "VALUES", DIM, *vector, "WITHSCORES", "COUNT", k
    )
    return {"query_tags": tags, "matches": _pairs(raw)}


async def info(client: aioredis.Redis) -> dict[str, Any]:
    try:
        card = cast(int, await client.execute_command("VCARD", keys.vector_users()))
        dim = cast(int, await client.execute_command("VDIM", keys.vector_users()))
    except ResponseError:
        return {"members": 0, "dimensions": DIM}
    return {"members": int(card), "dimensions": int(dim)}
