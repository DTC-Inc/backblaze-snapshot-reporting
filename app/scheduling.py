import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

def should_take_snapshot(last_snapshot_time, settings):
    """
    Determine if a snapshot should be taken based on schedule settings
    
    Args:
        last_snapshot_time: The datetime of the last snapshot taken
        settings: Dictionary with scheduling configuration:
            - schedule_type: 'interval', 'daily', 'weekly', 'monthly'
            - interval_hours: Hours between snapshots for 'interval' schedule
            - hour: Hour of day for scheduled snapshots (0-23)
            - minute: Minute of hour for scheduled snapshots (0-59)
            - day_of_week: Day of week for weekly snapshots (0=Monday, 6=Sunday)
            - day_of_month: Day of month for monthly snapshots (1-31)
            
    Returns:
        bool: True if a snapshot should be taken, False otherwise
    """
    now = datetime.now()
    
    # First snapshot always runs
    if last_snapshot_time is None:
        logger.info("Taking first snapshot")
        return True
    
    # Different schedule types
    if settings['schedule_type'] == 'interval':
        # Take snapshot if interval has passed
        if now - last_snapshot_time >= timedelta(hours=settings['interval_hours']):
            logger.info(f"Interval of {settings['interval_hours']} hours has passed, taking snapshot")
            return True
    
    elif settings['schedule_type'] == 'daily':
        # Check if it's the scheduled hour and minute and we haven't taken a snapshot today
        if (now.hour == settings['hour'] and now.minute == settings['minute'] and 
                (last_snapshot_time.date() < now.date() or 
                (last_snapshot_time.hour < settings['hour'] or 
                (last_snapshot_time.hour == settings['hour'] and last_snapshot_time.minute < settings['minute'])))):
            logger.info(f"Daily snapshot time reached: {settings['hour']}:{settings['minute']}")
            return True
    
    elif settings['schedule_type'] == 'weekly':
        # Python's weekday() returns 0 for Monday, 6 for Sunday
        if (now.weekday() == settings['day_of_week'] and 
                now.hour == settings['hour'] and now.minute == settings['minute'] and 
                (last_snapshot_time.date() < now.date() or 
                (last_snapshot_time.hour < settings['hour'] or 
                (last_snapshot_time.hour == settings['hour'] and last_snapshot_time.minute < settings['minute'])))):
            logger.info(f"Weekly snapshot time reached: day {settings['day_of_week']}, time {settings['hour']}:{settings['minute']}")
            return True
    
    elif settings['schedule_type'] == 'monthly':
        # Check if it's the scheduled day of month, hour and minute
        if (now.day == settings['day_of_month'] and 
                now.hour == settings['hour'] and now.minute == settings['minute'] and 
                (last_snapshot_time.date() < now.date() or 
                (last_snapshot_time.hour < settings['hour'] or 
                (last_snapshot_time.hour == settings['hour'] and last_snapshot_time.minute < settings['minute'])))):
            logger.info(f"Monthly snapshot time reached: day {settings['day_of_month']}, time {settings['hour']}:{settings['minute']}")
            return True
    
    return False

def cleanup_old_snapshots(db, retain_days):
    """
    Delete snapshots older than retain_days
    
    Args:
        db: Database instance
        retain_days: Number of days to keep snapshots
    """
    try:
        deleted_count = db.delete_old_snapshots(retain_days)
        if deleted_count > 0:
            logger.info(f"Cleaned up {deleted_count} snapshots older than {retain_days} days")
    except Exception as e:
        logger.error(f"Error cleaning up old snapshots: {str(e)}")
