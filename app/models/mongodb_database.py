"""
MongoDB database implementation for high-volume webhook events
Provides the same interface as the SQLite Database class
"""
import json
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import os

try:
    from pymongo import MongoClient, ASCENDING, DESCENDING
    from pymongo.errors import DuplicateKeyError, PyMongoError
    from bson import ObjectId
    MONGODB_AVAILABLE = True
except ImportError:
    MONGODB_AVAILABLE = False

logger = logging.getLogger(__name__)

class MongoDatabase:
    def __init__(self, connection_string):
        """Initialize MongoDB connection"""
        if not MONGODB_AVAILABLE:
            raise ImportError("pymongo is required for MongoDB support. Install with: pip install pymongo")
        
        self.connection_string = connection_string
        self.client = None
        self.db = None
        
        # Parse database name from connection string
        if 'mongodb://' in connection_string:
            # Extract database name from connection string
            db_name = connection_string.split('/')[-1]
            if '?' in db_name:
                db_name = db_name.split('?')[0]
        else:
            db_name = 'bbssr_db'
        
        self.db_name = db_name
        logger.info(f"MongoDB database initialized with connection: {connection_string}")
        self._connect()
        self._create_indexes()

    def _connect(self):
        """Connect to MongoDB"""
        try:
            self.client = MongoClient(self.connection_string, serverSelectionTimeoutMS=5000)
            # Test connection
            self.client.admin.command('ping')
            self.db = self.client[self.db_name]
            logger.info(f"Connected to MongoDB database: {self.db_name}")
        except Exception as e:
            logger.error(f"Failed to connect to MongoDB: {e}")
            raise

    def _create_indexes(self):
        """Create performance indexes for frequently queried collections"""
        try:
            # Webhook events indexes (most important for high volume)
            webhook_events = self.db.webhook_events
            webhook_events.create_index([("timestamp", DESCENDING)])
            webhook_events.create_index([("bucket_name", ASCENDING)])
            webhook_events.create_index([("event_type", ASCENDING)])
            webhook_events.create_index([("created_at", DESCENDING)])
            webhook_events.create_index([("bucket_name", ASCENDING), ("event_type", ASCENDING)])
            
            # Snapshots indexes
            snapshots = self.db.snapshots
            snapshots.create_index([("timestamp", DESCENDING)])
            
            # Bucket snapshots indexes
            bucket_snapshots = self.db.bucket_snapshots
            bucket_snapshots.create_index([("snapshot_id", ASCENDING)])
            bucket_snapshots.create_index([("bucket_name", ASCENDING)])
            
            # Bucket configurations indexes
            bucket_configurations = self.db.bucket_configurations
            bucket_configurations.create_index([("bucket_name", ASCENDING)], unique=True)
            bucket_configurations.create_index([("webhook_enabled", ASCENDING)])
            
            # B2 buckets indexes
            b2_buckets = self.db.b2_buckets
            b2_buckets.create_index([("bucket_b2_id", ASCENDING)], unique=True)
            b2_buckets.create_index([("bucket_name", ASCENDING)], unique=True)
            b2_buckets.create_index([("last_synced_at", DESCENDING)])
            
            logger.info("MongoDB indexes created successfully")
            
        except Exception as e:
            logger.warning(f"Could not create some MongoDB indexes: {e}")

    def save_snapshot(self, snapshot_data):
        """Save a new snapshot of Backblaze usage data"""
        try:
            # Insert the main snapshot
            snapshot_doc = {
                "timestamp": datetime.now().isoformat(),
                "total_storage_bytes": snapshot_data['total_storage_bytes'],
                "total_storage_cost": snapshot_data['total_storage_cost'],
                "total_download_bytes": snapshot_data['total_download_bytes'],
                "total_download_cost": snapshot_data['total_download_cost'],
                "total_api_calls": snapshot_data['total_api_calls'],
                "total_api_cost": snapshot_data['total_api_cost'],
                "total_cost": snapshot_data['total_cost'],
                "raw_data": snapshot_data['raw_data']
            }
            
            result = self.db.snapshots.insert_one(snapshot_doc)
            snapshot_id = str(result.inserted_id)
            
            # Insert bucket-specific data
            bucket_docs = []
            for bucket in snapshot_data['buckets']:
                bucket_doc = {
                    "snapshot_id": snapshot_id,
                    "bucket_name": bucket['name'],
                    "storage_bytes": bucket['storage_bytes'],
                    "storage_cost": bucket['storage_cost'],
                    "download_bytes": bucket['download_bytes'],
                    "download_cost": bucket['download_cost'],
                    "api_calls": bucket['api_calls'],
                    "api_cost": bucket['api_cost'],
                    "total_cost": bucket['total_cost']
                }
                bucket_docs.append(bucket_doc)
            
            if bucket_docs:
                self.db.bucket_snapshots.insert_many(bucket_docs)
            
            return snapshot_id
            
        except Exception as e:
            logger.error(f"Error saving snapshot to MongoDB: {e}")
            raise

    def get_latest_snapshots(self, limit=30):
        """Get the latest snapshots"""
        try:
            cursor = self.db.snapshots.find().sort("timestamp", DESCENDING).limit(limit)
            snapshots = []
            for doc in cursor:
                doc['id'] = str(doc['_id'])
                del doc['_id']
                snapshots.append(doc)
            return snapshots
        except Exception as e:
            logger.error(f"Error getting latest snapshots from MongoDB: {e}")
            return []

    def get_snapshot_by_id(self, snapshot_id):
        """Get a snapshot by ID with its bucket data"""
        try:
            # Convert string ID to ObjectId if needed
            if isinstance(snapshot_id, str):
                try:
                    object_id = ObjectId(snapshot_id)
                except:
                    # If it's not a valid ObjectId, treat as string
                    object_id = snapshot_id
            else:
                object_id = snapshot_id
            
            # Get the main snapshot
            snapshot_doc = self.db.snapshots.find_one({"_id": object_id})
            if not snapshot_doc:
                return None
            
            snapshot = dict(snapshot_doc)
            snapshot['id'] = str(snapshot['_id'])
            del snapshot['_id']
            
            # Get the bucket data for this snapshot
            bucket_cursor = self.db.bucket_snapshots.find(
                {"snapshot_id": snapshot['id']}
            ).sort("total_cost", DESCENDING)
            
            buckets = []
            for bucket_doc in bucket_cursor:
                bucket = dict(bucket_doc)
                if '_id' in bucket:
                    del bucket['_id']
                buckets.append(bucket)
            
            snapshot['buckets'] = buckets
            return snapshot
            
        except Exception as e:
            logger.error(f"Error getting snapshot by ID from MongoDB: {e}")
            return None

    def save_webhook_event(self, webhook_data):
        """Save a webhook event - optimized for high volume"""
        try:
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
            
            # Extract fields from webhook data
            event_doc = {
                "timestamp": webhook_data.get('eventTimestamp', datetime.now().isoformat()),
                "event_timestamp": webhook_data.get('eventTimestamp', ''),
                "bucket_name": webhook_data.get('bucketName', ''),
                "event_type": webhook_data.get('eventType', ''),
                "object_key": webhook_data.get('objectName'),
                "object_size": object_size,  # Use validated and converted object_size
                "object_version_id": webhook_data.get('objectVersionId'),
                "source_ip": webhook_data.get('source_ip', ''),
                "user_agent": webhook_data.get('user_agent', ''),
                "request_id": webhook_data.get('eventId', ''),
                "raw_payload": webhook_data,
                "processed": False,
                "created_at": datetime.now().isoformat()
            }
            
            result = self.db.webhook_events.insert_one(event_doc)
            return str(result.inserted_id)
            
        except Exception as e:
            logger.error(f"Error saving webhook event to MongoDB: {e}")
            return None

    def save_webhook_events_batch(self, webhook_events_list):
        """Save multiple webhook events in a batch - highly optimized for MongoDB"""
        if not webhook_events_list:
            return 0
        
        try:
            current_time = datetime.now().isoformat()
            batch_docs = []
            
            for webhook_data in webhook_events_list:
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
                
                event_doc = {
                    "timestamp": webhook_data.get('eventTimestamp', current_time),
                    "event_timestamp": webhook_data.get('eventTimestamp', ''),
                    "bucket_name": webhook_data.get('bucketName', ''),
                    "event_type": webhook_data.get('eventType', ''),
                    "object_key": webhook_data.get('objectName'),
                    "object_size": object_size,  # Use validated and converted object_size
                    "object_version_id": webhook_data.get('objectVersionId'),
                    "source_ip": webhook_data.get('source_ip', ''),
                    "user_agent": webhook_data.get('user_agent', ''),
                    "request_id": webhook_data.get('eventId', ''),
                    "raw_payload": webhook_data,
                    "processed": False,
                    "created_at": current_time
                }
                batch_docs.append(event_doc)
            
            # MongoDB batch insert is extremely efficient
            result = self.db.webhook_events.insert_many(batch_docs, ordered=False)
            saved_count = len(result.inserted_ids)
            
            # Update webhook statistics efficiently
            self._update_webhook_statistics_batch(webhook_events_list, current_time)
            
            logger.info(f"MongoDB batch saved {saved_count} webhook events efficiently")
            return saved_count
            
        except Exception as e:
            logger.error(f"Error in MongoDB batch save: {e}")
            return 0

    def _update_webhook_statistics_batch(self, events_list, current_time):
        """Update webhook statistics for batch of events"""
        try:
            date_str = current_time[:10]  # YYYY-MM-DD
            
            # Group events by bucket and type for efficient updates
            stats_updates = {}
            for event in events_list:
                bucket_name = event.get('bucketName', '')
                event_type = event.get('eventType', '')
                key = (date_str, bucket_name, event_type)
                stats_updates[key] = stats_updates.get(key, 0) + 1
            
            # Batch update statistics using MongoDB's bulk operations
            from pymongo import UpdateOne
            bulk_ops = []
            
            for (date, bucket, event_type), count in stats_updates.items():
                filter_doc = {
                    "date": date,
                    "bucket_name": bucket,
                    "event_type": event_type
                }
                update_doc = {"$inc": {"event_count": count}}
                bulk_ops.append(UpdateOne(filter_doc, update_doc, upsert=True))
            
            if bulk_ops:
                self.db.webhook_statistics.bulk_write(bulk_ops)
                
        except Exception as e:
            logger.error(f"Error updating webhook statistics: {e}")

    def get_webhook_events(self, limit=100, bucket_name=None, event_type=None):
        """Get webhook events with optional filtering"""
        try:
            filter_query = {}
            if bucket_name:
                filter_query['bucket_name'] = bucket_name
            if event_type:
                filter_query['event_type'] = event_type
            
            cursor = self.db.webhook_events.find(filter_query).sort("created_at", DESCENDING).limit(limit)
            
            events = []
            for doc in cursor:
                event = dict(doc)
                event['id'] = str(event['_id'])
                del event['_id']
                events.append(event)
            
            return events
            
        except Exception as e:
            logger.error(f"Error getting webhook events from MongoDB: {e}")
            return []

    def get_webhook_statistics(self, days=30):
        """Get webhook statistics for the specified number of days"""
        try:
            cutoff_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
            
            cursor = self.db.webhook_statistics.find(
                {"date": {"$gte": cutoff_date}}
            ).sort("date", DESCENDING)
            
            stats = []
            for doc in cursor:
                stat = dict(doc)
                if '_id' in stat:
                    del stat['_id']
                stats.append(stat)
            
            return stats
            
        except Exception as e:
            logger.error(f"Error getting webhook statistics from MongoDB: {e}")
            return []

    def get_bucket_configuration(self, bucket_name):
        """Get bucket webhook configuration"""
        try:
            doc = self.db.bucket_configurations.find_one({"bucket_name": bucket_name})
            if doc:
                config = dict(doc)
                if '_id' in config:
                    del config['_id']
                # Parse events_to_track if it's a string
                if isinstance(config.get('events_to_track'), str):
                    try:
                        config['events_to_track'] = json.loads(config['events_to_track'])
                    except:
                        config['events_to_track'] = []
                return config
            return None
            
        except Exception as e:
            logger.error(f"Error getting bucket configuration from MongoDB: {e}")
            return None

    def save_bucket_configuration(self, bucket_name, webhook_enabled=False, webhook_secret=None, events_to_track=None):
        """Save bucket webhook configuration"""
        try:
            if events_to_track is None:
                events_to_track = ["b2:ObjectCreated", "b2:ObjectDeleted"]
            
            current_time = datetime.now().isoformat()
            
            config_doc = {
                "bucket_name": bucket_name,
                "webhook_enabled": webhook_enabled,
                "webhook_secret": webhook_secret,
                "events_to_track": json.dumps(events_to_track) if isinstance(events_to_track, list) else events_to_track,
                "updated_at": current_time
            }
            
            # Try to update existing, create if not exists
            result = self.db.bucket_configurations.update_one(
                {"bucket_name": bucket_name},
                {"$set": config_doc, "$setOnInsert": {"created_at": current_time}},
                upsert=True
            )
            
            return True
            
        except Exception as e:
            logger.error(f"Error saving bucket configuration to MongoDB: {e}")
            return False

    # Add compatibility methods for other database operations
    def get_cost_trends(self, days=30):
        """Get cost trends - same as SQLite implementation"""
        try:
            cursor = self.db.snapshots.find().sort("timestamp", DESCENDING).limit(days)
            trends = []
            for doc in cursor:
                trend = {
                    "timestamp": doc['timestamp'],
                    "total_storage_cost": doc['total_storage_cost'],
                    "total_download_cost": doc['total_download_cost'],
                    "total_api_cost": doc['total_api_cost'],
                    "total_cost": doc['total_cost']
                }
                trends.append(trend)
            return trends
        except Exception as e:
            logger.error(f"Error getting cost trends from MongoDB: {e}")
            return []

    def detect_significant_changes(self, threshold_percentage):
        """Detect significant changes in costs between the last two snapshots"""
        try:
            cursor = self.db.snapshots.find().sort("timestamp", DESCENDING).limit(2)
            snapshots = list(cursor)
            
            if len(snapshots) < 2:
                return None
            
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
                # Get bucket-level changes
                latest_id = str(latest['_id'])
                previous_id = str(previous['_id'])
                
                # Use aggregation to join bucket snapshots
                pipeline = [
                    {"$match": {"snapshot_id": {"$in": [latest_id, previous_id]}}},
                    {"$group": {
                        "_id": "$bucket_name",
                        "snapshots": {"$push": {
                            "snapshot_id": "$snapshot_id",
                            "total_cost": "$total_cost"
                        }}
                    }},
                    {"$match": {"snapshots.1": {"$exists": True}}}
                ]
                
                bucket_changes = []
                for result in self.db.bucket_snapshots.aggregate(pipeline):
                    snapshots_data = result['snapshots']
                    if len(snapshots_data) == 2:
                        # Find latest and previous costs
                        latest_cost = None
                        previous_cost = None
                        
                        for snapshot_data in snapshots_data:
                            if snapshot_data['snapshot_id'] == latest_id:
                                latest_cost = snapshot_data['total_cost']
                            elif snapshot_data['snapshot_id'] == previous_id:
                                previous_cost = snapshot_data['total_cost']
                        
                        if latest_cost is not None and previous_cost is not None:
                            change = self._calculate_percent_change(previous_cost, latest_cost)
                            if abs(change['percent']) >= threshold_percentage:
                                bucket_changes.append({
                                    'bucket_name': result['_id'],
                                    'change': change
                                })
                
                if bucket_changes:
                    significant_changes['buckets'] = sorted(
                        bucket_changes,
                        key=lambda x: abs(x['change']['percent']),
                        reverse=True
                    )
            
            return significant_changes if significant_changes else None
            
        except Exception as e:
            logger.error(f"Error detecting significant changes in MongoDB: {e}")
            return None

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

    # Add other required methods for compatibility
    def get_all_bucket_configurations(self):
        """Get all bucket configurations"""
        try:
            cursor = self.db.bucket_configurations.find()
            configs = []
            for doc in cursor:
                config = dict(doc)
                if '_id' in config:
                    del config['_id']
                if isinstance(config.get('events_to_track'), str):
                    try:
                        config['events_to_track'] = json.loads(config['events_to_track'])
                    except:
                        config['events_to_track'] = []
                configs.append(config)
            return configs
        except Exception as e:
            logger.error(f"Error getting all bucket configurations from MongoDB: {e}")
            return []

    def delete_bucket_configuration(self, bucket_name):
        """Delete bucket configuration"""
        try:
            result = self.db.bucket_configurations.delete_one({"bucket_name": bucket_name})
            return result.deleted_count > 0
        except Exception as e:
            logger.error(f"Error deleting bucket configuration from MongoDB: {e}")
            return False

    def get_all_bucket_names_from_webhooks(self):
        """Get all unique bucket names from webhook events"""
        try:
            bucket_names = self.db.webhook_events.distinct("bucket_name")
            return [name for name in bucket_names if name]  # Filter out empty names
        except Exception as e:
            logger.error(f"Error getting bucket names from MongoDB: {e}")
            return []

    # B2 bucket management methods
    def save_b2_bucket_details(self, bucket_details_list):
        """Save B2 bucket details"""
        if not bucket_details_list:
            return 0
        
        try:
            from pymongo import UpdateOne
            current_time = datetime.now().isoformat()
            bulk_ops = []
            
            for bucket_details in bucket_details_list:
                bucket_doc = {
                    "bucket_b2_id": bucket_details.get('bucketId'),
                    "bucket_name": bucket_details.get('bucketName'),
                    "account_b2_id": bucket_details.get('accountId'),
                    "bucket_type": bucket_details.get('bucketType'),
                    "cors_rules": json.dumps(bucket_details.get('corsRules', [])),
                    "event_notification_rules": json.dumps(bucket_details.get('eventNotificationRules', [])),
                    "lifecycle_rules": json.dumps(bucket_details.get('lifecycleRules', [])),
                    "bucket_info": json.dumps(bucket_details.get('bucketInfo', {})),
                    "options": json.dumps(bucket_details.get('options', [])),
                    "file_lock_configuration": json.dumps(bucket_details.get('fileLockConfiguration', {})),
                    "default_server_side_encryption": json.dumps(bucket_details.get('defaultServerSideEncryption', {})),
                    "replication_configuration": json.dumps(bucket_details.get('replicationConfiguration', {})),
                    "revision": bucket_details.get('revision', 1),
                    "last_synced_at": current_time
                }
                
                filter_doc = {"bucket_b2_id": bucket_details.get('bucketId')}
                update_doc = {"$set": bucket_doc}
                bulk_ops.append(UpdateOne(filter_doc, update_doc, upsert=True))
            
            if bulk_ops:
                result = self.db.b2_buckets.bulk_write(bulk_ops)
                return result.upserted_count + result.modified_count
            
            return 0
            
        except Exception as e:
            logger.error(f"Error saving B2 bucket details to MongoDB: {e}")
            return 0

    def get_all_b2_buckets(self):
        """Get all B2 buckets"""
        try:
            cursor = self.db.b2_buckets.find().sort("bucket_name", ASCENDING)
            buckets = []
            for doc in cursor:
                bucket = dict(doc)
                bucket['id'] = str(bucket['_id'])
                del bucket['_id']
                # Parse JSON fields
                for field in ['cors_rules', 'event_notification_rules', 'lifecycle_rules', 'bucket_info', 'options', 'file_lock_configuration', 'default_server_side_encryption', 'replication_configuration']:
                    if field in bucket and isinstance(bucket[field], str):
                        try:
                            bucket[field] = json.loads(bucket[field])
                        except:
                            bucket[field] = {}
                buckets.append(bucket)
            return buckets
        except Exception as e:
            logger.error(f"Error getting all B2 buckets from MongoDB: {e}")
            return []

    def get_b2_bucket_by_id(self, bucket_b2_id):
        """Get B2 bucket by B2 ID"""
        try:
            doc = self.db.b2_buckets.find_one({"bucket_b2_id": bucket_b2_id})
            if doc:
                bucket = dict(doc)
                bucket['id'] = str(bucket['_id'])
                del bucket['_id']
                # Parse JSON fields
                for field in ['cors_rules', 'event_notification_rules', 'lifecycle_rules', 'bucket_info', 'options', 'file_lock_configuration', 'default_server_side_encryption', 'replication_configuration']:
                    if field in bucket and isinstance(bucket[field], str):
                        try:
                            bucket[field] = json.loads(bucket[field])
                        except:
                            bucket[field] = {}
                return bucket
            return None
        except Exception as e:
            logger.error(f"Error getting B2 bucket by ID from MongoDB: {e}")
            return None

    def _get_connection(self):
        """Compatibility method for SQLite-style connection handling
        Returns a context manager that provides a MongoDB database connection"""
        class MongoConnectionContext:
            def __init__(self, db):
                self.db = db
                
            def __enter__(self):
                return self.db
                
            def __exit__(self, exc_type, exc_val, exc_tb):
                # MongoDB doesn't need explicit connection closing like SQLite
                pass
                
            def cursor(self):
                # Return a cursor-like object for compatibility
                return self.db
                
            def commit(self):
                # MongoDB doesn't need explicit commits
                pass
                
            def rollback(self):
                # MongoDB doesn't have rollback in the same way
                pass
        
        return MongoConnectionContext(self.db) 

    def get_object_operation_stats_for_period(self, start_date_str, end_date_str, bucket_name=None):
        """Calculate object operation statistics for a given period and optional bucket"""
        try:
            # Build the filter query - use created_at for recent activity filtering
            filter_query = {
                "created_at": {
                    "$gte": start_date_str,
                    "$lte": end_date_str
                }
            }
            
            if bucket_name:
                filter_query["bucket_name"] = bucket_name

            # Objects Added (b2:ObjectCreated events)
            added_filter = filter_query.copy()
            added_filter["event_type"] = {"$regex": "^b2:ObjectCreated:"}
            
            added_pipeline = [
                {"$match": added_filter},
                {"$group": {
                    "_id": "$request_id",  # Group by request_id to count unique events
                    "object_size": {"$first": "$object_size"}
                }},
                {"$group": {
                    "_id": None,
                    "count": {"$sum": 1},
                    "total_size": {"$sum": {"$ifNull": ["$object_size", 0]}}
                }}
            ]
            
            added_result = list(self.db.webhook_events.aggregate(added_pipeline))
            objects_added = added_result[0]["count"] if added_result else 0
            size_added = added_result[0]["total_size"] if added_result else 0

            # Objects Deleted (b2:ObjectDeleted events)
            deleted_filter = filter_query.copy()
            deleted_filter["event_type"] = {"$regex": "^b2:ObjectDeleted:"}
            
            deleted_pipeline = [
                {"$match": deleted_filter},
                {"$group": {
                    "_id": "$request_id",  # Group by request_id to count unique events
                    "object_size": {"$first": "$object_size"}
                }},
                {"$group": {
                    "_id": None,
                    "count": {"$sum": 1},
                    "total_size": {"$sum": {"$ifNull": ["$object_size", 0]}}
                }}
            ]
            
            deleted_result = list(self.db.webhook_events.aggregate(deleted_pipeline))
            objects_deleted = deleted_result[0]["count"] if deleted_result else 0
            size_deleted = deleted_result[0]["total_size"] if deleted_result else 0
            
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
            
        except Exception as e:
            logger.error(f"Error getting object operation stats from MongoDB: {e}")
            return {
                'objects_added': 0,
                'size_added': 0,
                'objects_deleted': 0,
                'size_deleted': 0,
                'net_object_change': 0,
                'net_size_change': 0,
                'start_date': start_date_str,
                'end_date': end_date_str,
                'bucket_name_filter': bucket_name
            }

    def get_daily_object_operation_breakdown(self, start_date_str, end_date_str, bucket_name=None):
        """Get a daily breakdown of object operations"""
        try:
            results = []
            # Parse dates and iterate through all days in the range
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
            
        except Exception as e:
            logger.error(f"Error getting daily operation breakdown from MongoDB: {e}")
            return []

    def get_top_buckets_by_size(self, operation_type='added', limit=10, start_date_str=None, end_date_str=None):
        """Get top N buckets by total data size for a given operation type and period"""
        try:
            if operation_type == 'added':
                event_type_pattern = "^b2:ObjectCreated:"
            elif operation_type == 'removed':
                event_type_pattern = "^b2:ObjectDeleted:"
            else:
                raise ValueError("Invalid operation_type. Must be 'added' or 'removed'.")

            filter_query = {"event_type": {"$regex": event_type_pattern}}

            if start_date_str and end_date_str:
                filter_query["created_at"] = {
                    "$gte": start_date_str,
                    "$lte": end_date_str
                }

            pipeline = [
                {"$match": filter_query},
                {"$group": {
                    "_id": "$bucket_name",
                    "total_size": {"$sum": {"$ifNull": ["$object_size", 0]}}
                }},
                {"$match": {"total_size": {"$gt": 0}}},
                {"$sort": {"total_size": -1}},
                {"$limit": limit},
                {"$project": {
                    "bucket_name": "$_id",
                    "total_size": 1,
                    "_id": 0
                }}
            ]

            results = list(self.db.webhook_events.aggregate(pipeline))
            return results
            
        except Exception as e:
            logger.error(f"Error getting top buckets by size from MongoDB: {e}")
            return []

    def get_top_buckets_by_object_count(self, operation_type='added', limit=10, start_date_str=None, end_date_str=None):
        """Get top N buckets by total object count for a given operation type and period"""
        try:
            if operation_type == 'added':
                event_type_pattern = "^b2:ObjectCreated:"
            elif operation_type == 'removed':
                event_type_pattern = "^b2:ObjectDeleted:"
            else:
                raise ValueError("Invalid operation_type. Must be 'added' or 'removed'.")

            filter_query = {"event_type": {"$regex": event_type_pattern}}

            if start_date_str and end_date_str:
                filter_query["created_at"] = {
                    "$gte": start_date_str,
                    "$lte": end_date_str
                }

            # Count distinct request_id to count unique events more accurately
            pipeline = [
                {"$match": filter_query},
                {"$group": {
                    "_id": {
                        "bucket_name": "$bucket_name",
                        "request_id": "$request_id"
                    }
                }},
                {"$group": {
                    "_id": "$_id.bucket_name",
                    "total_objects": {"$sum": 1}
                }},
                {"$match": {"total_objects": {"$gt": 0}}},
                {"$sort": {"total_objects": -1}},
                {"$limit": limit},
                {"$project": {
                    "bucket_name": "$_id",
                    "total_objects": 1,
                    "_id": 0
                }}
            ]

            results = list(self.db.webhook_events.aggregate(pipeline))
            return results
            
        except Exception as e:
            logger.error(f"Error getting top buckets by object count from MongoDB: {e}")
            return []

    def get_stale_buckets(self, limit=10, active_threshold_days=90):
        """Get N buckets that have not had recent 'created' activity"""
        try:
            # Get all known B2 bucket names (master list)
            b2_buckets = self.db.b2_buckets.distinct("bucket_name")
            
            if not b2_buckets:
                # Fallback to webhook event buckets if b2_buckets is empty
                b2_buckets = self.db.webhook_events.distinct("bucket_name")

            bucket_last_creation = []
            cutoff_date_str = (datetime.utcnow() - timedelta(days=active_threshold_days)).isoformat()

            for bucket_name in b2_buckets:
                # Find the latest creation event for this bucket
                latest_creation = self.db.webhook_events.find_one(
                    {
                        "bucket_name": bucket_name,
                        "event_type": {"$regex": "^b2:ObjectCreated:"}
                    },
                    sort=[("created_at", -1)]
                )
                
                if latest_creation is None:
                    # Buckets with no creation events are considered most stale
                    bucket_last_creation.append({
                        'bucket_name': bucket_name,
                        'last_creation_event': None,
                        'sort_key': '0'
                    })
                elif latest_creation.get('created_at', '') < cutoff_date_str:
                    # Buckets whose last creation event is older than the threshold
                    bucket_last_creation.append({
                        'bucket_name': bucket_name,
                        'last_creation_event': latest_creation.get('created_at'),
                        'sort_key': latest_creation.get('created_at', '0')
                    })
            
            # Sort: None (no creation events) first, then by oldest timestamp
            bucket_last_creation.sort(key=lambda x: x['sort_key'])
            
            return bucket_last_creation[:limit]
            
        except Exception as e:
            logger.error(f"Error getting stale buckets from MongoDB: {e}")
            return []

    def get_top_largest_objects(self, limit=10, start_date_str=None, end_date_str=None, bucket_name=None):
        """Get the top N largest objects from webhook events"""
        try:
            # Base filter for created events only
            filter_query = {
                "event_type": {"$regex": "^b2:ObjectCreated:"},
                "object_size": {"$gt": 0}  # Only include objects with size > 0
            }

            # Add time filter if provided
            if start_date_str and end_date_str:
                filter_query["created_at"] = {
                    "$gte": start_date_str,
                    "$lte": end_date_str
                }
            
            # Add bucket filter if provided
            if bucket_name:
                filter_query["bucket_name"] = bucket_name

            pipeline = [
                {"$match": filter_query},
                # Group by request_id to get unique objects only
                {"$group": {
                    "_id": "$request_id",
                    "object_key": {"$first": "$object_key"},
                    "object_size": {"$first": "$object_size"},
                    "bucket_name": {"$first": "$bucket_name"},
                    "event_type": {"$first": "$event_type"},
                    "created_at": {"$first": "$created_at"},
                    "event_timestamp": {"$first": "$event_timestamp"}
                }},
                # Sort by size descending
                {"$sort": {"object_size": -1}},
                {"$limit": limit},
                # Project the fields we want
                {"$project": {
                    "request_id": "$_id",
                    "object_key": 1,
                    "object_size": 1,
                    "bucket_name": 1,
                    "event_type": 1,
                    "created_at": 1,
                    "event_timestamp": 1,
                    "_id": 0
                }}
            ]

            results = list(self.db.webhook_events.aggregate(pipeline))
            return results
            
        except Exception as e:
            logger.error(f"Error getting top largest objects from MongoDB: {e}")
            return []

    # Billing Configuration Methods
    def save_billing_configuration(self, config):
        """Save billing configuration for cost calculations"""
        try:
            current_time = datetime.now().isoformat()
            
            billing_config = {
                "baseline_amount": config.get('baseline_amount', 0.0),
                "discount_percentage": config.get('discount_percentage', 0.0),
                "billing_period_start": config.get('billing_period_start'),
                "next_billing_period_start": config.get('next_billing_period_start'),
                "storage_price_per_gb": config.get('storage_price_per_gb', 0.005),  # B2 default
                "class_a_api_price": config.get('class_a_api_price', 0.004),  # Per 1,000 calls
                "class_b_api_price": config.get('class_b_api_price', 0.004),  # Per 10,000 calls
                "class_c_api_price": config.get('class_c_api_price', 0.004),  # Per 10,000 calls
                "created_at": current_time,
                "updated_at": current_time
            }
            
            # Replace existing config (only one config per system)
            result = self.db.billing_configuration.replace_one(
                {},  # Match any document
                billing_config,
                upsert=True
            )
            
            logger.info("Billing configuration saved successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error saving billing configuration to MongoDB: {e}")
            return False

    def get_billing_configuration(self):
        """Get current billing configuration"""
        try:
            config = self.db.billing_configuration.find_one()
            if config:
                # Remove MongoDB _id field
                if '_id' in config:
                    del config['_id']
                return config
            
            # Return default configuration if none exists
            return {
                "baseline_amount": None,
                "discount_percentage": 0.0,
                "billing_period_start": None,
                "next_billing_period_start": None,
                "storage_price_per_gb": 0.005,  # B2 default $0.005 per GB/month
                "class_a_api_price": 0.004,     # Upload API calls per 1,000
                "class_b_api_price": 0.004,     # Download API calls per 10,000  
                "class_c_api_price": 0.004      # Other API calls per 10,000
            }
            
        except Exception as e:
            logger.error(f"Error getting billing configuration from MongoDB: {e}")
            return None

    def reset_billing_configuration(self):
        """Reset/delete billing configuration"""
        try:
            result = self.db.billing_configuration.delete_many({})
            logger.info(f"Billing configuration reset - deleted {result.deleted_count} documents")
            return True
            
        except Exception as e:
            logger.error(f"Error resetting billing configuration in MongoDB: {e}")
            return False

    def calculate_estimated_costs(self, start_date_str, end_date_str, bucket_name=None):
        """Calculate estimated B2 costs based on webhook activity and configuration"""
        try:
            # Get billing configuration
            config = self.get_billing_configuration()
            if not config or config.get('baseline_amount') is None:
                return {
                    'error': 'Billing configuration not set. Please configure billing settings first.',
                    'needs_configuration': True
                }
            
            # Get operation stats for the period
            stats = self.get_object_operation_stats_for_period(start_date_str, end_date_str, bucket_name)
            
            # Calculate storage costs (based on net size change)
            net_storage_gb = stats['net_size_change'] / (1024**3)  # Convert bytes to GB
            storage_cost = net_storage_gb * config['storage_price_per_gb']
            
            # Calculate API costs
            # Class A: Upload operations (ObjectCreated events)
            class_a_calls = stats['objects_added']
            class_a_cost = (class_a_calls / 1000) * config['class_a_api_price']
            
            # Class C: Delete operations (ObjectDeleted events) 
            class_c_calls = stats['objects_deleted']
            class_c_cost = (class_c_calls / 10000) * config['class_c_api_price']
            
            # Total incremental cost for this period
            incremental_cost = storage_cost + class_a_cost + class_c_cost
            
            # Apply discount if configured
            if config['discount_percentage'] > 0:
                discount_multiplier = (100 - config['discount_percentage']) / 100
                incremental_cost *= discount_multiplier
            
            # Calculate estimated total bill
            baseline = config['baseline_amount']
            estimated_total = baseline + incremental_cost
            
            return {
                'baseline_amount': baseline,
                'incremental_cost': incremental_cost,
                'estimated_total': estimated_total,
                'storage_cost': storage_cost,
                'api_cost': class_a_cost + class_c_cost,
                'class_a_cost': class_a_cost,
                'class_c_cost': class_c_cost,
                'discount_percentage': config['discount_percentage'],
                'net_storage_gb': net_storage_gb,
                'api_calls': {
                    'uploads': class_a_calls,
                    'deletes': class_c_calls
                },
                'period': {
                    'start': start_date_str,
                    'end': end_date_str
                }
            }
            
        except Exception as e:
            logger.error(f"Error calculating estimated costs: {e}")
            return {
                'error': f'Error calculating costs: {str(e)}',
                'needs_configuration': False
            } 
        
        8113