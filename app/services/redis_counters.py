"""
Live per-job sent/failed counters in Redis, per ARCHITECTURE.md — read by
the SSE status endpoint for low-latency updates while a job is running.

DATABASE_SCHEMA.md is explicit that jobs.sent_count/failed_count are the
durable source of truth "once the job finishes or if Redis is unavailable"
— so every function here is designed to fail fast and let the caller fall
back to the DB rather than block a request. See app/tasks/__init__.py for
why "fail fast" needs deliberate timeout config with this Redis client,
not just try/except.
"""
import redis
from redis.backoff import NoBackoff
from redis.retry import Retry
from flask import current_app

_SOCKET_TIMEOUT = 1.5


def _client():
    return redis.Redis.from_url(
        current_app.config["REDIS_URL"],
        socket_connect_timeout=_SOCKET_TIMEOUT,
        socket_timeout=_SOCKET_TIMEOUT,
        # redis-py retries certain errors (e.g. ConnectionError on initial
        # connect) by default even with retry_on_timeout=False — each
        # retry re-pays the full socket_connect_timeout. Disable retries
        # entirely so a down Redis fails once, fast, per call.
        retry=Retry(NoBackoff(), 0),
        retry_on_timeout=False,
        retry_on_error=[],
    )


def _key(job_id, field):
    return f"job:{job_id}:{field}"


def increment(job_id, field, amount=1):
    """Best-effort — never raises. Failures just mean the SSE endpoint falls back to the DB."""
    try:
        _client().incrby(_key(job_id, field), amount)
    except Exception:
        pass


def read_counters(job_id):
    """Returns {"sent": int, "failed": int} or None if Redis is unreachable / has no data."""
    try:
        client = _client()
        sent = client.get(_key(job_id, "sent"))
        failed = client.get(_key(job_id, "failed"))
        if sent is None and failed is None:
            return None
        return {"sent": int(sent or 0), "failed": int(failed or 0)}
    except Exception:
        return None
