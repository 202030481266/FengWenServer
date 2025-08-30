import os
import hashlib
import json
from fastapi_cache import FastAPICache
from fastapi_cache.backends.redis import RedisBackend
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


class CacheManager:
    """Helper class for cache management"""
    
    @staticmethod
    def generate_astrology_cache_key(user_info) -> str:
        """Generate cache key for astrology calculation"""
        return generate_cache_key(
            "astrology:calculate",
            email=user_info.email,
            name=user_info.name,
            birth_date=user_info.birth_date,
            birth_time=user_info.birth_time,
            gender=user_info.gender
        )
    
    @staticmethod
    async def get_cached_result(cache_key: str):
        """Get cached result by key"""
        try:
            backend = FastAPICache.get_backend()
            full_key = f"astrology-cache:{cache_key}"
            cached_data = await backend.redis.get(full_key)
            if cached_data:
                logger.info(f"Cache hit for key: {cache_key}")
                return json.loads(cached_data)
            else:
                logger.info(f"Cache miss for key: {cache_key}")
                return None
        except Exception as e:
            logger.error(f"Error getting cached result: {e}")
            return None
    
    @staticmethod
    async def set_cached_result(cache_key: str, result: dict, ttl: int):
        """Cache result with TTL"""
        try:
            backend = FastAPICache.get_backend()
            full_key = f"astrology-cache:{cache_key}"
            await backend.redis.setex(full_key, ttl, json.dumps(result, default=str))
            logger.info(f"Result cached with TTL {ttl}s for key: {cache_key}")
        except Exception as e:
            logger.error(f"Error setting cached result: {e}")
    
    @staticmethod
    async def invalidate_user_cache(email: str):
        """Invalidate all cached data for a specific user"""
        try:
            backend = FastAPICache.get_backend()
            # Pattern match all keys for this email
            pattern = f"astrology-cache:astrology:calculate:*{email}*"
            async for key in backend.redis.scan_iter(match=pattern):
                await backend.redis.delete(key)
            logger.info(f"Cache invalidated for email: {email}")
        except Exception as e:
            logger.error(f"Error invalidating cache: {e}")
    
    @staticmethod
    async def clear_all_cache():
        """Clear all astrology cache (use with caution)"""
        try:
            backend = FastAPICache.get_backend()
            async for key in backend.redis.scan_iter(match="astrology-cache:*"):
                await backend.redis.delete(key)
            logger.info("All astrology cache cleared")
        except Exception as e:
            logger.error(f"Error clearing cache: {e}")