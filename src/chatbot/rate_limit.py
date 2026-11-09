import hashlib
import math
import os
import time

import redis


_redis_client = None
_LIMIT = 10
_WINDOW_SECONDS = 60
_INCREMENT_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return count
"""


class RateLimitUnavailable(Exception):
    pass


def _client():
    global _redis_client
    if _redis_client is None:
        url = os.getenv("CHAT_REDIS_URL") or os.getenv(
            "REDIS_URL", "redis://redis:6379/2"
        )
        _redis_client = redis.Redis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=1,
        )
    return _redis_client


def check_request_limit(identity):
    now = time.time()
    window = int(now // _WINDOW_SECONDS)
    identity_digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    key = f"chat:v1:rate:{identity_digest}:{window}"
    try:
        count = int(_client().eval(_INCREMENT_SCRIPT, 1, key, 65))
    except Exception:
        raise RateLimitUnavailable from None
    if count <= _LIMIT:
        return None
    seconds_remaining = ((window + 1) * _WINDOW_SECONDS) - now
    return max(1, math.ceil(seconds_remaining))
