"""Redis client and in-memory fallback cache manager."""

import logging
from typing import Optional, Any, Tuple
import json

from ticketnotify.config import settings

logger = logging.getLogger(__name__)

_redis_client: Any = None
_is_using_fakeredis: bool = False


async def get_redis_client() -> Any:
    """Returns an active Redis client or in-memory fakeredis client as fallback."""
    global _redis_client, _is_using_fakeredis
    if _redis_client is not None:
        return _redis_client

    # First attempt: Try connecting to real Redis
    try:
        import redis.asyncio as aioredis
        client = aioredis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=2.0,
            socket_timeout=2.0,
        )
        await client.ping()
        _redis_client = client
        _is_using_fakeredis = False
        logger.info(f"Connected to Redis server at {settings.REDIS_URL}")
        return _redis_client
    except Exception as e:
        logger.warning(f"Could not connect to Redis at {settings.REDIS_URL}: {e}")

    # Second attempt: Fallback to fakeredis if enabled
    if settings.USE_IN_MEMORY_REDIS_FALLBACK:
        try:
            import fakeredis.aioredis as fake_aioredis
            _redis_client = fake_aioredis.FakeRedis(decode_responses=True)
            _is_using_fakeredis = True
            logger.info("Using in-memory fakeredis fallback for caching.")
            return _redis_client
        except Exception as fe:
            logger.error(f"Failed to initialize fakeredis: {fe}")

    return None


async def check_redis_health() -> Tuple[bool, str]:
    """Checks Redis health and returns (is_healthy, description)."""
    try:
        client = await get_redis_client()
        if client is None:
            return False, "disconnected"
        await client.ping()
        mode = "in-memory fallback (fakeredis)" if _is_using_fakeredis else "connected (Redis)"
        return True, mode
    except Exception as e:
        return False, f"error: {str(e)}"


async def cache_get(key: str) -> Optional[str]:
    """Retrieve string or JSON from cache."""
    try:
        client = await get_redis_client()
        if client:
            return await client.get(key)
    except Exception as e:
        logger.debug(f"Redis cache_get failed for {key}: {e}")
    return None


async def cache_set(key: str, value: str, ttl_seconds: Optional[int] = None) -> bool:
    """Store string or JSON in cache with optional TTL."""
    try:
        client = await get_redis_client()
        if client:
            if ttl_seconds:
                await client.set(key, value, ex=ttl_seconds)
            else:
                await client.set(key, value)
            return True
    except Exception as e:
        logger.debug(f"Redis cache_set failed for {key}: {e}")
    return False


async def cache_delete(key: str) -> bool:
    """Delete a key from cache."""
    try:
        client = await get_redis_client()
        if client:
            await client.delete(key)
            return True
    except Exception as e:
        logger.debug(f"Redis cache_delete failed for {key}: {e}")
    return False
