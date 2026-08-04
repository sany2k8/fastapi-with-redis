"""Time series: retention, duplicate policy and server-side aggregation."""

import pytest

from app.redis_ops import timeseries


@pytest.fixture(autouse=True)
async def _requires_ts(module_check):
    await module_check("timeseries")


async def test_record_and_range(redis_client):
    now = timeseries.now_ms()
    for i, value in enumerate([10.0, 20.0, 30.0]):
        await timeseries.record(redis_client, "test_metric", value, now + i)

    result = await timeseries.range_query(redis_client, "test_metric")
    assert [point["value"] for point in result["points"]] == [10.0, 20.0, 30.0]


async def test_aggregation_downsamples_server_side(redis_client):
    """60 raw samples become 1 bucket — the arithmetic happens in Redis, not here."""
    now = timeseries.now_ms()
    for i in range(60):
        await timeseries.record(redis_client, "test_metric", float(i), now + i * 100)

    raw = await timeseries.range_query(redis_client, "test_metric")
    bucketed = await timeseries.range_query(
        redis_client, "test_metric", bucket_ms=60_000, aggregation="avg"
    )

    assert raw["count"] == 60
    assert bucketed["count"] < raw["count"]
    assert bucketed["points"][0]["value"] == pytest.approx(29.5, abs=1.0)


async def test_duplicate_timestamp_does_not_error(redis_client):
    """DUPLICATE_POLICY LAST is what stops two same-millisecond writes from raising."""
    now = timeseries.now_ms()
    await timeseries.record(redis_client, "test_metric", 1.0, now)
    await timeseries.record(redis_client, "test_metric", 2.0, now)

    result = await timeseries.range_query(redis_client, "test_metric")
    assert result["points"] == [{"timestamp_ms": now, "value": 2.0}]


async def test_ensure_series_is_idempotent(redis_client):
    assert await timeseries.ensure_series(redis_client, "test_metric") is True
    assert await timeseries.ensure_series(redis_client, "test_metric") is False


async def test_mrange_finds_series_by_label(redis_client):
    """You never have to know the series names — that is what labels are for."""
    await timeseries.record(redis_client, "a_metric", 1.0, labels={"kind": "demo"})
    await timeseries.record(redis_client, "b_metric", 2.0, labels={"kind": "demo"})
    await timeseries.record(redis_client, "c_metric", 3.0, labels={"kind": "other"})

    series = await timeseries.multi_range(redis_client, "kind", "demo")
    assert len(series) == 2


async def test_missing_series_returns_empty_not_error(redis_client):
    assert (await timeseries.range_query(redis_client, "never_created"))["count"] == 0
