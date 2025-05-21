import sqlite3
import json
from datetime import datetime, timedelta
import os

class Database:
    def __init__(self, db_path):
        """Initialize database connection"""
        self.db_path = db_path
        self._create_tables_if_not_exist()

    def _get_connection(self):
        """Get a database connection"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _create_tables_if_not_exist(self):
        """Create required tables if they don't exist"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Snapshots table to store overall account data
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                total_storage_bytes INTEGER NOT NULL,
                total_storage_cost REAL NOT NULL,
                total_download_bytes INTEGER NOT NULL,
                total_download_cost REAL NOT NULL,
                total_api_calls INTEGER NOT NULL,
                total_api_cost REAL NOT NULL,
                total_cost REAL NOT NULL,
                raw_data TEXT NOT NULL
            )
            ''')
            
            # Bucket snapshots table for per-bucket data
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS bucket_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_id INTEGER NOT NULL,
                bucket_name TEXT NOT NULL,
                storage_bytes INTEGER NOT NULL,
                storage_cost REAL NOT NULL,
                download_bytes INTEGER NOT NULL,
                download_cost REAL NOT NULL,
                api_calls INTEGER NOT NULL,
                api_cost REAL NOT NULL,
                total_cost REAL NOT NULL,
                FOREIGN KEY (snapshot_id) REFERENCES snapshots (id)
            )
            ''')
            
            # Notification history table for tracking email notifications
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS notification_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                type TEXT NOT NULL,
                details TEXT NOT NULL,
                recipients TEXT,
                status TEXT NOT NULL
            )
            ''')
            
            conn.commit()

    def save_snapshot(self, snapshot_data):
        """Save a new snapshot of Backblaze usage data"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Insert the main snapshot
            cursor.execute('''
            INSERT INTO snapshots (
                timestamp, total_storage_bytes, total_storage_cost,
                total_download_bytes, total_download_cost,
                total_api_calls, total_api_cost,
                total_cost, raw_data
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                datetime.now().isoformat(),
                snapshot_data['total_storage_bytes'],
                snapshot_data['total_storage_cost'],
                snapshot_data['total_download_bytes'],
                snapshot_data['total_download_cost'],
                snapshot_data['total_api_calls'],
                snapshot_data['total_api_cost'],
                snapshot_data['total_cost'],
                json.dumps(snapshot_data['raw_data'])
            ))
            
            snapshot_id = cursor.lastrowid
            
            # Insert bucket-specific data
            for bucket in snapshot_data['buckets']:
                cursor.execute('''
                INSERT INTO bucket_snapshots (
                    snapshot_id, bucket_name, storage_bytes, storage_cost,
                    download_bytes, download_cost, api_calls, api_cost, total_cost
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    snapshot_id,
                    bucket['name'],
                    bucket['storage_bytes'],
                    bucket['storage_cost'],
                    bucket['download_bytes'],
                    bucket['download_cost'],
                    bucket['api_calls'],
                    bucket['api_cost'],
                    bucket['total_cost']
                ))
            
            conn.commit()
            return snapshot_id

    def get_latest_snapshots(self, limit=30):
        """Get the latest snapshots"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
            SELECT * FROM snapshots
            ORDER BY timestamp DESC
            LIMIT ?
            ''', (limit,))
            return [dict(row) for row in cursor.fetchall()]

    def get_snapshot_by_id(self, snapshot_id):
        """Get a snapshot by ID with its bucket data"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Get the main snapshot
            cursor.execute('SELECT * FROM snapshots WHERE id = ?', (snapshot_id,))
            snapshot = dict(cursor.fetchone())
            
            # Get the bucket data for this snapshot
            cursor.execute('''
            SELECT * FROM bucket_snapshots
            WHERE snapshot_id = ?
            ORDER BY total_cost DESC
            ''', (snapshot_id,))
            
            snapshot['buckets'] = [dict(row) for row in cursor.fetchall()]
            return snapshot

    def get_cost_trends(self, days=30):
        """Get cost trends for the past specified number of days"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
            SELECT timestamp, total_storage_cost, total_download_cost, total_api_cost, total_cost
            FROM snapshots
            ORDER BY timestamp DESC
            LIMIT ?
            ''', (days,))
            return [dict(row) for row in cursor.fetchall()]

    def detect_significant_changes(self, threshold_percentage):
        """Detect significant changes in costs between the last two snapshots"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
            SELECT * FROM snapshots
            ORDER BY timestamp DESC
            LIMIT 2
            ''')
            
            snapshots = [dict(row) for row in cursor.fetchall()]
            if len(snapshots) < 2:
                return None  # Not enough data for comparison
                
            latest = snapshots[0]
            previous = snapshots[1]
            
            changes = {
                'storage': self._calculate_percent_change(
                    previous['total_storage_cost'], latest['total_storage_cost']),
                'download': self._calculate_percent_change(
                    previous['total_download_cost'], latest['total_download_cost']),
                'api': self._calculate_percent_change(
                    previous['total_api_cost'], latest['total_api_cost']),
                'total': self._calculate_percent_change(
                    previous['total_cost'], latest['total_cost'])
            }
            
            significant_changes = {}
            for category, change in changes.items():
                if abs(change['percent']) >= threshold_percentage:
                    significant_changes[category] = change
                    
            if significant_changes:
                # Also fetch bucket-level changes
                cursor.execute('''
                SELECT b1.bucket_name, b1.total_cost as latest_cost, b2.total_cost as previous_cost
                FROM bucket_snapshots b1
                JOIN bucket_snapshots b2 ON b1.bucket_name = b2.bucket_name
                WHERE b1.snapshot_id = ? AND b2.snapshot_id = ?
                ''', (latest['id'], previous['id']))
                
                bucket_changes = []
                for row in cursor.fetchall():
                    change = self._calculate_percent_change(row['previous_cost'], row['latest_cost'])
                    if abs(change['percent']) >= threshold_percentage:
                        bucket_changes.append({
                            'bucket_name': row['bucket_name'],
                            'change': change
                        })
                
                if bucket_changes:
                    significant_changes['buckets'] = sorted(
                        bucket_changes, 
                        key=lambda x: abs(x['change']['percent']), 
                        reverse=True
                    )
            
            return significant_changes if significant_changes else None

    @staticmethod
    def _calculate_percent_change(old_value, new_value):
        """Calculate the percentage change between two values"""
        if old_value == 0:
            percent = 100 if new_value > 0 else 0
        else:
            percent = ((new_value - old_value) / old_value) * 100
            
        return {
            'from': old_value,
            'to': new_value,
            'absolute': new_value - old_value,
            'percent': percent
        }

    def log_notification(self, notification_type, details, recipients, status):
        """Log a notification event in the database
        
        Args:
            notification_type (str): Type of notification (e.g., 'cost_alert', 'test')
            details (str): Details about the notification
            recipients (list): List of email recipients
            status (str): Status of the notification ('success', 'failed')
        
        Returns:
            int: The ID of the inserted notification record
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            recipients_str = ','.join(recipients) if recipients else ''
            
            cursor.execute('''
            INSERT INTO notification_history (
                timestamp, type, details, recipients, status
            ) VALUES (?, ?, ?, ?, ?)
            ''', (
                datetime.now().isoformat(),
                notification_type,
                details,
                recipients_str,
                status
            ))
            
            conn.commit()
            return cursor.lastrowid
    
    def get_notification_history(self, limit=50):
        """Get notification history
        
        Args:
            limit (int): Maximum number of notifications to retrieve
            
        Returns:
            list: List of notification records
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
            SELECT * FROM notification_history
            ORDER BY timestamp DESC
            LIMIT ?
            ''', (limit,))
            
            return [dict(row) for row in cursor.fetchall()]
    
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
