"""Every Redis key pattern in the project, as functions.

A naming convention written only in a README drifts within a week. Here it is executable:
if you want to know what this app writes, this file is the exhaustive answer, and
`POST /demo/reset` can clean up because everything starts with the same prefix.

Convention: {prefix}:{domain}:{id}[:{sub}]
"""

from app.core.config import get_settings


def _p() -> str:
    return get_settings().key_prefix


# --- Strings -------------------------------------------------------------------
def session(user_id: str) -> str:
    return f"{_p()}:session:{user_id}"


def session_last_seen(user_id: str) -> str:
    return f"{_p()}:session:{user_id}:last_seen"


def post_views(post_id: str) -> str:
    return f"{_p()}:post:{post_id}:views"


# --- Hash ----------------------------------------------------------------------
def user(user_id: str) -> str:
    return f"{_p()}:user:{user_id}"


# --- JSON ----------------------------------------------------------------------
def profile(user_id: str) -> str:
    return f"{_p()}:profile:{user_id}"


# --- List ----------------------------------------------------------------------
def notifications(user_id: str) -> str:
    return f"{_p()}:notifications:{user_id}"


# --- Sets ----------------------------------------------------------------------
def following(user_id: str) -> str:
    return f"{_p()}:following:{user_id}"


def followers(user_id: str) -> str:
    return f"{_p()}:followers:{user_id}"


# --- Sorted set ----------------------------------------------------------------
def leaderboard() -> str:
    return f"{_p()}:leaderboard:global"


# --- Bitmap --------------------------------------------------------------------
def activity(day: str) -> str:
    """day is an ISO date, e.g. 2026-08-04 — one bitmap per day."""
    return f"{_p()}:activity:{day}"


def activity_scratch(name: str) -> str:
    """Destination key for BITOP results. Ephemeral, deleted after reading."""
    return f"{_p()}:activity:scratch:{name}"


def bit_index() -> str:
    """user_id -> dense integer offset. Bitmaps need small, dense integer ids."""
    return f"{_p()}:bitindex"


def bit_index_seq() -> str:
    return f"{_p()}:bitindex:seq"


# --- Bitfield ------------------------------------------------------------------
def state(user_id: str) -> str:
    return f"{_p()}:state:{user_id}"


# --- Geo -----------------------------------------------------------------------
def geo_users() -> str:
    return f"{_p()}:geo:users"


# --- Stream --------------------------------------------------------------------
def events() -> str:
    return f"{_p()}:stream:events"


# --- Probabilistic -------------------------------------------------------------
def bloom_emails() -> str:
    return f"{_p()}:bloom:emails"


def hll_visitors(day: str) -> str:
    return f"{_p()}:hll:visitors:{day}"


def cms_searches() -> str:
    return f"{_p()}:cms:searches"


def topk_searches() -> str:
    return f"{_p()}:topk:searches"


# --- Time series ---------------------------------------------------------------
def metric(name: str) -> str:
    return f"{_p()}:metric:{name}"


HTTP_LATENCY_METRIC = "http_latency_ms"


# --- Vector set ----------------------------------------------------------------
def vector_users() -> str:
    return f"{_p()}:vectors:users"


def scan_pattern() -> str:
    return f"{_p()}:*"
