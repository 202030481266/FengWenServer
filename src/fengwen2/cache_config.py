import os
import hashlib
import json
from typing import Optional
from fastapi_cache import FastAPICache
from fastapi_cache.backends.redis import RedisBackend
from fastapi_cache.decorator import cache
import redis.asyncio as redis
import logging

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
CACHE_TTL = int(os.getenv("CACHE_TTL", 3600))  # 1 hour default


async def init_cache():
    """Initialize Redis cache connection"""
    redis_client = redis.from_url(REDIS_URL, encoding="utf8", decode_responses=True)
    FastAPICache.init(RedisBackend(redis_client), prefix="astrology-cache:")
    

def generate_cache_key(prefix: str, **kwargs) -> str:
    """Generate a consistent cache key from request parameters"""
    # Sort kwargs to ensure consistent key generation
    sorted_params = sorted(kwargs.items())
    key_data = json.dumps(sorted_params, sort_keys=True, default=str)
    hash_digest = hashlib.md5(key_data.encode()).hexdigest()
    return f"{prefix}:{hash_digest}"


def astrology_cache_key_builder(
    func,
    namespace: Optional[str] = "",
    request = None,
    response = None,
    args = None,
    kwargs = None,
):
    """Custom cache key builder for astrology endpoints"""
    # Extract the UserInfoRequest from kwargs
    user_info = kwargs.get("user_info")
    if user_info:
        return generate_cache_key(
            "astrology:calculate",
            email=user_info.email,
            name=user_info.name,
            birth_date=user_info.birth_date,
            birth_time=user_info.birth_time,
            gender=user_info.gender
        )
    return None


class CacheManager:
    """Helper class for cache management"""
    
    @staticmethod
    async def invalidate_user_cache(email: str):
        """Invalidate all cached data for a specific user"""
        try:
            backend = FastAPICache.get_backend()
            # Pattern match all keys for this email
            pattern = f"astrology-cache:astrology:calculate:*{email}*"
            async for key in backend.client.scan_iter(match=pattern):
                await backend.client.delete(key)
            logger.info(f"Cache invalidated for email: {email}")
        except Exception as e:
            logger.error(f"Error invalidating cache: {e}")
    
    @staticmethod
    async def clear_all_cache():
        """Clear all astrology cache (use with caution)"""
        try:
            backend = FastAPICache.get_backend()
            async for key in backend.client.scan_iter(match="astrology-cache:*"):
                await backend.client.delete(key)
            logger.info("All astrology cache cleared")
        except Exception as e:
            logger.error(f"Error clearing cache: {e}")