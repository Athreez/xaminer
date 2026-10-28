"""UUIDv7 identifiers: unique, time-ordered (good index locality), and not guessable in URLs.

Python 3.12 has no uuid.uuid7(), so it is built here following RFC 9562:
48-bit Unix time in milliseconds, then the version and variant bits, then 74 random bits.

Lists show "newest first" by sorting on these ids, so within one process each id is greater than
the last even when several are made in the same millisecond (RFC 9562 § 6.2, method 2: the random
part of the previous id plus one).
"""

import secrets
import threading
import time
import uuid

_RANDOM_BITS = 74
_RANDOM_MAX = (1 << _RANDOM_BITS) - 1
_lock = threading.Lock()
_last_ms = 0
_last_random = 0


def _pack(unix_ms: int, random: int) -> uuid.UUID:
    rand_a, rand_b = random >> 62, random & ((1 << 62) - 1)  # 12 + 62 bits around the markers
    value = (unix_ms & ((1 << 48) - 1)) << 80 | 0x7 << 76 | rand_a << 64 | 0x2 << 62 | rand_b
    return uuid.UUID(int=value)


def uuid7() -> uuid.UUID:
    global _last_ms, _last_random
    with _lock:
        unix_ms = time.time_ns() // 1_000_000
        if unix_ms > _last_ms:
            random = int.from_bytes(secrets.token_bytes(10), "big") & _RANDOM_MAX
        else:  # same millisecond (or the clock stepped back): count on from the last id
            unix_ms = _last_ms
            random = _last_random + 1
            if random > _RANDOM_MAX:  # practically never: borrow the next millisecond
                unix_ms, random = unix_ms + 1, 0
        _last_ms, _last_random = unix_ms, random
        return _pack(unix_ms, random)
