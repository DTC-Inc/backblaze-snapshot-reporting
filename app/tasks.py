"""
Celery tasks for async webhook processing
"""

from .celery_app import celery
from .webhooks import WebhookProcessor
from .models.database_factory import get_database_from_config
from .models.redis_cache import cache
from .models.hybrid_cache import simple_cache
import os
import logging
import json
from datetime import datetime
from flask import current_app

logger = logging.getLogger(__name__)

@celery.task(bind=True, autoretry_for=(Exception,), retry_kwargs={'max_retries': 3, 'countdown': 60})
def process_webhook_task(self, webhook_data, source_ip=None, user_agent=None):
    """
    Celery task to process webhook events asynchronously
    
    Args:
        webhook_data (dict): The webhook event data from Backblaze
        source_ip (str): Source IP address of the webhook request
        user_agent (str): User agent string from the webhook request
        
    Returns:
        dict: Processing result with success/error information
    """
    try:
        # Initialize database connection in worker using the same factory as main app
        db = get_database_from_config()
        if not db:
            raise Exception("Database connection could not be established for Celery worker")
            
        processor = WebhookProcessor(db)
        
        logger.info(f"Processing webhook task {self.request.id} for bucket: {webhook_data.get('bucketName')}")
        
        # Process the webhook event
        result = processor.process_webhook_event(
            webhook_data, 
            source_ip=source_ip, 
            user_agent=user_agent
        )
        
        if result['success']:
            logger.info(f"Webhook task {self.request.id} processed successfully: {result['event_id']}")
            
            # Invalidate dashboard caches since new data was added
            try:
                # Invalidate both regular dashboard cache and simple time-series cache
                cache.invalidate_dashboard_cache()
                simple_cache.invalidate_current_day_cache()
                logger.debug(f"Dashboard caches invalidated after webhook processing")
            except Exception as cache_error:
                logger.warning(f"Failed to invalidate dashboard caches: {cache_error}")
            
            # Emit WebSocket event for real-time updates (if needed)
            try:
                emit_webhook_event_for_task(result['event_id'], webhook_data)
            except Exception as emit_error:
                logger.warning(f"Failed to emit WebSocket event: {emit_error}")
            
            return {
                'success': True,
                'event_id': result['event_id'],
                'message': result['message'],
                'task_id': self.request.id,
                'processed_at': datetime.now().isoformat()
            }
        else:
            logger.error(f"Webhook task {self.request.id} failed: {result['error']}")
            raise Exception(f"Webhook processing failed: {result['error']}")
            
    except Exception as e:
        logger.error(f"Error in webhook task {self.request.id}: {str(e)}")
        
        # Check if we should retry
        if self.request.retries < self.max_retries:
            logger.info(f"Retrying webhook task {self.request.id} (attempt {self.request.retries + 1}/{self.max_retries + 1})")
            raise self.retry(exc=e, countdown=60 * (self.request.retries + 1))  # Exponential backoff
        else:
            logger.error(f"Webhook task {self.request.id} failed permanently after {self.request.retries + 1} attempts")
            raise

@celery.task(bind=True, autoretry_for=(Exception,), retry_kwargs={'max_retries': 1})
def verify_webhook_signature_task(self, payload, signature, secret):
    """
    Celery task for webhook signature verification (if needed for heavy loads)
    
    Args:
        payload (str): Raw webhook payload
        signature (str): Signature from webhook headers
        secret (str): Webhook secret for verification
        
    Returns:
        bool: True if signature is valid
    """
    try:
        processor = WebhookProcessor(None)  # No DB needed for signature verification
        is_valid = processor.verify_webhook_signature(payload, signature, secret)
        
        logger.debug(f"Signature verification task {self.request.id}: {'valid' if is_valid else 'invalid'}")
        return is_valid
        
    except Exception as e:
        logger.error(f"Error in signature verification task {self.request.id}: {str(e)}")
        raise self.retry(exc=e)

@celery.task
def cleanup_old_task_results():
    """
    Periodic task to clean up old Celery task results
    """
    try:
        # Clean up results older than 24 hours
        celery.backend.cleanup()
        logger.info("Cleaned up old Celery task results")
        return {"status": "success", "message": "Old task results cleaned up"}
    except Exception as e:
        logger.error(f"Error cleaning up task results: {str(e)}")
        return {"status": "error", "message": str(e)}

@celery.task
def health_check_task():
    """
    Simple health check task for monitoring
    """
    try:
        # Test database connection using the same factory as main app
        db = get_database_from_config()
        if not db:
            raise Exception("Database connection could not be established")
        
        # Simple DB health check
        db.get_billing_configuration()  # This will test the connection
        
        return {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "worker_id": os.getpid()
        }
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        return {
            "status": "unhealthy", 
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }

def emit_webhook_event_for_task(event_id, webhook_data):
    """
    Helper function to emit WebSocket events from Celery tasks
    Note: This requires Redis for pub/sub or similar mechanism
    """
    try:
        # Since we can't directly access Flask-SocketIO from Celery,
        # we can publish to Redis and have the main app listen
        import redis
        
        redis_url = os.getenv('CELERY_BROKER_URL', 'redis://redis:6379/0')
        r = redis.from_url(redis_url)
        
        # Publish event for main app to emit via WebSocket
        event_data = {
            'id': event_id,
            'request_id': webhook_data.get('eventId'),
            'event_type': webhook_data.get('eventType'),
            'bucket_name': webhook_data.get('bucketName'),
            'object_key': webhook_data.get('objectName'),
            'object_size': webhook_data.get('objectSize'),
            'object_version_id': webhook_data.get('objectVersionId'),
            'event_timestamp': webhook_data.get('eventTimestamp'),
            'created_at': datetime.now().isoformat(),
        }
        
        r.publish('webhook_events', json.dumps(event_data))
        logger.debug(f"Published webhook event {event_id} to Redis for WebSocket emission")
        
    except Exception as e:
        logger.warning(f"Failed to publish webhook event to Redis: {e}")

# Periodic tasks (if using Celery Beat)
from celery.schedules import crontab

celery.conf.beat_schedule = {
    'cleanup-task-results': {
        'task': 'app.tasks.cleanup_old_task_results',
        'schedule': crontab(hour=2, minute=0),  # Daily at 2 AM
    },
} 