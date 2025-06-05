import hashlib
import hmac
import json
import logging
from datetime import datetime
from flask import request, current_app

logger = logging.getLogger(__name__)

class WebhookProcessor:
    """Handles Backblaze webhook events"""
    
    def __init__(self, db):
        self.db = db
        self.redis_buffer = None
    
    def set_redis_buffer(self, redis_buffer):
        """Set the Redis buffer for event storage"""
        self.redis_buffer = redis_buffer
        logger.info("Redis buffer enabled for webhook processor")
    
    def get_bucket_configuration_cached(self, bucket_name):
        """Get bucket configuration with Redis caching to avoid database locks"""
        if self.redis_buffer and self.redis_buffer.redis_client:
            # Try to get bucket config from Redis cache first
            try:
                config_key = f"bucket_config:{bucket_name}"
                cached_config = self.redis_buffer.redis_client.get(config_key)
                if cached_config:
                    bucket_config = json.loads(cached_config)
                    logger.debug(f"Retrieved bucket config for {bucket_name} from Redis cache")
                    return bucket_config
                else:
                    # Not in cache, get from database and cache it
                    bucket_config = self.db.get_bucket_configuration(bucket_name)
                    if bucket_config:
                        # Cache for 5 minutes
                        self.redis_buffer.redis_client.setex(config_key, 300, json.dumps(bucket_config))
                        logger.debug(f"Cached bucket config for {bucket_name} in Redis")
                    return bucket_config
            except Exception as e:
                logger.warning(f"Redis bucket config cache error: {e}, falling back to database")
                return self.db.get_bucket_configuration(bucket_name)
        else:
            # No Redis, use database directly
            return self.db.get_bucket_configuration(bucket_name)
    
    def verify_webhook_signature(self, payload, signature, secret):
        """Verify the webhook signature from Backblaze
        
        Args:
            payload (str): Raw webhook payload
            signature (str): Signature from the webhook header
            secret (str): Webhook secret for verification
            
        Returns:
            bool: True if signature is valid
        """
        logger.debug(f"SERVER_VERIFY: Attempting signature verification.")
        logger.debug(f"SERVER_VERIFY: Received payload string for signing: [{payload}]")
        logger.debug(f"SERVER_VERIFY: Using secret from DB for bucket: [{secret}]")
        logger.debug(f"SERVER_VERIFY: Received signature header: [{signature}]")

        if not secret or not signature:
            logger.warning("SERVER_VERIFY: Verification failed - missing secret or signature.")
            return False
            
        # Handle Backblaze signature format: v1=<hex_signature>
        actual_signature = signature
        if signature.startswith('sha256='):
            # Legacy format or test format
            actual_signature = signature[7:]
        elif signature.startswith('v1='):
            # Official Backblaze format: v1=<hex_signature>
            actual_signature = signature[3:]
        elif '=' in signature:
            # Check for other versioned formats
            parts = signature.split('=', 1)
            if len(parts) == 2:
                version, sig_value = parts
                if version == 'v1':
                    actual_signature = sig_value
                else:
                    logger.warning(f"SERVER_VERIFY: Unsupported signature version: {version}")
                    return False
            else:
                logger.warning(f"SERVER_VERIFY: Invalid signature format: {signature}")
                return False
        # If no prefix, assume it's just the raw hex signature
        
        logger.debug(f"SERVER_VERIFY: Extracted signature (after removing prefix): [{actual_signature}]")
            
        # Calculate expected signature
        expected_signature = hmac.new(
            secret.encode('utf-8'),
            payload.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        # Use constant time comparison to prevent timing attacks
        is_valid = hmac.compare_digest(expected_signature, actual_signature)
        logger.debug(f"SERVER_VERIFY: Calculated expected signature: [{expected_signature}]")
        logger.debug(f"SERVER_VERIFY: Comparing expected vs actual: [{expected_signature}] vs [{actual_signature}]")
        logger.debug(f"SERVER_VERIFY: Signature valid: {is_valid}")
        return is_valid
    
    def process_webhook_event(self, payload_data, source_ip=None, user_agent=None):
        """Process a webhook event from Backblaze
        
        Args:
            payload_data (dict): Parsed webhook payload
            source_ip (str): Source IP address
            user_agent (str): User agent string
            
        Returns:
            dict: Processing result with success/error information
        """
        try:
            # Extract event information
            event_type = payload_data.get('eventType', '')
            bucket_name = payload_data.get('bucketName', '')
            
            if not event_type or not bucket_name:
                return {
                    'success': False,
                    'error': 'Missing required fields (eventType or bucketName)'
                }
            
            # Check if we have configuration for this bucket
            bucket_config = self.get_bucket_configuration_cached(bucket_name)
            if not bucket_config or not bucket_config.get('webhook_enabled'):
                logger.info(f"Received webhook for unconfigured/disabled bucket: {bucket_name}. Bucket config: {bucket_config}")
                return {
                    'success': False,
                    'error': f'Webhooks not enabled for bucket: {bucket_name}'
                }
            
            # Check if this event type is being tracked
            raw_events_to_track = bucket_config.get('events_to_track', [])
            parsed_events_to_track = []
            if isinstance(raw_events_to_track, str):
                try:
                    parsed_events_to_track = json.loads(raw_events_to_track)
                except json.JSONDecodeError:
                    logger.error(f"Could not parse events_to_track JSON string for bucket {bucket_name}: '{raw_events_to_track}'")
                    # Fallback to an empty list, so the event will likely be rejected below, which is safer.
                    parsed_events_to_track = [] 
            elif isinstance(raw_events_to_track, list):
                parsed_events_to_track = raw_events_to_track
            else:
                logger.error(f"Unexpected type for events_to_track for bucket {bucket_name}: {type(raw_events_to_track)}. Value: '{raw_events_to_track}'")
                parsed_events_to_track = []

            event_is_tracked = False
            for tracked_pattern in parsed_events_to_track:
                if tracked_pattern.endswith(':*'):
                    # Wildcard match: b2:ObjectCreated:* should match b2:ObjectCreated:Upload
                    category = tracked_pattern[:-2] # e.g., "b2:ObjectCreated"
                    if event_type.startswith(category + ':'):
                        event_is_tracked = True
                        break
                elif tracked_pattern == event_type:
                    # Exact match
                    event_is_tracked = True
                    break
            
            if not event_is_tracked:
                logger.info(f"Received untracked event type '{event_type}' for bucket '{bucket_name}'. Bucket config tracked events: {parsed_events_to_track} (Raw from DB: '{raw_events_to_track}')")
                return {
                    'success': False,
                    'error': f'Event type {event_type} not tracked for bucket {bucket_name}'
                }
            
            # Enhance payload with additional metadata
            enhanced_payload = {
                **payload_data,
                'sourceIpAddress': source_ip,
                'userAgent': user_agent,
                'receivedAt': datetime.now().isoformat()
            }
            
            # Save the webhook event - use Redis buffering for SQLite, direct writes for MongoDB
            event_id = None
            if self.redis_buffer:
                logger.debug(f"Attempting to buffer event in Redis for bucket {bucket_name}")
                redis_success = self.redis_buffer.add_event(enhanced_payload)
                if redis_success:
                    # For Redis buffering, we don't have a real event_id yet since it hasn't been saved to SQLite
                    # Use a temporary ID based on timestamp + bucket + event type for tracking
                    temp_id = f"redis_{int(datetime.now().timestamp() * 1000)}_{bucket_name}_{event_type}"
                    event_id = temp_id
                    logger.info(f"Successfully buffered webhook event in Redis for bucket {bucket_name}, event: {event_type} (temp_id: {temp_id})")
                else:
                    logger.error(f"Failed to buffer event in Redis for bucket {bucket_name} - rejecting webhook to avoid database locks")
                    return {
                        'success': False,
                        'error': 'Event buffering failed - webhook rejected to prevent database locks'
                    }
            else:
                # Redis disabled - check if we're using MongoDB or SQLite
                database_type = type(self.db).__name__
                if database_type == 'MongoDatabase':
                    # MongoDB can handle direct writes efficiently without locking issues
                    logger.debug(f"Writing webhook event directly to MongoDB for bucket {bucket_name}")
                    event_id = self.db.save_webhook_event(enhanced_payload)
                    if event_id:
                        logger.info(f"Successfully saved webhook event directly to MongoDB for bucket {bucket_name}, event: {event_type} (id: {event_id})")
                    else:
                        logger.error(f"Failed to save webhook event directly to MongoDB for bucket {bucket_name}")
                        return {
                            'success': False,
                            'error': 'Failed to save event to MongoDB'
                        }
                else:
                    # SQLite without Redis - reject webhook to avoid database locks during high load
                    logger.error(f"Redis buffering disabled with SQLite - rejecting webhook for bucket {bucket_name} to avoid database locks")
                    return {
                        'success': False,
                        'error': 'Redis buffering required for SQLite webhook processing'
                    }
            
            return {
                'success': True,
                'event_id': event_id,
                'message': f'Webhook event processed successfully'
            }
            
        except Exception as e:
            logger.error(f"Error processing webhook event: {str(e)}")
            return {
                'success': False,
                'error': f'Error processing webhook: {str(e)}'
            }
    
    def get_webhook_url(self, bucket_name=None, include_secret=False):
        """Generate webhook URL for Backblaze configuration
        
        Args:
            bucket_name (str): Optional bucket name for bucket-specific URLs
            include_secret (bool): Whether to include the secret in response
            
        Returns:
            dict: Webhook configuration information
        """
        base_url = request.url_root.rstrip('/')
        webhook_path = '/api/webhooks/backblaze'
        
        if bucket_name:
            webhook_path += f'?bucket={bucket_name}'
        
        webhook_url = f"{base_url}{webhook_path}"
        
        result = {
            'webhook_url': webhook_url,
            'supported_events': [
                'b2:ObjectCreated',
                'b2:ObjectDeleted',
                'b2:ObjectRestore',
                'b2:ObjectArchive'
            ]
        }
        
        if include_secret and bucket_name:
            config = self.get_bucket_configuration_cached(bucket_name)
            if config:
                result['webhook_secret'] = config.get('webhook_secret')
        
        return result
    
    def generate_webhook_secret(self):
        """Generate a secure webhook secret
        
        Returns:
            str: Generated webhook secret
        """
        import secrets
        return secrets.token_urlsafe(32)
    
    def get_event_summary(self, days=7):
        """Get a summary of webhook events
        
        Args:
            days (int): Number of days to summarize
            
        Returns:
            dict: Summary of webhook activity
        """
        try:
            events = self.db.get_webhook_events(limit=1000)
            statistics = self.db.get_webhook_statistics(days=days)
            
            # Calculate totals
            total_events = len(events)
            
            # Group by event type
            event_types = {}
            buckets = {}
            
            for event in events:
                event_type = event.get('event_type', 'unknown')
                bucket_name = event.get('bucket_name', 'unknown')
                
                event_types[event_type] = event_types.get(event_type, 0) + 1
                buckets[bucket_name] = buckets.get(bucket_name, 0) + 1
            
            # Recent activity (last 24 hours)
            recent_cutoff = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            recent_events = [
                e for e in events 
                if datetime.fromisoformat(e['timestamp'].replace('Z', '+00:00')) >= recent_cutoff
            ]
            
            return {
                'total_events': total_events,
                'recent_events_24h': len(recent_events),
                'event_types': event_types,
                'active_buckets': buckets,
                'statistics': statistics,
                'summary_period_days': days
            }
            
        except Exception as e:
            logger.error(f"Error generating event summary: {str(e)}")
            return {
                'error': f'Error generating summary: {str(e)}'
            } 