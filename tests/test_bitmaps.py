"""Bitmaps: per-user flags, counting, and BITOP retention."""

from app.redis_ops import bitmaps


async def test_mark_and_check_one_user(redis_client):
    first = await bitmaps.mark_active(redis_client, "alice", "2026-08-04")
    second = await bitmaps.mark_active(redis_client, "alice", "2026-08-04")

    assert first["already_active"] is False
    assert second["already_active"] is True  # SETBIT returned the previous bit

    stats = await bitmaps.day_stats(redis_client, "2026-08-04", user_id="alice")
    assert stats["active_users"] == 1
    assert stats["was_active"] is True


async def test_offsets_are_stable_and_dense(redis_client):
    """Bitmaps need small dense integer ids, so the mapping must be stable per user."""
    a = await bitmaps.mark_active(redis_client, "alice", "2026-08-04")
    b = await bitmaps.mark_active(redis_client, "bob", "2026-08-04")
    a_again = await bitmaps.mark_active(redis_client, "alice", "2026-08-05")

    assert {a["bit_offset"], b["bit_offset"]} == {0, 1}
    assert a_again["bit_offset"] == a["bit_offset"]


async def test_three_users_fit_in_one_byte(redis_client):
    await bitmaps.seed_day(redis_client, "2026-08-04", ["alice", "bob", "carol"])
    stats = await bitmaps.day_stats(redis_client, "2026-08-04")

    assert stats["active_users"] == 3
    assert stats["bitmap_bytes"] == 1  # the memory claim, demonstrated


async def test_bitop_and_computes_retention(redis_client):
    await bitmaps.seed_day(redis_client, "2026-08-03", ["alice", "bob", "carol"])
    await bitmaps.seed_day(redis_client, "2026-08-04", ["alice", "bob"])

    result = await bitmaps.retention(redis_client, "2026-08-03", "2026-08-04")
    assert result["active_both_days"] == 2
    assert result["retention_pct"] == 66.67


async def test_scratch_key_does_not_leak(redis_client):
    await bitmaps.seed_day(redis_client, "2026-08-03", ["alice"])
    await bitmaps.seed_day(redis_client, "2026-08-04", ["alice"])
    await bitmaps.retention(redis_client, "2026-08-03", "2026-08-04")

    assert await redis_client.keys("*scratch*") == []


async def test_unknown_user_reads_as_inactive(redis_client):
    stats = await bitmaps.day_stats(redis_client, "2026-08-04", user_id="ghost")
    assert stats["was_active"] is False
