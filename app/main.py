"""Redis Data Types Playground — FastAPI app.

Every route group maps to exactly one Redis data type. The Redis knowledge lives in
app/redis_ops/*.py; this layer only parses, calls and serialises.
"""

import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from app.api.routes import (
    bitfields,
    bitmaps,
    geo,
    hashes,
    jsondoc,
    lists,
    meta,
    probabilistic,
    sets,
    sortedsets,
    streams,
    strings,
    timeseries,
    vectors,
)
from app.core import keys
from app.core.client import (
    REQUIRED_MODULES,
    bootstrap,
    connect,
    disconnect,
    get_redis,
    module_names,
)
from app.core.logging import configure_logging, get_logger
from app.redis_ops import timeseries as ts_ops

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    client = await connect()

    loaded = await module_names(client)
    missing = [name for key, name in REQUIRED_MODULES.items() if key not in loaded]
    if missing:
        # Fail loudly here rather than with a cryptic "unknown command" on first request.
        log.error("redis.modules.missing", missing=missing, loaded=sorted(loaded))
        raise RuntimeError(
            f"Redis is missing {missing}. Use redis:8-alpine — redis:7 has none of these."
        )

    await bootstrap(client)
    log.info("app.started", types=13)
    yield
    await disconnect()


app = FastAPI(
    title="Redis Data Types Playground",
    version="0.1.0",
    summary="Every Redis data type, one real use case each.",
    description=(
        "Each tag below is one Redis data type. Start with **GET /demo/scenario** to see all "
        "thirteen work together, then read `app/redis_ops/<type>.py` for why each was chosen."
    ),
    lifespan=lifespan,
)


@app.middleware("http")
async def record_latency(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Record every request's latency into a Redis time series.

    This is why GET /timeseries/http-latency returns real data with nothing seeded. Metrics
    recording must never break the request it measures, so failures here are logged and
    swallowed deliberately — the one place a bare except is the right call.
    """
    started = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - started) * 1000

    try:
        await ts_ops.record(get_redis(), keys.HTTP_LATENCY_METRIC, round(elapsed_ms, 3))
    except Exception as exc:
        log.warning("metrics.record_failed", error=str(exc), path=request.url.path)

    response.headers["X-Response-Time-ms"] = f"{elapsed_ms:.2f}"
    return response


@app.exception_handler(ValueError)
async def value_error_handler(_: Request, exc: ValueError) -> JSONResponse:
    """Domain errors become HTTP errors at the app edge, not inside the ops modules."""
    return JSONResponse(status_code=422, content={"detail": str(exc)})


for router in (
    meta.router,
    strings.router,
    hashes.router,
    jsondoc.router,
    lists.router,
    sets.router,
    sortedsets.router,
    bitmaps.router,
    bitfields.router,
    geo.router,
    streams.router,
    probabilistic.router,
    timeseries.router,
    vectors.router,
):
    app.include_router(router)
