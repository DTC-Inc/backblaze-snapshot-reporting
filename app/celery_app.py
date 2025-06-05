"""
Celery application configuration for async webhook processing
"""

from celery import Celery
import os
import logging

logger = logging.getLogger(__name__)

def make_celery(app=None):
    """Create and configure Celery instance"""
    broker_url = os.getenv('CELERY_BROKER_URL', 'redis://redis:6379/0')
    result_backend = os.getenv('CELERY_RESULT_BACKEND', 'redis://redis:6379/1')
    
    celery = Celery('bbssr_webhooks')
    
    # Celery configuration
    celery.conf.update(
        broker_url=broker_url,
        result_backend=result_backend,
        task_serializer='json',
        accept_content=['json'],
        result_serializer='json',
        timezone='UTC',
        enable_utc=True,
        
        # Worker optimization settings
        worker_prefetch_multiplier=1,  # Process one task at a time for memory efficiency
        task_acks_late=True,  # Acknowledge task after completion (safer)
        worker_max_tasks_per_child=1000,  # Restart worker after 1000 tasks to prevent memory leaks
        
        # Task routing and retry settings
        task_default_retry_delay=60,  # Wait 60 seconds before retry
        task_max_retries=3,
        
        # Result settings
        result_expires=3600,  # Results expire after 1 hour
        
        # Performance settings
        worker_disable_rate_limits=True,
        task_ignore_result=False,  # Store results for monitoring
        
        # Monitoring
        worker_send_task_events=True,
        task_send_sent_event=True,
    )
    
    # Flask app integration (if provided)
    if app:
        class ContextTask(celery.Task):
            """Make celery tasks work with Flask app context"""
            def __call__(self, *args, **kwargs):
                with app.app_context():
                    return self.run(*args, **kwargs)
        
        celery.Task = ContextTask
    
    logger.info(f"Celery configured with broker: {broker_url}")
    return celery

# Initialize Celery instance
celery = make_celery()

# Import tasks to register them with Celery
try:
    from . import tasks
    logger.info("Celery tasks imported successfully")
except ImportError as e:
    logger.warning(f"Could not import tasks: {e}") 