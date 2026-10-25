"""Rate limits shared by every API process, kept in Redis (SECURITY_AND_ACCESS.md § 5.3)."""

from dataclasses import dataclass

from redis.asyncio import Redis

from app.core.errors import AppError


@dataclass(frozen=True)
class Limit:
    allowed: bool
    retry_after: int  # seconds until the window resets (0 when allowed)


async def hit(redis: Redis, key: str, limit: int, window_seconds: int) -> Limit:
    """Count one hit for `key`; allowed while at most `limit` hits happened in the current window.

    A fixed window: simple, and good enough for limits like "10 logins a minute".
    """
    full_key = f"ratelimit:{key}"
    async with redis.pipeline(transaction=True) as pipe:
        pipe.incr(full_key)
        pipe.expire(full_key, window_seconds, nx=True)  # the first hit starts the window
        pipe.ttl(full_key)
        count, _, ttl = await pipe.execute()
    if int(count) <= limit:
        return Limit(allowed=True, retry_after=0)
    return Limit(allowed=False, retry_after=max(int(ttl), 1))


def rate_limited(retry_after: int) -> AppError:
    """The 429 answer. It always says how long to wait (`Retry-After`, in seconds)."""
    return AppError(
        "RATE_LIMITED",
        f"Too many requests. Try again in {retry_after} seconds.",
        status_code=429,
        headers={"Retry-After": str(retry_after)},
    )
