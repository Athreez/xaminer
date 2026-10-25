"""UUIDv7 identifiers: unique, time-ordered (good index locality), and not guessable in URLs.

Python 3.12 has no uuid.uuid7(), so it is built here following RFC 9562:
48-bit Unix time in milliseconds, then the version and variant bits, then 74 random bits.
"""

import secrets
import time
import uuid


def uuid7() -> uuid.UUID:
    unix_ms = time.time_ns() // 1_000_000
    value = (unix_ms & ((1 << 48) - 1)) << 80 | int.from_bytes(secrets.token_bytes(10), "big")
    value = (value & ~(0xF << 76)) | (0x7 << 76)  # version 7
    value = (value & ~(0x3 << 62)) | (0x2 << 62)  # RFC 9562 variant
    return uuid.UUID(int=value)
