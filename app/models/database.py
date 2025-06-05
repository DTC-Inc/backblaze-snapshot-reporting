import sqlite3
import json
from datetime import datetime, timedelta, timezone
import os
import logging

logger = logging.getLogger(__name__)

class Database:
    def __init__(self, db_path):
        """Initialize database connection"""
        self.db_path = db_path
        logger.info(f"Database class initialized with db_path: {self.db_path}")
        self._create_tables_if_not_exist()

    def _get_connection(self):
        """Get a database connection"""
        logger.info(f"Attempting to connect to SQLite database at: {self.db_path} (UID: {os.geteuid()}, GID: {os.getegid()})")
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
            
            # Webhook events table for storing Backblaze object events
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS webhook_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                event_timestamp TEXT NOT NULL,
                bucket_name TEXT NOT NULL,
                event_type TEXT NOT NULL,
                object_key TEXT,
                object_size INTEGER,
                object_version_id TEXT,
                source_ip TEXT,
                user_agent TEXT,
                request_id TEXT,
                raw_payload TEXT NOT NULL,
                processed BOOLEAN DEFAULT 0,
                created_at TEXT NOT NULL
            )
            ''')
            
            # Bucket configurations table for webhook settings
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS bucket_configurations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bucket_name TEXT NOT NULL UNIQUE,
                webhook_enabled BOOLEAN DEFAULT 0,
                webhook_secret TEXT,
                events_to_track TEXT NOT NULL DEFAULT '["b2:ObjectCreated", "b2:ObjectDeleted"]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            ''')
            
            # Webhook statistics table for tracking webhook activity
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS webhook_statistics (
                date TEXT NOT NULL,
                bucket_name TEXT NOT NULL,
                event_type TEXT NOT NULL,
                event_count INTEGER DEFAULT 0,
                PRIMARY KEY (date, bucket_name, event_type)
            ) WITHOUT ROWID
            ''')
            
            # B2 Buckets table to store canonical list of B2 buckets and their settings
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS b2_buckets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bucket_b2_id TEXT NOT NULL UNIQUE,
                bucket_name TEXT NOT NULL UNIQUE,
                account_b2_id TEXT,
                bucket_type TEXT,
                cors_rules TEXT,
                event_notification_rules TEXT,
                lifecycle_rules TEXT,
                bucket_info TEXT,
                options TEXT,
                file_lock_configuration TEXT,
                default_server_side_encryption TEXT,
                replication_configuration TEXT,
                revision INTEGER,
                last_synced_at TEXT NOT NULL
            )
            ''')
            
            conn.commit()
            
            # Create performance indexes for frequently queried columns
            try:
                # Webhook events indexes
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_webhook_events_timestamp ON webhook_events(timestamp DESC)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_webhook_events_bucket_name ON webhook_events(bucket_name)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_webhook_events_event_type ON webhook_events(event_type)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_webhook_events_created_at ON webhook_events(created_at DESC)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_webhook_events_bucket_type ON webhook_events(bucket_name, event_type)')
                
                # Snapshots indexes
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_snapshots_timestamp ON snapshots(timestamp DESC)')
                
                # Bucket snapshots indexes  
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_bucket_snapshots_snapshot_id ON bucket_snapshots(snapshot_id)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_bucket_snapshots_bucket_name ON bucket_snapshots(bucket_name)')
                
                # Bucket configurations indexes
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_bucket_configurations_bucket_name ON bucket_configurations(bucket_name)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_bucket_configurations_webhook_enabled ON bucket_configurations(webhook_enabled)')
                
                # B2 buckets indexes
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_b2_buckets_bucket_b2_id ON b2_buckets(bucket_b2_id)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_b2_buckets_bucket_name ON b2_buckets(bucket_name)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_b2_buckets_last_synced ON b2_buckets(last_synced_at DESC)')
                
                conn.commit()
                logger.info("Database performance indexes created successfully")
                
            except Exception as e:
                logger.warning(f"Could not create some database indexes (this is normal for existing databases): {e}")
                # Don't fail if indexes already exist or there are other issues

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

    # Webhook-related methods
    
    def save_webhook_event(self, webhook_data):
        """Save a webhook event from Backblaze
        
        Args:
            webhook_data (dict): The webhook event data
            
        Returns:
            int: The ID of the inserted webhook event
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Convert event timestamp to ISO format for consistency
            event_timestamp_str = webhook_data.get('eventTimestamp', '')
            event_timestamp_iso = None
            
            if event_timestamp_str:
                try:
                    # B2 eventTimestamp is in milliseconds since epoch
                    if isinstance(event_timestamp_str, (int, float)):
                        timestamp_dt = datetime.fromtimestamp(event_timestamp_str / 1000.0, tz=timezone.utc)
                    elif isinstance(event_timestamp_str, str):
                        # Try parsing as ISO string first
                        try:
                            timestamp_dt = datetime.fromisoformat(event_timestamp_str.replace('Z', '+00:00'))
                        except ValueError:
                            # Fallback: assume it's milliseconds as string
                            timestamp_dt = datetime.fromtimestamp(int(event_timestamp_str) / 1000.0, tz=timezone.utc)
                    else:
                        timestamp_dt = datetime.now(timezone.utc)
                        
                    event_timestamp_iso = timestamp_dt.isoformat()
                except (ValueError, TypeError) as e:
                    logger.warning(f"Error parsing event timestamp '{event_timestamp_str}': {e}")
                    event_timestamp_iso = datetime.now(timezone.utc).isoformat()
            else:
                event_timestamp_iso = datetime.now(timezone.utc).isoformat()
            
            current_time = datetime.now().isoformat()
            
            # Handle object_size conversion and validation
            object_size = webhook_data.get('objectSize')
            if object_size is not None:
                try:
                    # Convert to integer, handle string numbers
                    object_size = int(object_size)
                    # Ensure non-negative values
                    if object_size < 0:
                        logger.warning(f"Negative object_size ({object_size}) received, setting to 0")
                        object_size = 0
                except (ValueError, TypeError) as e:
                    logger.warning(f"Invalid object_size value '{object_size}': {e}. Setting to 0.")
                    object_size = 0
            else:
                # B2 might not send objectSize for some event types (e.g., bucket events)
                object_size = 0
                logger.debug(f"No objectSize in webhook data for event type: {webhook_data.get('eventType')}")
            
            cursor.execute('''
            INSERT INTO webhook_events (
                timestamp, event_timestamp, bucket_name, event_type, object_key,
                object_size, object_version_id, source_ip, user_agent, request_id,
                raw_payload, processed, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                event_timestamp_iso,  # Use converted timestamp  
                webhook_data.get('bucketName', ''),
                webhook_data.get('eventType', ''),
                webhook_data.get('objectName'),
                object_size,  # Use validated and converted object_size
                webhook_data.get('objectVersionId'),
                webhook_data.get('sourceIpAddress'),
                webhook_data.get('userAgent'),
                webhook_data.get('eventId'),
                json.dumps(webhook_data),
                False,
                current_time
            ))
            
            event_id = cursor.lastrowid
            
            # Update webhook statistics
            date_str = datetime.now().strftime('%Y-%m-%d')
            cursor.execute('''
            INSERT OR REPLACE INTO webhook_statistics (date, bucket_name, event_type, event_count)
            VALUES (?, ?, ?, COALESCE((
                SELECT event_count FROM webhook_statistics 
                WHERE date = ? AND bucket_name = ? AND event_type = ?
            ), 0) + 1)
            ''', (
                date_str, webhook_data.get('bucketName', ''), 
                webhook_data.get('eventType', ''),
                date_str, webhook_data.get('bucketName', ''), 
                webhook_data.get('eventType', '')
            ))
            
            conn.commit()
            return event_id

    def get_webhook_events(self, limit=100, bucket_name=None, event_type=None):
        """Get webhook events with optional filtering
        
        Args:
            limit (int): Maximum number of events to retrieve
            bucket_name (str): Filter by bucket name
            event_type (str): Filter by event type
            
        Returns:
            list: List of webhook event records
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            query = 'SELECT * FROM webhook_events WHERE 1=1'
            params = []
            
            if bucket_name:
                query += ' AND bucket_name = ?'
                params.append(bucket_name)
                
            if event_type:
                query += ' AND event_type = ?'
                params.append(event_type)
                
            query += ' ORDER BY created_at DESC LIMIT ?'
            params.append(limit)
            
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def get_webhook_statistics(self, days=30):
        """Get webhook statistics for the past specified number of days
        
        Args:
            days (int): Number of days to retrieve statistics for
            
        Returns:
            list: List of webhook statistics
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
            
            cursor.execute('''
            SELECT date, bucket_name, event_type, event_count
            FROM webhook_statistics
            WHERE date >= ?
            ORDER BY date DESC, bucket_name, event_type
            ''', (start_date,))
            
            return [dict(row) for row in cursor.fetchall()]

    def get_bucket_configuration(self, bucket_name):
        """Get webhook configuration for a specific bucket
        
        Args:
            bucket_name (str): Name of the bucket
            
        Returns:
            dict: Bucket configuration or None if not found
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
            SELECT * FROM bucket_configurations
            WHERE bucket_name = ?
            ''', (bucket_name,))
            
            row = cursor.fetchone()
            if row:
                config = dict(row)
                config['events_to_track'] = json.loads(config['events_to_track'])
                return config
            return None

    def save_bucket_configuration(self, bucket_name, webhook_enabled=False, webhook_secret=None, events_to_track=None):
        """Save or update webhook configuration for a bucket
        
        Args:
            bucket_name (str): Name of the bucket
            webhook_enabled (bool): Whether webhooks are enabled
            webhook_secret (str): Secret for webhook verification
            events_to_track (list): List of event types to track
            
        Returns:
            bool: True if saved successfully
        """
        if events_to_track is None:
            events_to_track = ["b2:ObjectCreated", "b2:ObjectDeleted"]
            
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            current_time = datetime.now().isoformat()
            
            cursor.execute('''
            INSERT OR REPLACE INTO bucket_configurations (
                bucket_name, webhook_enabled, webhook_secret, events_to_track,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, 
                COALESCE((SELECT created_at FROM bucket_configurations WHERE bucket_name = ?), ?),
                ?
            )
            ''', (
                bucket_name, webhook_enabled, webhook_secret, json.dumps(events_to_track),
                bucket_name, current_time, current_time
            ))
            
            conn.commit()
            return True

    def get_all_bucket_configurations(self):
        """Get all bucket configurations
        
        Returns:
            list: List of all bucket configurations
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
            SELECT * FROM bucket_configurations
            ORDER BY bucket_name
            ''')
            
            configs = []
            for row in cursor.fetchall():
                config = dict(row)
                config['events_to_track'] = json.loads(config['events_to_track'])
                configs.append(config)
                
            return configs

    def delete_bucket_configuration(self, bucket_name):
        """Delete webhook configuration for a bucket
        
        Args:
            bucket_name (str): Name of the bucket
            
        Returns:
            bool: True if deleted successfully
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
            DELETE FROM bucket_configurations
            WHERE bucket_name = ?
            ''', (bucket_name,))
            
            conn.commit()
            return cursor.rowcount > 0

    # Methods for the b2_buckets table
    def save_b2_bucket_details(self, bucket_details_list):
        """Save or update a list of B2 bucket details.
        
        Args:
            bucket_details_list (list): A list of dictionaries, where each dictionary
                                     contains the details of a B2 bucket.
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            current_time = datetime.now().isoformat()
            
            for bucket in bucket_details_list:
                logger.debug(f"Saving/Updating B2 bucket details for: {bucket.get('bucketName')}")
                cursor.execute('''
                    INSERT OR REPLACE INTO b2_buckets (
                        bucket_b2_id, bucket_name, account_b2_id, bucket_type,
                        cors_rules, event_notification_rules, lifecycle_rules,
                        bucket_info, options, file_lock_configuration,
                        default_server_side_encryption, replication_configuration,
                        revision, last_synced_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    bucket.get('bucketId'),
                    bucket.get('bucketName'),
                    bucket.get('accountId'),
                    bucket.get('bucketType'),
                    json.dumps(bucket.get('corsRules', [])),
                    json.dumps(bucket.get('eventNotificationRules', [])),
                    json.dumps(bucket.get('lifecycleRules', [])),
                    json.dumps(bucket.get('bucketInfo', {})),
                    json.dumps(bucket.get('options', {})), # New field from B2 API v3
                    json.dumps(bucket.get('fileLockConfiguration', {})), # New field from B2 API v3
                    json.dumps(bucket.get('defaultServerSideEncryption', {})), # New field from B2 API v3
                    json.dumps(bucket.get('replicationConfiguration', {})), # New field from B2 API v3
                    bucket.get('revision'),
                    current_time
                ))
            conn.commit()
            logger.info(f"Successfully saved/updated details for {len(bucket_details_list)} B2 buckets.")

    def get_all_b2_buckets(self):
        """Get all B2 buckets from the b2_buckets table, joined with local webhook configuration."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # Join b2_buckets with bucket_configurations to get webhook_secret and webhook_enabled status
            # Use LEFT JOIN to ensure all buckets from b2_buckets are listed, even if no local config exists yet.
            cursor.execute("""
                SELECT b.*, bc.webhook_enabled, bc.webhook_secret, bc.events_to_track
                FROM b2_buckets b
                LEFT JOIN bucket_configurations bc ON b.bucket_name = bc.bucket_name
                ORDER BY b.bucket_name
            """)
            buckets = [dict(row) for row in cursor.fetchall()]
            # Deserialize JSON fields
            for bucket in buckets:
                for field in ['cors_rules', 'event_notification_rules', 'lifecycle_rules', 'bucket_info', 'options', 'file_lock_configuration', 'default_server_side_encryption', 'replication_configuration']:
                    if bucket.get(field) and isinstance(bucket[field], str): # Check if it's a string before trying to load
                        try:
                            bucket[field] = json.loads(bucket[field])
                        except json.JSONDecodeError:
                            logger.warning(f"Failed to decode JSON for field {field} in bucket {bucket.get('bucket_name')}")
                            bucket[field] = None 
                # Ensure events_to_track is also deserialized if it came from bucket_configurations
                if bucket.get('events_to_track') and isinstance(bucket['events_to_track'], str):
                    try:
                        bucket['events_to_track'] = json.loads(bucket['events_to_track'])
                    except json.JSONDecodeError:
                        logger.warning(f"Failed to decode JSON for field events_to_track in bucket {bucket.get('bucket_name')}")
                        bucket['events_to_track'] = []
                elif bucket.get('events_to_track') is None: # If no local config, default to empty list
                    bucket['events_to_track'] = []

            return buckets

    def get_b2_bucket_by_name(self, bucket_name):
        """Get a specific B2 bucket by its name."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM b2_buckets WHERE bucket_name = ?", (bucket_name,))
            row = cursor.fetchone()
            if row:
                bucket = dict(row)
                # Deserialize JSON fields
                for field in ['cors_rules', 'event_notification_rules', 'lifecycle_rules', 'bucket_info', 'options', 'file_lock_configuration', 'default_server_side_encryption', 'replication_configuration']:
                    if bucket.get(field):
                        try:
                            bucket[field] = json.loads(bucket[field])
                        except json.JSONDecodeError:
                            logger.warning(f"Failed to decode JSON for field {field} in bucket {bucket.get('bucket_name')}")
                            bucket[field] = None
                return bucket
            return None

    def get_b2_bucket_by_b2_id(self, bucket_b2_id):
        """Get a specific B2 bucket by its B2 bucket ID."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM b2_buckets WHERE bucket_b2_id = ?", (bucket_b2_id,))
            row = cursor.fetchone()
            if row:
                bucket = dict(row)
                # Deserialize JSON fields (same as get_b2_bucket_by_name)
                for field in ['cors_rules', 'event_notification_rules', 'lifecycle_rules', 'bucket_info', 'options', 'file_lock_configuration', 'default_server_side_encryption', 'replication_configuration']:
                    if bucket.get(field):
                        try:
                            bucket[field] = json.loads(bucket[field])
                        except json.JSONDecodeError:
                            logger.warning(f"Failed to decode JSON for field {field} in bucket {bucket.get('bucket_name')} (ID: {bucket_b2_id})")
                            bucket[field] = None # Or some default, like {} or []
                return bucket
            return None

    # Alias kept for backward compatibility with earlier code paths
    def get_b2_bucket_by_id(self, bucket_b2_id):
        """Alias to get_b2_bucket_by_b2_id for legacy callers."""
        return self.get_b2_bucket_by_b2_id(bucket_b2_id)

    # --- Dashboard Specific Methods ---
    def get_object_operation_stats_for_period(self, start_date_str, end_date_str, bucket_name=None):
        """Calculate object operation statistics for a given period and optional bucket."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Build the WHERE clause
            where_clause = "WHERE event_timestamp >= ? AND event_timestamp <= ?"
            params = [start_date_str, end_date_str]
            
            if bucket_name:
                where_clause += " AND bucket_name = ?"
                params.append(bucket_name)

            # Objects Added - Fixed SQL syntax with proper subquery
            added_query = f"""
                SELECT COUNT(*), COALESCE(SUM(object_size), 0) 
                FROM (
                    SELECT DISTINCT request_id, object_size 
                    FROM webhook_events 
                    {where_clause} AND event_type LIKE 'b2:ObjectCreated:%'
                )
            """
            cursor.execute(added_query, params)
            added_row = cursor.fetchone()
            objects_added = added_row[0] if added_row and added_row[0] is not None else 0
            size_added = added_row[1] if added_row and added_row[1] is not None else 0

            # Objects Deleted - Fixed SQL syntax with proper subquery
            deleted_query = f"""
                SELECT COUNT(*), COALESCE(SUM(object_size), 0) 
                FROM (
                    SELECT DISTINCT request_id, object_size 
                    FROM webhook_events 
                    {where_clause} AND event_type LIKE 'b2:ObjectDeleted:%'
                )
            """
            cursor.execute(deleted_query, params)
            deleted_row = cursor.fetchone()
            objects_deleted = deleted_row[0] if deleted_row and deleted_row[0] is not None else 0
            size_deleted = deleted_row[1] if deleted_row and deleted_row[1] is not None else 0
            
            return {
                'objects_added': objects_added,
                'size_added': size_added,
                'objects_deleted': objects_deleted,
                'size_deleted': size_deleted,
                'net_object_change': objects_added - objects_deleted,
                'net_size_change': size_added - size_deleted,
                'start_date': start_date_str,
                'end_date': end_date_str,
                'bucket_name_filter': bucket_name
            }

    def get_daily_object_operation_breakdown(self, start_date_str, end_date_str, bucket_name=None):
        """Get a daily breakdown of object operations."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            results = [] 
            # Ensure we iterate through all days in the range for complete data
            try:
                current_date = datetime.fromisoformat(start_date_str.split('T')[0])
                end_date_obj = datetime.fromisoformat(end_date_str.split('T')[0])
            except ValueError:
                 # Fallback if only date string is provided without time
                current_date = datetime.strptime(start_date_str, '%Y-%m-%d')
                end_date_obj = datetime.strptime(end_date_str, '%Y-%m-%d')

            while current_date <= end_date_obj:
                day_start = current_date.strftime('%Y-%m-%dT00:00:00')
                day_end = current_date.strftime('%Y-%m-%dT23:59:59.999999')
                
                day_stats = self.get_object_operation_stats_for_period(day_start, day_end, bucket_name)
                results.append({
                    'date': current_date.strftime('%Y-%m-%d'),
                    'objects_added': day_stats['objects_added'],
                    'size_added': day_stats['size_added'],
                    'objects_deleted': day_stats['objects_deleted'],
                    'size_deleted': day_stats['size_deleted']
                })
                current_date += timedelta(days=1)
            return results

    def get_all_bucket_names_from_webhooks(self):
        """Get a list of all unique bucket names that have webhook events."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT bucket_name FROM webhook_events ORDER BY bucket_name")
            return [row['bucket_name'] for row in cursor.fetchall()]

    def get_top_buckets_by_size(self, operation_type='added', limit=10, start_date_str=None, end_date_str=None):
        """Get top N buckets by total data size for a given operation type and period."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if operation_type == 'added':
                event_type_pattern = 'b2:ObjectCreated:%'
            elif operation_type == 'removed':
                event_type_pattern = 'b2:ObjectDeleted:%'
            else:
                raise ValueError("Invalid operation_type. Must be 'added' or 'removed'.")

            query = "SELECT bucket_name, SUM(object_size) as total_size FROM webhook_events WHERE event_type LIKE ?"
            params = [event_type_pattern]

            if start_date_str and end_date_str:
                query += " AND event_timestamp >= ? AND event_timestamp <= ?"
                params.extend([start_date_str, end_date_str])
            
            query += " GROUP BY bucket_name HAVING total_size > 0 ORDER BY total_size DESC LIMIT ?"
            params.append(limit)
            
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def get_top_buckets_by_object_count(self, operation_type='added', limit=10, start_date_str=None, end_date_str=None):
        """Get top N buckets by total object count for a given operation type and period."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if operation_type == 'added':
                event_type_pattern = 'b2:ObjectCreated:%'
            elif operation_type == 'removed':
                event_type_pattern = 'b2:ObjectDeleted:%'
            else:
                raise ValueError("Invalid operation_type. Must be 'added' or 'removed'.")

            # Counting distinct request_id to count unique events more accurately
            query = "SELECT bucket_name, COUNT(DISTINCT request_id) as total_objects FROM webhook_events WHERE event_type LIKE ?"
            params = [event_type_pattern]

            if start_date_str and end_date_str:
                query += " AND event_timestamp >= ? AND event_timestamp <= ?"
                params.extend([start_date_str, end_date_str])
            
            query += " GROUP BY bucket_name HAVING total_objects > 0 ORDER BY total_objects DESC LIMIT ?"
            params.append(limit)
            
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def get_stale_buckets(self, limit=10, active_threshold_days=90):
        """Get N buckets that have not had recent 'created' activity.
           'Stale' is defined as no b2:ObjectCreated:* event within active_threshold_days.
           Returns buckets ordered by the oldest last creation event (or those with no creation events first).
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Get all known B2 bucket names (master list)
            cursor.execute("SELECT DISTINCT bucket_name FROM b2_buckets ORDER BY bucket_name")
            all_b2_bucket_names = [row['bucket_name'] for row in cursor.fetchall()]
            
            if not all_b2_bucket_names:
                 # Fallback to webhook event buckets if b2_buckets is empty for some reason
                cursor.execute("SELECT DISTINCT bucket_name FROM webhook_events ORDER BY bucket_name")
                all_b2_bucket_names = [row['bucket_name'] for row in cursor.fetchall()]

            bucket_last_creation = []
            cutoff_date_str = (datetime.utcnow() - timedelta(days=active_threshold_days)).isoformat()

            for bucket_name in all_b2_bucket_names:
                cursor.execute("""
                    SELECT MAX(event_timestamp) 
                    FROM webhook_events 
                    WHERE bucket_name = ? AND event_type LIKE 'b2:ObjectCreated:%'""", 
                    (bucket_name,)
                )
                row = cursor.fetchone()
                last_creation_timestamp = row[0] if row else None
                
                if last_creation_timestamp is None:
                    # Buckets with no creation events are considered most stale
                    bucket_last_creation.append({'bucket_name': bucket_name, 'last_creation_event': None, 'sort_key': '0'}) # Sort None first
                elif last_creation_timestamp < cutoff_date_str:
                    # Buckets whose last creation event is older than the threshold
                    bucket_last_creation.append({'bucket_name': bucket_name, 'last_creation_event': last_creation_timestamp, 'sort_key': last_creation_timestamp})
            
            # Sort: None (no creation events) first, then by oldest timestamp
            bucket_last_creation.sort(key=lambda x: x['sort_key'])
            
            return bucket_last_creation[:limit]

    def get_top_largest_objects(self, limit=10, start_date_str=None, end_date_str=None, bucket_name=None):
        """Get the top N largest objects from webhook events"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Build the WHERE clause
            where_clause = "WHERE event_type LIKE 'b2:ObjectCreated:%' AND object_size > 0"
            params = []
            
            if start_date_str and end_date_str:
                where_clause += " AND created_at >= ? AND created_at <= ?"
                params.extend([start_date_str, end_date_str])
            
            if bucket_name:
                where_clause += " AND bucket_name = ?"
                params.append(bucket_name)
            
            # Query to get top largest objects (using DISTINCT on request_id to avoid duplicates)
            query = f"""
                SELECT 
                    request_id,
                    object_key,
                    object_size,
                    bucket_name,
                    event_type,
                    created_at,
                    event_timestamp
                FROM (
                    SELECT DISTINCT 
                        request_id,
                        FIRST_VALUE(object_key) OVER (PARTITION BY request_id ORDER BY created_at DESC) as object_key,
                        FIRST_VALUE(object_size) OVER (PARTITION BY request_id ORDER BY created_at DESC) as object_size,
                        FIRST_VALUE(bucket_name) OVER (PARTITION BY request_id ORDER BY created_at DESC) as bucket_name,
                        FIRST_VALUE(event_type) OVER (PARTITION BY request_id ORDER BY created_at DESC) as event_type,
                        FIRST_VALUE(created_at) OVER (PARTITION BY request_id ORDER BY created_at DESC) as created_at,
                        FIRST_VALUE(event_timestamp) OVER (PARTITION BY request_id ORDER BY created_at DESC) as event_timestamp
                    FROM webhook_events 
                    {where_clause}
                )
                ORDER BY object_size DESC 
                LIMIT ?
            """
            params.append(limit)
            
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def save_webhook_events_batch(self, webhook_events_list):
        """Save multiple webhook events in a single transaction to reduce lock contention
        
        Args:
            webhook_events_list (list): List of webhook event dictionaries
            
        Returns:
            int: Number of events successfully saved
        """
        if not webhook_events_list:
            return 0
            
        with self._get_connection() as conn:
            cursor = conn.cursor()
            current_time = datetime.now().isoformat()
            saved_count = 0
            
            try:
                # Prepare batch data
                batch_events = []
                batch_stats = {}
                
                for webhook_data in webhook_events_list:
                    # Convert B2's eventTimestamp (milliseconds since epoch) to ISO format
                    event_timestamp_iso = current_time  # default fallback
                    if 'eventTimestamp' in webhook_data:
                        try:
                            # B2 sends eventTimestamp as milliseconds since epoch
                            timestamp_ms = int(webhook_data['eventTimestamp'])
                            timestamp_dt = datetime.fromtimestamp(timestamp_ms / 1000.0)
                            event_timestamp_iso = timestamp_dt.isoformat()
                        except (ValueError, TypeError) as e:
                            logger.warning(f"Could not parse eventTimestamp {webhook_data.get('eventTimestamp')}: {e}")
                            # Keep current_time as fallback
                    
                    # Prepare event data for batch insert
                    event_tuple = (
                        event_timestamp_iso,  # Use converted timestamp
                        event_timestamp_iso,  # Use converted timestamp  
                        webhook_data.get('bucketName', ''),
                        webhook_data.get('eventType', ''),
                        webhook_data.get('objectName'),
                        webhook_data.get('objectSize'),
                        webhook_data.get('objectVersionId'),
                        webhook_data.get('sourceIpAddress'),
                        webhook_data.get('userAgent'),
                        webhook_data.get('eventId'),
                        json.dumps(webhook_data),
                        False,
                        current_time
                    )
                    batch_events.append(event_tuple)
                    
                    # Aggregate statistics
                    date_str = datetime.now().strftime('%Y-%m-%d')
                    bucket_name = webhook_data.get('bucketName', '')
                    event_type = webhook_data.get('eventType', '')
                    stat_key = (date_str, bucket_name, event_type)
                    batch_stats[stat_key] = batch_stats.get(stat_key, 0) + 1
                
                # Batch insert events
                cursor.executemany('''
                INSERT INTO webhook_events (
                    timestamp, event_timestamp, bucket_name, event_type,
                    object_key, object_size, object_version_id,
                    source_ip, user_agent, request_id, raw_payload,
                    processed, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', batch_events)
                
                saved_count = len(batch_events)
                
                # Batch update statistics
                for (date_str, bucket_name, event_type), count in batch_stats.items():
                    cursor.execute('''
                    INSERT OR REPLACE INTO webhook_statistics (date, bucket_name, event_type, event_count)
                    VALUES (?, ?, ?, COALESCE((
                        SELECT event_count FROM webhook_statistics 
                        WHERE date = ? AND bucket_name = ? AND event_type = ?
                    ), 0) + ?)
                    ''', (
                        date_str, bucket_name, event_type,
                        date_str, bucket_name, event_type,
                        count
                    ))
                
                conn.commit()
                logger.info(f"Batch saved {saved_count} webhook events successfully")
                return saved_count
                
            except Exception as e:
                logger.error(f"Error in batch save webhook events: {e}")
                conn.rollback()
                return 0
