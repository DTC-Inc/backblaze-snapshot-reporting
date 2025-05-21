def delete_old_snapshots(self, days):
    """Delete snapshots older than the specified days
    
    Args:
        days (int): Number of days to retain snapshots
        
    Returns:
        int: Number of snapshots deleted
    """
    try:
        cutoff_date = datetime.now() - timedelta(days=days)
        cutoff_date_str = cutoff_date.strftime('%Y-%m-%d %H:%M:%S')
        
        with self._get_connection() as conn:
            # First get the IDs of snapshots to delete
            cursor = conn.cursor()
            cursor.execute(
                'SELECT id FROM snapshots WHERE timestamp < ?',
                (cutoff_date_str,)
            )
            snapshot_ids = [row['id'] for row in cursor.fetchall()]
            
            # Delete the related bucket snapshots
            for snapshot_id in snapshot_ids:
                cursor.execute(
                    'DELETE FROM bucket_snapshots WHERE snapshot_id = ?',
                    (snapshot_id,)
                )
            
            # Then delete the snapshots themselves
            cursor.execute(
                'DELETE FROM snapshots WHERE timestamp < ?',
                (cutoff_date_str,)
            )
            
            deleted_count = len(snapshot_ids)
            conn.commit()
            return deleted_count
            
    except Exception as e:
        raise Exception(f"Error deleting old snapshots: {str(e)}")

def get_schedule_settings(self):
    """Get the current snapshot schedule settings from the database
    
    Returns:
        dict: The schedule settings or default settings if not found
    """
    try:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
            SELECT * FROM settings 
            WHERE category = 'snapshot_schedule' 
            ORDER BY id DESC LIMIT 1
            ''')
            row = cursor.fetchone()
            
            if row:
                settings = json.loads(row['settings_json'])
                return settings
            
            # Default settings if not found
            from app.config import (
                SNAPSHOT_SCHEDULE_TYPE, SNAPSHOT_INTERVAL_HOURS,
                SNAPSHOT_HOUR, SNAPSHOT_MINUTE, 
                SNAPSHOT_DAY_OF_WEEK, SNAPSHOT_DAY_OF_MONTH,
                SNAPSHOT_RETAIN_DAYS
            )
            
            return {
                'schedule_type': SNAPSHOT_SCHEDULE_TYPE,
                'interval_hours': SNAPSHOT_INTERVAL_HOURS,
                'hour': SNAPSHOT_HOUR,
                'minute': SNAPSHOT_MINUTE,
                'day_of_week': SNAPSHOT_DAY_OF_WEEK,
                'day_of_month': SNAPSHOT_DAY_OF_MONTH,
                'retain_days': SNAPSHOT_RETAIN_DAYS
            }
            
    except Exception as e:
        # Return default settings on error
        from app.config import (
            SNAPSHOT_SCHEDULE_TYPE, SNAPSHOT_INTERVAL_HOURS,
            SNAPSHOT_HOUR, SNAPSHOT_MINUTE, 
            SNAPSHOT_DAY_OF_WEEK, SNAPSHOT_DAY_OF_MONTH,
            SNAPSHOT_RETAIN_DAYS
        )
        
        return {
            'schedule_type': SNAPSHOT_SCHEDULE_TYPE,
            'interval_hours': SNAPSHOT_INTERVAL_HOURS,
            'hour': SNAPSHOT_HOUR,
            'minute': SNAPSHOT_MINUTE,
            'day_of_week': SNAPSHOT_DAY_OF_WEEK,
            'day_of_month': SNAPSHOT_DAY_OF_MONTH,
            'retain_days': SNAPSHOT_RETAIN_DAYS
        }

def save_schedule_settings(self, settings):
    """Save snapshot schedule settings to the database
    
    Args:
        settings (dict): The schedule settings to save
        
    Returns:
        bool: True if saved successfully
    """
    try:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Ensure settings table exists
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                category TEXT NOT NULL,
                settings_json TEXT NOT NULL
            )
            ''')
            conn.commit()
            
            # Insert new settings
            cursor.execute('''
            INSERT INTO settings (timestamp, category, settings_json)
            VALUES (?, ?, ?)
            ''', (
                datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'snapshot_schedule',
                json.dumps(settings)
            ))
            conn.commit()
            return True
            
    except Exception as e:
        raise Exception(f"Error saving schedule settings: {str(e)}")
