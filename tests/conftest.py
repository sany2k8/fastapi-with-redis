"""Test fixtures.

These tests run against a REAL Redis 8 (db 15, flushed per test). That is deliberate:
fakeredis cannot emulate JSON, Bloom, Time Series or vector sets, and mocking the client
would only assert that we call the functions we call — it would test nothing about Redis.
"""

import os

# Must be set before app.core.config is imported anywhere: env vars win over .env.
os.environ["REDIS_DB"] = "15"
os.environ.setdefault("REDIS_HOST", "localhost")
os.environ.setdefault("REDIS_PORT", "6382")
os.environ["APP_ENV"] = "test"

from collections.abc import AsyncIterator

import pytest
import redis.asyncio as aioredis

from app.core.client import bootstrap
from app.core.config import get_settings

get_settings.cache_clear()


@pytest.fixture
async def redis_client() -> AsyncIterator[aioredis.Redis]:
    settings = get_settings()
    client: aioredis.Redis = aioredis.from_url(settings.redis_url, decode_responses=True)

    try:
        await client.ping()
    except Exception as exc:  # pragma: no cover - environment problem, not a test failure
        await client.aclose()
        pytest.skip(f"Redis unavailable at {settings.redis_url}: {exc}")

    assert settings.redis_db == 15, "tests must never run against a real database"
    await client.flushdb()
    await bootstrap(client)  # CMS and Top-K must exist before first write

    yield client

    await client.flushdb()
    await client.aclose()


@pytest.fixture
def module_check(redis_client: aioredis.Redis):  # type: ignore[no-untyped-def]
    """Skip with a clear message when a module is absent, rather than failing cryptically."""

    async def _check(module: str) -> None:
        modules = await redis_client.execute_command("MODULE", "LIST")
        names = {str(m.get("name", "")).lower() for m in modules}
        if module not in names:
            pytest.skip(f"Redis module {module!r} not loaded — use redis:8-alpine")

    return _check
