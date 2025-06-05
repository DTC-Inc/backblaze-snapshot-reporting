"""
Redis buffer for webhook events to reduce SQLite write frequency and SSD wear
"""
import redis
import json
import logging
import threading
import time
from datetime import datetime
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

class RedisEventBuffer:
    def __init__(self, redis_url='redis://localhost:6379/0', flush_interval=10):
        """
        Initialize Redis event buffer
        
        Args:
            redis_url (str): Redis connection URL
            flush_interval (int): Seconds between flushes to SQLite
        """
        self.redis_url = redis_url
        self.flush_interval = flush_interval
        self.redis_client = None
        self.running = False
        self.flush_thread = None
        self.database = None  # Will be set by the main app
        
        # Redis keys
        self.events_queue_key = 'webhook_events:queue'
        self.events_backup_key = 'webhook_events:backup'
        self.stats_key = 'webhook_events:stats'
        
        self._connect_redis()
    
    def _connect_redis(self):
        """Connect to Redis with error handling"""
        try:
            self.redis_client = redis.from_url(
                self.redis_url,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5,
                retry_on_timeout=True
            )
            # Test connection
            self.redis_client.ping()
            logger.info("Connected to Redis successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            self.redis_client = None
            return False
    
    def set_database(self, database):
        """Set the database instance for flushing events"""
        self.database = database
    
    def start_flush_worker(self):
        """Start the background thread that flushes events to SQLite"""
        if self.running:
            return
            
        self.running = True
        self.flush_thread = threading.Thread(target=self._flush_worker, daemon=True)
        self.flush_thread.start()
        logger.info(f"Started Redis flush worker (interval: {self.flush_interval}s)")
    
    def stop_flush_worker(self):
        """Stop the background flush worker"""
        self.running = False
        if self.flush_thread and self.flush_thread.is_alive():
            self.flush_thread.join(timeout=5)
        logger.info("Stopped Redis flush worker")
    
    def add_event(self, webhook_data: Dict) -> bool:
        """
        Add a webhook event to the Redis buffer
        
        Args:
            webhook_data (dict): The webhook event data
            
        Returns:
            bool: True if successfully added to Redis, False if fallback to direct DB save needed
        """
        if not self.redis_client:
            if not self._connect_redis():
                return False
        
        try:
            # Add timestamp if not present
            if 'buffer_timestamp' not in webhook_data:
                webhook_data['buffer_timestamp'] = datetime.now().isoformat()
            
            # Push to Redis queue
            event_json = json.dumps(webhook_data)
            self.redis_client.lpush(self.events_queue_key, event_json)
            
            # Update stats
            self.redis_client.hincrby(self.stats_key, 'total_buffered', 1)
            self.redis_client.hincrby(self.stats_key, 'pending_flush', 1)
            
            logger.debug(f"Added event to Redis buffer: {webhook_data.get('eventType', 'unknown')}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to add event to Redis buffer: {e}")
            # Try to reconnect for next time
            self._connect_redis()
            return False
    
    def get_buffer_stats(self) -> Dict:
        """Get current buffer statistics"""
        if not self.redis_client:
            return {'redis_connected': False}
        
        try:
            stats = self.redis_client.hgetall(self.stats_key)
            queue_size = self.redis_client.llen(self.events_queue_key)
            
            return {
                'redis_connected': True,
                'queue_size': queue_size,
                'total_buffered': int(stats.get('total_buffered', 0)),
                'total_flushed': int(stats.get('total_flushed', 0)),
                'pending_flush': int(stats.get('pending_flush', 0)),
                'last_flush': stats.get('last_flush', 'Never'),
                'flush_errors': int(stats.get('flush_errors', 0))
            }
        except Exception as e:
            logger.error(f"Failed to get buffer stats: {e}")
            return {'redis_connected': False, 'error': str(e)}
    
    def _flush_worker(self):
        """Background worker that periodically flushes events to SQLite"""
        logger.info("Redis flush worker started")
        
        while self.running:
            try:
                time.sleep(self.flush_interval)
                if self.running:  # Check again after sleep
                    self._flush_events()
            except Exception as e:
                logger.error(f"Error in flush worker: {e}")
                time.sleep(1)  # Short sleep before retrying
        
        # Final flush when stopping
        try:
            self._flush_events()
            logger.info("Final flush completed")
        except Exception as e:
            logger.error(f"Error in final flush: {e}")
    
    def _flush_events(self):
        """Flush all pending events from Redis to SQLite"""
        if not self.redis_client or not self.database:
            return
        
        try:
            # Get all events from queue
            events = []
            while True:
                event_json = self.redis_client.rpop(self.events_queue_key)
                if not event_json:
                    break
                try:
                    event_data = json.loads(event_json)
                    events.append(event_data)
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to decode buffered event: {e}")
                    # Continue with other events
            
            if not events:
                return
            
            logger.info(f"Flushing {len(events)} events from Redis to SQLite")
            
            # Batch save to SQLite
            saved_count = 0
            for event_data in events:
                try:
                    # Remove our internal timestamp before saving
                    event_data.pop('buffer_timestamp', None)
                    self.database.save_webhook_event(event_data)
                    saved_count += 1
                except Exception as e:
                    logger.error(f"Failed to save event to SQLite: {e}")
                    # Add back to backup queue for retry
                    backup_json = json.dumps(event_data)
                    self.redis_client.lpush(self.events_backup_key, backup_json)
            
            # Update stats
            self.redis_client.hincrby(self.stats_key, 'total_flushed', saved_count)
            self.redis_client.hincrby(self.stats_key, 'pending_flush', -saved_count)
            self.redis_client.hset(self.stats_key, 'last_flush', datetime.now().isoformat())
            
            if saved_count != len(events):
                self.redis_client.hincrby(self.stats_key, 'flush_errors', len(events) - saved_count)
                logger.warning(f"Only saved {saved_count}/{len(events)} events to SQLite")
            else:
                logger.info(f"Successfully flushed {saved_count} events to SQLite")
                
        except Exception as e:
            logger.error(f"Error during flush operation: {e}")
            self.redis_client.hincrby(self.stats_key, 'flush_errors', 1)
    
    def flush_now(self) -> int:
        """Manually trigger immediate flush of all pending events"""
        try:
            queue_size_before = self.redis_client.llen(self.events_queue_key) if self.redis_client else 0
            self._flush_events()
            queue_size_after = self.redis_client.llen(self.events_queue_key) if self.redis_client else 0
            return queue_size_before - queue_size_after
        except Exception as e:
            logger.error(f"Error in manual flush: {e}")
            return 0
    
    def get_recent_events_from_redis(self, limit=100) -> List[Dict]:
        """Get recent events from Redis buffer (for debugging/monitoring)"""
        if not self.redis_client:
            return []
        
        try:
            event_jsons = self.redis_client.lrange(self.events_queue_key, 0, limit - 1)
            events = []
            for event_json in event_jsons:
                try:
                    event_data = json.loads(event_json)
                    events.append(event_data)
                except json.JSONDecodeError:
                    continue
            return events
        except Exception as e:
            logger.error(f"Failed to get recent events from Redis: {e}")
            return []
    
    def clear_buffer(self):
        """Clear all buffered events (use with caution!)"""
        if not self.redis_client:
            return False
        
        try:
            cleared = self.redis_client.delete(
                self.events_queue_key,
                self.events_backup_key,
                self.stats_key
            )
            logger.warning(f"Cleared Redis buffer - deleted {cleared} keys")
            return True
        except Exception as e:
            logger.error(f"Failed to clear Redis buffer: {e}")
            return False 