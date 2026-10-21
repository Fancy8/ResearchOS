"""Redis-backed auth limits shared by API processes; no raw identity in keys."""

import hashlib
import hmac
from functools import lru_cache

from redis import Redis
from redis.exceptions import RedisError
from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.core.errors import DomainError

SCRIPT = """
local n = redis.call('INCR', KEYS[1])
if n == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
return n
"""


@lru_cache
def client():
    return Redis.from_url(get_settings().redis_url, socket_connect_timeout=2, socket_timeout=2)


def enforce(kind, identity, maximum, seconds):
    settings = get_settings()
    hashed = hmac.new(
        settings.control_secret.encode(), f"{kind}:{identity}".encode(), hashlib.sha256
    ).hexdigest()
    key = f"researchos:{settings.environment}:auth-limit:{hashed}"
    try:
        counter = client().eval(SCRIPT, 1, key, seconds)
    except RedisError:
        raise DomainError("AUTH_SERVICE_UNAVAILABLE", "身份验证服务暂不可用，请稍后重试", 503) from None
    if counter > maximum:
        raise DomainError("RATE_LIMITED", "尝试次数过多，请稍后重试", 429, {"retry_after_seconds": seconds})


async def auth_limit(kind, request, identity, maximum=8, seconds=900):
    address = request.client.host if request.client else "unknown"
    await run_in_threadpool(enforce, f"{kind}:client", address, 200, seconds)
    await run_in_threadpool(enforce, f"{kind}:identity", identity, maximum, seconds)
