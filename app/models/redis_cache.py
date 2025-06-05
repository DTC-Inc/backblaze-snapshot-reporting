"""
Redis cache utility for expensive dashboard queries
"""

import redis
import json
import hashlib
import logging
from datetime import datetime, timedelta
from typing import Any, Optional, Callable
import os

logger = logging.getLogger(__name__)

class RedisCache:
    def __init__(self, redis_url: str = None, default_ttl: int = 300):
        """
        Initialize Redis cache
        
        Args:
            redis_url: Redis connection URL
            default_ttl: Default time-to-live in seconds (5 minutes)
        """
        self.redis_url = redis_url or os.getenv('REDIS_URL', 'redis://bbssr_redis:6379/2')
        self.default_ttl = default_ttl
        self.redis_client = None
        
        # Try to connect to Redis
        try:
            self.redis_client = redis.from_url(self.redis_url)
            self.redis_client.ping()  # Test connection
            logger.info(f"Redis cache initialized successfully: {self.redis_url}")
        except Exception as e:
            logger.warning(f"Redis cache unavailable: {e}. Dashboard queries will not be cached.")
            self.redis_client = None
    
    def _generate_cache_key(self, prefix: str, **kwargs) -> str:
        """Generate a cache key from prefix and parameters"""
        # Sort kwargs for consistent key generation
        sorted_params = sorted(kwargs.items())
        params_str = json.dumps(sorted_params, sort_keys=True)
        
        # Create hash of parameters to avoid very long keys
        params_hash = hashlib.md5(params_str.encode()).hexdigest()[:8]
        
        return f"dashboard_cache:{prefix}:{params_hash}"
    
    def get(self, key: str) -> Optional[Any]:
        """Get cached value"""
        if not self.redis_client:
            return None
            
        try:
            cached_data = self.redis_client.get(key)
            if cached_data:
                return json.loads(cached_data)
        except Exception as e:
            logger.warning(f"Redis cache get error: {e}")
        
        return None
    
    def set(self, key: str, value: Any, ttl: int = None) -> bool:
        """Set cached value with TTL"""
        if not self.redis_client:
            return False
            
        try:
            ttl = ttl or self.default_ttl
            cached_data = json.dumps(value, default=str)  # Handle datetime objects
            self.redis_client.setex(key, ttl, cached_data)
            return True
        except Exception as e:
            logger.warning(f"Redis cache set error: {e}")
            return False
    
    def delete_pattern(self, pattern: str) -> int:
        """Delete keys matching pattern"""
        if not self.redis_client:
            return 0
            
        try:
            keys = self.redis_client.keys(pattern)
            if keys:
                return self.redis_client.delete(*keys)
        except Exception as e:
            logger.warning(f"Redis cache delete pattern error: {e}")
        
        return 0
    
    def cached_query(self, prefix: str, ttl: int = None, **cache_params):
        """
        Decorator for caching expensive queries
        
        Args:
            prefix: Cache key prefix
            ttl: Time-to-live in seconds  
            **cache_params: Additional parameters for cache key generation
        """
        def decorator(func: Callable):
            def wrapper(*args, **kwargs):
                # Generate cache key from function name and parameters
                cache_key = self._generate_cache_key(
                    prefix, 
                    func_name=func.__name__,
                    args=args,
                    kwargs=kwargs,
                    **cache_params
                )
                
                # Try to get from cache first
                cached_result = self.get(cache_key)
                if cached_result is not None:
                    logger.debug(f"Cache hit for {cache_key}")
                    return cached_result
                
                # Execute function and cache result
                logger.debug(f"Cache miss for {cache_key}, executing query")
                result = func(*args, **kwargs)
                
                # Cache the result
                self.set(cache_key, result, ttl)
                
                return result
            
            return wrapper
        return decorator
    
    def invalidate_dashboard_cache(self):
        """Invalidate all dashboard cache entries"""
        pattern = "dashboard_cache:*"
        deleted_count = self.delete_pattern(pattern)
        logger.info(f"Invalidated {deleted_count} dashboard cache entries")
        return deleted_count
    
    def get_cache_stats(self) -> dict:
        """Get cache statistics"""
        if not self.redis_client:
            return {"status": "unavailable"}
            
        try:
            info = self.redis_client.info()
            dashboard_keys = len(self.redis_client.keys("dashboard_cache:*"))
            
            return {
                "status": "connected",
                "redis_version": info.get("redis_version"),
                "used_memory": info.get("used_memory_human"),
                "connected_clients": info.get("connected_clients"),
                "dashboard_cache_keys": dashboard_keys,
                "cache_url": self.redis_url
            }
        except Exception as e:
            logger.error(f"Error getting cache stats: {e}")
            return {"status": "error", "error": str(e)}

# Global cache instance
cache = RedisCache() 