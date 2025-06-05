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
            
        # Try to flush any backup events from previous run first
        self._recover_backup_events()
        
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
        """Flush all pending events from Redis to SQLite using chunked batch inserts"""
        if not self.redis_client or not self.database:
            return
        
        flush_start_time = time.time()
        
        try:
            # Get all events from queue
            events = []
            while True:
                event_json = self.redis_client.rpop(self.events_queue_key)
                if not event_json:
                    break
                try:
                    event_data = json.loads(event_json)
                    # Remove our internal timestamp before saving
                    event_data.pop('buffer_timestamp', None)
                    events.append(event_data)
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to decode buffered event: {e}")
                    continue
            
            if not events:
                return 0
                
            # Performance logging for high-volume monitoring
            batch_size = len(events)
            logger.info(f"Redis flush: {batch_size} events queued for chunked batch insert")
            
            # Use chunked writes to prevent application freezes
            chunk_size = 15000  # Process 15k events at a time - efficient for 5-minute intervals
            total_saved = 0
            max_retries = 3
            
            # Process events in chunks to avoid long database locks
            for i in range(0, len(events), chunk_size):
                chunk = events[i:i + chunk_size]
                chunk_number = (i // chunk_size) + 1
                total_chunks = (len(events) + chunk_size - 1) // chunk_size
                
                logger.debug(f"Processing chunk {chunk_number}/{total_chunks} ({len(chunk)} events)")
                
                retry_delay = 0.1
                chunk_saved = 0
                
                for attempt in range(max_retries):
                    try:
                        if hasattr(self.database, 'save_webhook_events_batch'):
                            chunk_saved = self.database.save_webhook_events_batch(chunk)
                        else:
                            # Fallback to individual saves if batch method not available
                            for event_data in chunk:
                                try:
                                    event_id = self.database.save_webhook_event(event_data)
                                    if event_id:
                                        chunk_saved += 1
                                except Exception as e:
                                    logger.error(f"Failed to save individual event: {e}")
                                    continue
                        
                        total_saved += chunk_saved
                        break  # Success, move to next chunk
                        
                    except Exception as e:
                        if "database is locked" in str(e).lower() and attempt < max_retries - 1:
                            logger.warning(f"Database locked during chunk {chunk_number} (attempt {attempt + 1}/{max_retries}), retrying in {retry_delay}s...")
                            time.sleep(retry_delay)
                            retry_delay *= 2  # Exponential backoff
                            continue
                        else:
                            logger.error(f"Failed to save chunk {chunk_number} (attempt {attempt + 1}/{max_retries}): {e}")
                            
                            # Move failed chunk to backup queue
                            try:
                                for event_data in chunk:
                                    self.redis_client.lpush(self.events_backup_key, json.dumps(event_data))
                                logger.info(f"Moved {len(chunk)} failed events from chunk {chunk_number} to backup queue")
                            except Exception as backup_e:
                                logger.error(f"Failed to backup chunk: {backup_e}")
                            break  # Don't try more chunks if this one failed
                
                # Small pause between chunks to allow other operations
                if i + chunk_size < len(events):
                    time.sleep(0.01)  # 10ms pause between chunks
            
            # Performance metrics
            flush_duration = time.time() - flush_start_time
            events_per_second = total_saved / flush_duration if flush_duration > 0 else 0
            
            logger.info(f"Redis chunked flush completed: {total_saved}/{batch_size} events saved in {flush_duration:.2f}s ({events_per_second:.0f} events/sec)")
            
            # Performance warnings with chunking context
            if flush_duration > 20.0:
                logger.warning(f"Slow Redis flush: {flush_duration:.2f}s for {batch_size} events in {chunk_size}-event chunks. Consider increasing chunk size or REDIS_FLUSH_INTERVAL.")
            elif batch_size > 400000:
                logger.warning(f"Very large batch: {batch_size} events. Consider shorter flush intervals to reduce memory usage.")
            
            # Update stats
            if self.redis_client:
                try:
                    self.redis_client.hincrby(self.stats_key, 'total_flushed', total_saved)
                    self.redis_client.hincrby(self.stats_key, 'pending_flush', -total_saved)
                    self.redis_client.hset(self.stats_key, 'last_flush', datetime.now().isoformat())
                    
                    if total_saved != batch_size:
                        failed_count = batch_size - total_saved
                        self.redis_client.hincrby(self.stats_key, 'flush_errors', failed_count)
                except Exception as e:
                    logger.error(f"Failed to update Redis stats: {e}")
            
            return total_saved
                        
        except Exception as e:
            logger.error(f"Critical error during Redis chunked flush: {e}")
            return 0
    
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
    
    def _recover_backup_events(self):
        """Recover any events from backup queue (from previous failed flushes)"""
        if not self.redis_client or not self.database:
            return
            
        try:
            backup_count = self.redis_client.llen(self.events_backup_key)
            if backup_count > 0:
                logger.info(f"Found {backup_count} backup events from previous run, attempting recovery...")
                
                # Move backup events back to main queue for processing
                while True:
                    backup_event = self.redis_client.rpop(self.events_backup_key)
                    if not backup_event:
                        break
                    self.redis_client.lpush(self.events_queue_key, backup_event)
                
                # Trigger immediate flush to process recovered events
                self._flush_events()
                logger.info("Backup event recovery completed")
        except Exception as e:
            logger.error(f"Error during backup event recovery: {e}") 