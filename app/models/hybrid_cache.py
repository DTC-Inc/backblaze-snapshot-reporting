"""
Simple 3-month caching system for immutable time-series dashboard data
All data cached for 3 months since it never changes once written
"""

import redis
import json
import hashlib
import logging
from datetime import datetime, timedelta
from typing import Any, Optional, List, Dict
import os

logger = logging.getLogger(__name__)

class SimpleTimeSeriesCache:
    def __init__(self, redis_url: str = None):
        """
        Initialize simple cache for immutable time-series data
        
        Strategy:
        - All data cached for 3 months (data never changes once written)
        - Only current day cache invalidated on webhook events
        """
        self.redis_url = redis_url or os.getenv('REDIS_URL', 'redis://bbssr_redis:6379/2')
        self.redis_client = None
        
        # Simple caching strategy
        self.CACHE_TTL = 86400 * 90  # 3 months for all data
        
        try:
            self.redis_client = redis.from_url(self.redis_url)
            self.redis_client.ping()
            logger.info(f"Simple time-series cache initialized: {self.redis_url} (3-month TTL)")
        except Exception as e:
            logger.warning(f"Cache unavailable: {e}")
            self.redis_client = None
    
    def _generate_cache_key(self, prefix: str, date_str: str = None, **kwargs) -> str:
        """Generate cache key with optional date partitioning"""
        params_hash = hashlib.md5(json.dumps(sorted(kwargs.items())).encode()).hexdigest()[:8]
        
        if date_str:
            return f"simple_cache:{prefix}:{date_str}:{params_hash}"
        else:
            return f"simple_cache:{prefix}:{params_hash}"
    
    def get_daily_breakdown_cached(self, start_date_str: str, end_date_str: str, 
                                   bucket_name: str = None, db_instance=None) -> List[Dict]:
        """
        Get daily breakdown with simple 3-month caching per day
        Each day cached separately for optimal cache hit rates
        """
        if not self.redis_client or not db_instance:
            # Fallback to direct DB query
            return db_instance.get_daily_object_operation_breakdown(
                start_date_str, end_date_str, bucket_name
            ) if db_instance else []
        
        # Parse date range
        start_date = datetime.fromisoformat(start_date_str.split('T')[0])
        end_date = datetime.fromisoformat(end_date_str.split('T')[0])
        
        # Fetch each day separately for better cache granularity
        current_date = start_date
        all_data = []
        cache_hits = 0
        cache_misses = 0
        
        while current_date <= end_date:
            date_str = current_date.strftime('%Y-%m-%d')
            
            # Generate cache key for this specific date
            cache_key = self._generate_cache_key(
                "daily_breakdown", 
                date_str=date_str,
                bucket=bucket_name
            )
            
            # Check cache first
            cached_data = self._get_cached_data(cache_key)
            
            if cached_data:
                all_data.extend(cached_data)
                cache_hits += 1
                logger.debug(f"Cache HIT for daily data {date_str}")
            else:
                # Cache miss - fetch from DB for this specific date
                daily_start = current_date.replace(hour=0, minute=0, second=0).isoformat()
                daily_end = current_date.replace(hour=23, minute=59, second=59).isoformat()
                
                daily_data = db_instance.get_daily_object_operation_breakdown(
                    daily_start, daily_end, bucket_name
                )
                
                if daily_data:
                    all_data.extend(daily_data)
                    
                    # Cache for 3 months
                    self._set_cached_data(cache_key, daily_data)
                    logger.info(f"Cache MISS for daily data {date_str} - stored for 3 months")
                
                cache_misses += 1
            
            current_date += timedelta(days=1)
        
        logger.info(f"Cache performance - Hits: {cache_hits}, Misses: {cache_misses} ({cache_hits}/{cache_hits + cache_misses} hit rate)")
        return all_data
    
    def get_monthly_summary_cached(self, year: int, month: int, bucket_name: str = None, 
                                   db_instance=None) -> Dict:
        """
        Get monthly summary with 3-month caching
        """
        if not self.redis_client or not db_instance:
            return {}
        
        # Don't process future months
        now = datetime.now()
        is_future_month = (year > now.year) or (year == now.year and month > now.month)
        
        if is_future_month:
            return {}
        
        cache_key = self._generate_cache_key(
            "monthly_summary",
            date_str=f"{year}-{month:02d}",
            bucket=bucket_name
        )
        
        # Check cache
        cached_data = self._get_cached_data(cache_key)
        if cached_data:
            logger.info(f"Cache HIT for monthly summary {year}-{month:02d}")
            return cached_data
        
        # Fetch from database
        month_start = datetime(year, month, 1).isoformat()
        if month == 12:
            month_end = datetime(year + 1, 1, 1) - timedelta(seconds=1)
        else:
            month_end = datetime(year, month + 1, 1) - timedelta(seconds=1)
        
        monthly_data = db_instance.get_object_operation_stats_for_period(
            month_start, month_end.isoformat(), bucket_name
        )
        
        if monthly_data:
            self._set_cached_data(cache_key, monthly_data)
            logger.info(f"Cache MISS for monthly summary {year}-{month:02d} - stored for 3 months")
        
        return monthly_data or {}
    
    def get_bucket_stats_cached(self, bucket_name: str = None, operation_type: str = 'added',
                               start_date_str: str = None, end_date_str: str = None,
                               limit: int = 10, db_instance=None) -> List[Dict]:
        """
        Get bucket statistics with 3-month caching
        """
        if not self.redis_client or not db_instance:
            return []
        
        cache_key = self._generate_cache_key(
            f"bucket_stats_{operation_type}",
            bucket=bucket_name,
            start=start_date_str,
            end=end_date_str,
            limit=limit
        )
        
        # Check cache
        cached_data = self._get_cached_data(cache_key)
        if cached_data:
            logger.info(f"Cache HIT for bucket stats ({operation_type})")
            return cached_data
        
        # Fetch from database - you'd integrate with your actual bucket stats methods here
        logger.info(f"Cache MISS for bucket stats ({operation_type}) - would store for 3 months")
        
        # Placeholder - integrate with your existing bucket stats methods
        return []
    
    def _get_cached_data(self, key: str) -> Optional[Any]:
        """Get data from cache"""
        try:
            cached_data = self.redis_client.get(key)
            return json.loads(cached_data) if cached_data else None
        except Exception as e:
            logger.warning(f"Cache get error for {key}: {e}")
            return None
    
    def _set_cached_data(self, key: str, data: Any) -> bool:
        """Set data in cache with 3-month TTL"""
        try:
            cached_data = json.dumps(data, default=str)
            self.redis_client.setex(key, self.CACHE_TTL, cached_data)
            return True
        except Exception as e:
            logger.warning(f"Cache set error for {key}: {e}")
            return False
    
    def invalidate_current_day_cache(self) -> int:
        """
        Invalidate only current day cache entries
        Called when new webhook events are processed for today
        """
        if not self.redis_client:
            return 0
        
        # Only invalidate today's cache entries
        today = datetime.now().strftime('%Y-%m-%d')
        pattern = f"simple_cache:*:{today}:*"
        
        keys = self.redis_client.keys(pattern)
        deleted_count = 0
        if keys:
            deleted_count = self.redis_client.delete(*keys)
        
        logger.info(f"Invalidated {deleted_count} current day cache entries ({today})")
        return deleted_count
    
    def invalidate_date_cache(self, date_str: str) -> int:
        """
        Invalidate cache entries for a specific date
        Useful for manual cache invalidation or data corrections
        """
        if not self.redis_client:
            return 0
        
        pattern = f"simple_cache:*:{date_str}:*"
        keys = self.redis_client.keys(pattern)
        deleted_count = 0
        if keys:
            deleted_count = self.redis_client.delete(*keys)
        
        logger.info(f"Invalidated {deleted_count} cache entries for {date_str}")
        return deleted_count
    
    def get_cache_stats(self) -> Dict:
        """Get cache statistics"""
        if not self.redis_client:
            return {"status": "unavailable"}
        
        try:
            info = self.redis_client.info()
            
            # Count cache keys
            all_keys = self.redis_client.keys("simple_cache:*")
            
            # Categorize by cache type
            daily_keys = len([k for k in all_keys if b'daily_breakdown' in k])
            monthly_keys = len([k for k in all_keys if b'monthly_summary' in k]) 
            bucket_keys = len([k for k in all_keys if b'bucket_stats' in k])
            other_keys = len(all_keys) - daily_keys - monthly_keys - bucket_keys
            
            return {
                "status": "connected",
                "redis_version": info.get("redis_version"),
                "used_memory": info.get("used_memory_human"),
                "total_cache_keys": len(all_keys),
                "daily_breakdown_keys": daily_keys,
                "monthly_summary_keys": monthly_keys,
                "bucket_stats_keys": bucket_keys,
                "other_keys": other_keys,
                "cache_url": self.redis_url,
                "strategy": {
                    "ttl_days": self.CACHE_TTL / 86400,
                    "immutable_data": True,
                    "per_day_caching": True
                }
            }
        except Exception as e:
            logger.error(f"Error getting cache stats: {e}")
            return {"status": "error", "error": str(e)}

# Global simple cache instance
simple_cache = SimpleTimeSeriesCache() 