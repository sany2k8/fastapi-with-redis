"""Bitfields: packing, unpacking and the overflow policy."""

import pytest

from app.redis_ops import bitfields


async def test_pack_and_unpack(redis_client):
    await bitfields.set_state(redis_client, "alice", {"level": 7, "streak": 12, "xp": 3400})
    state = await bitfields.get_state(redis_client, "alice")

    assert state["level"] == 7
    assert state["streak"] == 12
    assert state["xp"] == 3400


async def test_the_whole_record_is_four_bytes(redis_client):
    await bitfields.set_state(redis_client, "alice", {"level": 255, "streak": 255, "xp": 65_535})

    assert (await bitfields.get_state(redis_client, "alice"))["stored_bytes"] == 4


async def test_unwritten_state_reads_as_zeros(redis_client):
    state = await bitfields.get_state(redis_client, "nobody")
    assert (state["level"], state["streak"], state["xp"]) == (0, 0, 0)


async def test_overflow_saturates_instead_of_wrapping(redis_client):
    """The default WRAP policy would turn 65530 + 100 into 64. SAT clamps at the maximum."""
    await bitfields.set_state(redis_client, "alice", {"xp": 65_530})
    result = await bitfields.add_xp(redis_client, "alice", 100)

    assert result["xp"] == 65_535
    assert result["saturated"] is True


async def test_fields_are_independent(redis_client):
    """Writing xp must not disturb the neighbouring bits."""
    await bitfields.set_state(redis_client, "alice", {"level": 9, "streak": 3, "xp": 100})
    await bitfields.add_xp(redis_client, "alice", 50)

    state = await bitfields.get_state(redis_client, "alice")
    assert (state["level"], state["streak"], state["xp"]) == (9, 3, 150)


async def test_out_of_range_value_is_rejected(redis_client):
    with pytest.raises(ValueError, match="level"):
        await bitfields.set_state(redis_client, "alice", {"level": 300})
