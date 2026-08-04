"""BITFIELDS — a whole user state record in 4 bytes.

WHAT IT IS
    BITFIELD treats a String as an array of arbitrary-width integers. You declare the width
    and the bit offset; Redis handles the packing.

THE PROBLEM IT SOLVES HERE
    Gamification state: level (0-255), daily streak (0-255), xp (0-65535). Three numbers that
    are always read together and are far smaller than an int64.

THE LAYOUT (this comment is the schema — there is nowhere else to put it)
    bits  0..7   u8   level
    bits  8..15  u8   streak
    bits 16..31  u16  xp
    Total: 4 bytes per user. The same record as a Hash costs ~100 bytes of key, field-name
    and pointer overhead. At 50 million devices that is 200 MB versus 5 GB.

HOW REDIS STORES IT
    It is just a String. Multiple sub-commands in one BITFIELD call are applied atomically in
    order, so you can read and update several fields in a single round trip with no race.

OVERFLOW IS THE INTERESTING PART
    The default policy is WRAP: u8 255 + 1 silently becomes 0, and your user's level resets.
    OVERFLOW SAT clamps at the maximum instead; OVERFLOW FAIL returns nil so you can react.
    Choosing this deliberately is the whole skill of using bitfields.

WHY NOT ANOTHER TYPE
    vs HASH: a Hash is the right default — readable, self-describing, individually updatable.
      Bitfields win only when the count of records is huge and the values are genuinely small.
      You pay for the memory with an opaque, undocumented-by-default layout.
    vs STRING per field: three keys, three round trips, three lots of key overhead.

LIMITATIONS
    Self-describing in no way whatsoever — change the layout and every stored record silently
    becomes garbage. There is no migration path except a rewrite. Do not reach for this until
    memory is measurably the problem.
"""

from typing import Any, cast

import redis.asyncio as aioredis

from app.core import keys

# Layout: (name, type-spec, bit offset). Change this and old data becomes meaningless.
LAYOUT: tuple[tuple[str, str, int], ...] = (
    ("level", "u8", 0),
    ("streak", "u8", 8),
    ("xp", "u16", 16),
)
_MAX = {"u8": 255, "u16": 65535}


async def set_state(client: aioredis.Redis, user_id: str, values: dict[str, int]) -> dict[str, Any]:
    """One BITFIELD call sets every field atomically."""
    args: list[Any] = []
    for name, spec, offset in LAYOUT:
        if name in values:
            value = values[name]
            if not 0 <= value <= _MAX[spec]:
                raise ValueError(f"{name} must be within 0..{_MAX[spec]} for {spec}, got {value}")
            args += ["SET", spec, offset, value]

    if not args:
        raise ValueError("no known fields supplied")

    await client.execute_command("BITFIELD", keys.state(user_id), *args)
    return await get_state(client, user_id)


async def get_state(client: aioredis.Redis, user_id: str) -> dict[str, Any]:
    """Three GETs in one command. A key that was never written reads as all zeros."""
    args: list[Any] = []
    for _, spec, offset in LAYOUT:
        args += ["GET", spec, offset]

    raw = cast(list[int], await client.execute_command("BITFIELD", keys.state(user_id), *args))
    size = await client.strlen(keys.state(user_id))

    state = {name: int(value) for (name, _, _), value in zip(LAYOUT, raw, strict=True)}
    return {"user_id": user_id, **state, "stored_bytes": size}


async def add_xp(client: aioredis.Redis, user_id: str, amount: int) -> dict[str, Any]:
    """OVERFLOW SAT INCRBY — clamp at 65535 instead of wrapping to 0.

    Without the explicit OVERFLOW, a player at 65530 xp who earns 10 ends up at 4.
    The policy applies to the sub-commands that follow it within this call only.
    """
    result = cast(
        list[int],
        await client.execute_command(
            "BITFIELD", keys.state(user_id), "OVERFLOW", "SAT", "INCRBY", "u16", 16, amount
        ),
    )
    new_xp = int(result[0])
    return {
        "user_id": user_id,
        "xp": new_xp,
        "saturated": new_xp == _MAX["u16"],
    }
