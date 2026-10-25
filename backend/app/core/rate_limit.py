"""Rate limits shared by every API process, kept in Redis (SECURITY_AND_ACCESS.md § 5.3)."""

from redis.asyncio import Redis


async def allow(redis: Redis, key: str, limit: int, window_seconds: int) -> bool:
    """Count one hit for `key`. True while at most `limit` hits happened in the current window.

    A fixed window: simple, and good enough for limits like "3 password resets per hour".
    """
    full_key = f"ratelimit:{key}"
    async with redis.pipeline(transaction=True) as pipe:
        pipe.incr(full_key)
        pipe.expire(full_key, window_seconds, nx=True)  # the first hit starts the window
        count, _ = await pipe.execute()
    return int(count) <= limit
