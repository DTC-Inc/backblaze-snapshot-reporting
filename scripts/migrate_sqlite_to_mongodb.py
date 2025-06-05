#!/usr/bin/env python3
"""
Migration script to transfer data from SQLite to MongoDB
Run this script within the container to migrate existing data

Usage:
    python scripts/migrate_sqlite_to_mongodb.py [options]

Options:
    --sqlite-path PATH     Path to SQLite database (default: /data/backblaze_snapshots.db)
    --mongodb-uri URI      MongoDB connection URI (default: from environment)
    --dry-run             Show what would be migrated without actually doing it
    --batch-size SIZE     Number of records to process at once (default: 1000)
    --verbose             Enable verbose logging
    --force               Skip confirmation prompts
"""

import os
import sys
import json
import sqlite3
import logging
import argparse
from datetime import datetime
from typing import Dict, List, Any, Optional

# Add the app directory to the path so we can import our modules
sys.path.insert(0, '/app')

try:
    from app.models.database import Database
    from app.models.mongodb_database import MongoDatabase
    from pymongo.errors import PyMongoError
except ImportError as e:
    print(f"Error importing required modules: {e}")
    print("Make sure you're running this script from within the container")
    sys.exit(1)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class SQLiteToMongoMigrator:
    def __init__(self, sqlite_path: str, mongodb_uri: str, dry_run: bool = False, batch_size: int = 1000, verbose: bool = False):
        self.sqlite_path = sqlite_path
        self.mongodb_uri = mongodb_uri
        self.dry_run = dry_run
        self.batch_size = batch_size
        self.verbose = verbose
        
        if verbose:
            logging.getLogger().setLevel(logging.DEBUG)
        
        # Initialize databases
        self.sqlite_db = None
        self.mongo_db = None
        
        # Migration statistics
        self.stats = {
            'snapshots': {'total': 0, 'migrated': 0, 'errors': 0},
            'bucket_snapshots': {'total': 0, 'migrated': 0, 'errors': 0},
            'webhook_events': {'total': 0, 'migrated': 0, 'errors': 0},
            'bucket_configurations': {'total': 0, 'migrated': 0, 'errors': 0},
            'b2_buckets': {'total': 0, 'migrated': 0, 'errors': 0},
            'webhook_statistics': {'total': 0, 'migrated': 0, 'errors': 0}
        }

    def connect_databases(self):
        """Connect to both SQLite and MongoDB databases"""
        try:
            logger.info(f"Connecting to SQLite database: {self.sqlite_path}")
            if not os.path.exists(self.sqlite_path):
                raise FileNotFoundError(f"SQLite database not found: {self.sqlite_path}")
            
            self.sqlite_db = Database(self.sqlite_path)
            logger.info("✓ SQLite connection established")
            
            logger.info(f"Connecting to MongoDB: {self.mongodb_uri}")
            self.mongo_db = MongoDatabase(self.mongodb_uri)
            logger.info("✓ MongoDB connection established")
            
        except Exception as e:
            logger.error(f"Database connection failed: {e}")
            raise

    def get_table_counts(self) -> Dict[str, int]:
        """Get the number of records in each SQLite table"""
        counts = {}
        tables = [
            'snapshots', 'bucket_snapshots', 'webhook_events', 
            'bucket_configurations', 'b2_buckets', 'webhook_statistics'
        ]
        
        with self.sqlite_db._get_connection() as conn:
            cursor = conn.cursor()
            
            for table in tables:
                try:
                    cursor.execute(f"SELECT COUNT(*) FROM {table}")
                    count = cursor.fetchone()[0]
                    counts[table] = count
                    self.stats[table]['total'] = count
                except sqlite3.OperationalError:
                    # Table doesn't exist
                    counts[table] = 0
                    self.stats[table]['total'] = 0
        
        return counts

    def migrate_snapshots(self):
        """Migrate snapshots table"""
        logger.info("Migrating snapshots...")
        
        if self.stats['snapshots']['total'] == 0:
            logger.info("No snapshots to migrate")
            return
        
        with self.sqlite_db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, timestamp, total_storage_bytes, total_storage_cost,
                       total_download_bytes, total_download_cost, total_api_calls,
                       total_api_cost, total_cost, raw_data
                FROM snapshots
                ORDER BY id
            """)
            
            batch = []
            processed = 0
            
            for row in cursor:
                snapshot_doc = {
                    "timestamp": row[1],
                    "total_storage_bytes": row[2] or 0,
                    "total_storage_cost": row[3] or 0.0,
                    "total_download_bytes": row[4] or 0,
                    "total_download_cost": row[5] or 0.0,
                    "total_api_calls": row[6] or 0,
                    "total_api_cost": row[7] or 0.0,
                    "total_cost": row[8] or 0.0,
                    "raw_data": row[9]
                }
                
                batch.append((row[0], snapshot_doc))  # Keep SQLite ID for bucket_snapshots reference
                
                if len(batch) >= self.batch_size:
                    processed += self._process_snapshot_batch(batch)
                    batch = []
            
            # Process remaining records
            if batch:
                processed += self._process_snapshot_batch(batch)
            
            logger.info(f"✓ Migrated {processed} snapshots")

    def _process_snapshot_batch(self, batch: List[tuple]) -> int:
        """Process a batch of snapshots"""
        if self.dry_run:
            logger.debug(f"DRY RUN: Would migrate {len(batch)} snapshots")
            return len(batch)
        
        try:
            # Create a mapping of old IDs to new IDs
            old_to_new_ids = {}
            
            for old_id, snapshot_doc in batch:
                result = self.mongo_db.db.snapshots.insert_one(snapshot_doc)
                old_to_new_ids[old_id] = str(result.inserted_id)
                self.stats['snapshots']['migrated'] += 1
            
            # Store the mapping for bucket_snapshots migration
            if not hasattr(self, 'snapshot_id_mapping'):
                self.snapshot_id_mapping = {}
            self.snapshot_id_mapping.update(old_to_new_ids)
            
            return len(batch)
            
        except Exception as e:
            logger.error(f"Error processing snapshot batch: {e}")
            self.stats['snapshots']['errors'] += len(batch)
            return 0

    def migrate_bucket_snapshots(self):
        """Migrate bucket_snapshots table"""
        logger.info("Migrating bucket snapshots...")
        
        if self.stats['bucket_snapshots']['total'] == 0:
            logger.info("No bucket snapshots to migrate")
            return
        
        if not hasattr(self, 'snapshot_id_mapping'):
            logger.warning("No snapshot ID mapping found - bucket snapshots may have orphaned references")
            self.snapshot_id_mapping = {}
        
        with self.sqlite_db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT snapshot_id, bucket_name, storage_bytes, storage_cost,
                       download_bytes, download_cost, api_calls, api_cost, total_cost
                FROM bucket_snapshots
                ORDER BY snapshot_id
            """)
            
            batch = []
            processed = 0
            
            for row in cursor:
                old_snapshot_id = row[0]
                new_snapshot_id = self.snapshot_id_mapping.get(old_snapshot_id)
                
                if not new_snapshot_id:
                    logger.warning(f"Snapshot ID {old_snapshot_id} not found in mapping - skipping bucket snapshot")
                    self.stats['bucket_snapshots']['errors'] += 1
                    continue
                
                bucket_doc = {
                    "snapshot_id": new_snapshot_id,
                    "bucket_name": row[1],
                    "storage_bytes": row[2] or 0,
                    "storage_cost": row[3] or 0.0,
                    "download_bytes": row[4] or 0,
                    "download_cost": row[5] or 0.0,
                    "api_calls": row[6] or 0,
                    "api_cost": row[7] or 0.0,
                    "total_cost": row[8] or 0.0
                }
                
                batch.append(bucket_doc)
                
                if len(batch) >= self.batch_size:
                    processed += self._process_bucket_snapshot_batch(batch)
                    batch = []
            
            # Process remaining records
            if batch:
                processed += self._process_bucket_snapshot_batch(batch)
            
            logger.info(f"✓ Migrated {processed} bucket snapshots")

    def _process_bucket_snapshot_batch(self, batch: List[Dict]) -> int:
        """Process a batch of bucket snapshots"""
        if self.dry_run:
            logger.debug(f"DRY RUN: Would migrate {len(batch)} bucket snapshots")
            return len(batch)
        
        try:
            self.mongo_db.db.bucket_snapshots.insert_many(batch)
            self.stats['bucket_snapshots']['migrated'] += len(batch)
            return len(batch)
            
        except Exception as e:
            logger.error(f"Error processing bucket snapshot batch: {e}")
            self.stats['bucket_snapshots']['errors'] += len(batch)
            return 0

    def migrate_webhook_events(self):
        """Migrate webhook_events table"""
        logger.info("Migrating webhook events...")
        
        if self.stats['webhook_events']['total'] == 0:
            logger.info("No webhook events to migrate")
            return
        
        with self.sqlite_db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT timestamp, event_timestamp, bucket_name, event_type,
                       object_key, object_size, object_version_id, source_ip,
                       user_agent, request_id, raw_payload, processed, created_at
                FROM webhook_events
                ORDER BY created_at
            """)
            
            batch = []
            processed = 0
            
            for row in cursor:
                # Parse raw_payload if it's a string
                raw_payload = row[10]
                if isinstance(raw_payload, str):
                    try:
                        raw_payload = json.loads(raw_payload)
                    except (json.JSONDecodeError, TypeError):
                        raw_payload = {"error": "Could not parse original payload"}
                
                event_doc = {
                    "timestamp": row[0],
                    "event_timestamp": row[1],
                    "bucket_name": row[2],
                    "event_type": row[3],
                    "object_key": row[4],
                    "object_size": row[5] or 0,
                    "object_version_id": row[6],
                    "source_ip": row[7],
                    "user_agent": row[8],
                    "request_id": row[9],
                    "raw_payload": raw_payload,
                    "processed": bool(row[11]) if row[11] is not None else False,
                    "created_at": row[12] or datetime.now().isoformat()
                }
                
                batch.append(event_doc)
                
                if len(batch) >= self.batch_size:
                    processed += self._process_webhook_event_batch(batch)
                    batch = []
                    
                    # Progress indicator for large webhook tables
                    if processed % 10000 == 0:
                        logger.info(f"  Processed {processed} webhook events...")
            
            # Process remaining records
            if batch:
                processed += self._process_webhook_event_batch(batch)
            
            logger.info(f"✓ Migrated {processed} webhook events")

    def _process_webhook_event_batch(self, batch: List[Dict]) -> int:
        """Process a batch of webhook events"""
        if self.dry_run:
            logger.debug(f"DRY RUN: Would migrate {len(batch)} webhook events")
            return len(batch)
        
        try:
            self.mongo_db.db.webhook_events.insert_many(batch, ordered=False)
            self.stats['webhook_events']['migrated'] += len(batch)
            return len(batch)
            
        except Exception as e:
            logger.error(f"Error processing webhook event batch: {e}")
            self.stats['webhook_events']['errors'] += len(batch)
            return 0

    def migrate_bucket_configurations(self):
        """Migrate bucket_configurations table"""
        logger.info("Migrating bucket configurations...")
        
        if self.stats['bucket_configurations']['total'] == 0:
            logger.info("No bucket configurations to migrate")
            return
        
        with self.sqlite_db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT bucket_name, webhook_enabled, webhook_secret, events_to_track, created_at, updated_at
                FROM bucket_configurations
            """)
            
            batch = []
            processed = 0
            
            for row in cursor:
                # Parse events_to_track if it's a string
                events_to_track = row[3]
                if isinstance(events_to_track, str):
                    try:
                        events_to_track = json.loads(events_to_track)
                    except (json.JSONDecodeError, TypeError):
                        events_to_track = ["b2:ObjectCreated", "b2:ObjectDeleted"]
                
                config_doc = {
                    "bucket_name": row[0],
                    "webhook_enabled": bool(row[1]) if row[1] is not None else False,
                    "webhook_secret": row[2],
                    "events_to_track": json.dumps(events_to_track) if isinstance(events_to_track, list) else events_to_track,
                    "created_at": row[4] or datetime.now().isoformat(),
                    "updated_at": row[5] or datetime.now().isoformat()
                }
                
                batch.append(config_doc)
                
                if len(batch) >= self.batch_size:
                    processed += self._process_bucket_config_batch(batch)
                    batch = []
            
            # Process remaining records
            if batch:
                processed += self._process_bucket_config_batch(batch)
            
            logger.info(f"✓ Migrated {processed} bucket configurations")

    def _process_bucket_config_batch(self, batch: List[Dict]) -> int:
        """Process a batch of bucket configurations"""
        if self.dry_run:
            logger.debug(f"DRY RUN: Would migrate {len(batch)} bucket configurations")
            return len(batch)
        
        try:
            from pymongo import UpdateOne
            bulk_ops = []
            
            for config_doc in batch:
                filter_doc = {"bucket_name": config_doc["bucket_name"]}
                update_doc = {"$set": config_doc}
                bulk_ops.append(UpdateOne(filter_doc, update_doc, upsert=True))
            
            if bulk_ops:
                result = self.mongo_db.db.bucket_configurations.bulk_write(bulk_ops)
                migrated = result.upserted_count + result.modified_count
                self.stats['bucket_configurations']['migrated'] += migrated
                return migrated
            
            return 0
            
        except Exception as e:
            logger.error(f"Error processing bucket configuration batch: {e}")
            self.stats['bucket_configurations']['errors'] += len(batch)
            return 0

    def migrate_b2_buckets(self):
        """Migrate b2_buckets table"""
        logger.info("Migrating B2 buckets...")
        
        if self.stats['b2_buckets']['total'] == 0:
            logger.info("No B2 buckets to migrate")
            return
        
        with self.sqlite_db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT bucket_b2_id, bucket_name, account_b2_id, bucket_type,
                       cors_rules, event_notification_rules, lifecycle_rules,
                       bucket_info, options, file_lock_configuration,
                       default_server_side_encryption, replication_configuration,
                       revision, last_synced_at
                FROM b2_buckets
            """)
            
            batch = []
            processed = 0
            
            for row in cursor:
                bucket_doc = {
                    "bucket_b2_id": row[0],
                    "bucket_name": row[1],
                    "account_b2_id": row[2],
                    "bucket_type": row[3],
                    "cors_rules": row[4] or "[]",
                    "event_notification_rules": row[5] or "[]",
                    "lifecycle_rules": row[6] or "[]",
                    "bucket_info": row[7] or "{}",
                    "options": row[8] or "[]",
                    "file_lock_configuration": row[9] or "{}",
                    "default_server_side_encryption": row[10] or "{}",
                    "replication_configuration": row[11] or "{}",
                    "revision": row[12] or 1,
                    "last_synced_at": row[13] or datetime.now().isoformat()
                }
                
                batch.append(bucket_doc)
                
                if len(batch) >= self.batch_size:
                    processed += self._process_b2_bucket_batch(batch)
                    batch = []
            
            # Process remaining records
            if batch:
                processed += self._process_b2_bucket_batch(batch)
            
            logger.info(f"✓ Migrated {processed} B2 buckets")

    def _process_b2_bucket_batch(self, batch: List[Dict]) -> int:
        """Process a batch of B2 buckets"""
        if self.dry_run:
            logger.debug(f"DRY RUN: Would migrate {len(batch)} B2 buckets")
            return len(batch)
        
        try:
            from pymongo import UpdateOne
            bulk_ops = []
            
            for bucket_doc in batch:
                filter_doc = {"bucket_b2_id": bucket_doc["bucket_b2_id"]}
                update_doc = {"$set": bucket_doc}
                bulk_ops.append(UpdateOne(filter_doc, update_doc, upsert=True))
            
            if bulk_ops:
                result = self.mongo_db.db.b2_buckets.bulk_write(bulk_ops)
                migrated = result.upserted_count + result.modified_count
                self.stats['b2_buckets']['migrated'] += migrated
                return migrated
            
            return 0
            
        except Exception as e:
            logger.error(f"Error processing B2 bucket batch: {e}")
            self.stats['b2_buckets']['errors'] += len(batch)
            return 0

    def migrate_webhook_statistics(self):
        """Migrate webhook_statistics table if it exists"""
        logger.info("Migrating webhook statistics...")
        
        if self.stats['webhook_statistics']['total'] == 0:
            logger.info("No webhook statistics to migrate")
            return
        
        with self.sqlite_db._get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    SELECT date, bucket_name, event_type, event_count
                    FROM webhook_statistics
                """)
                
                batch = []
                processed = 0
                
                for row in cursor:
                    stat_doc = {
                        "date": row[0],
                        "bucket_name": row[1],
                        "event_type": row[2],
                        "event_count": row[3] or 0
                    }
                    
                    batch.append(stat_doc)
                    
                    if len(batch) >= self.batch_size:
                        processed += self._process_webhook_stats_batch(batch)
                        batch = []
                
                # Process remaining records
                if batch:
                    processed += self._process_webhook_stats_batch(batch)
                
                logger.info(f"✓ Migrated {processed} webhook statistics")
                
            except sqlite3.OperationalError:
                logger.info("Webhook statistics table doesn't exist - skipping")

    def _process_webhook_stats_batch(self, batch: List[Dict]) -> int:
        """Process a batch of webhook statistics"""
        if self.dry_run:
            logger.debug(f"DRY RUN: Would migrate {len(batch)} webhook statistics")
            return len(batch)
        
        try:
            from pymongo import UpdateOne
            bulk_ops = []
            
            for stat_doc in batch:
                filter_doc = {
                    "date": stat_doc["date"],
                    "bucket_name": stat_doc["bucket_name"],
                    "event_type": stat_doc["event_type"]
                }
                update_doc = {"$inc": {"event_count": stat_doc["event_count"]}}
                bulk_ops.append(UpdateOne(filter_doc, update_doc, upsert=True))
            
            if bulk_ops:
                result = self.mongo_db.db.webhook_statistics.bulk_write(bulk_ops)
                migrated = result.upserted_count + result.modified_count
                self.stats['webhook_statistics']['migrated'] += migrated
                return migrated
            
            return 0
            
        except Exception as e:
            logger.error(f"Error processing webhook statistics batch: {e}")
            self.stats['webhook_statistics']['errors'] += len(batch)
            return 0

    def print_migration_summary(self):
        """Print a summary of the migration results"""
        logger.info("\n" + "="*60)
        logger.info("MIGRATION SUMMARY")
        logger.info("="*60)
        
        total_migrated = 0
        total_errors = 0
        
        for table, stats in self.stats.items():
            if stats['total'] > 0:
                success_rate = (stats['migrated'] / stats['total']) * 100 if stats['total'] > 0 else 0
                logger.info(f"{table:20}: {stats['migrated']:6}/{stats['total']:6} ({success_rate:5.1f}%) - {stats['errors']} errors")
                total_migrated += stats['migrated']
                total_errors += stats['errors']
        
        logger.info("-" * 60)
        logger.info(f"{'TOTAL':20}: {total_migrated:6} records migrated, {total_errors} errors")
        
        if self.dry_run:
            logger.info("\nNOTE: This was a DRY RUN - no data was actually migrated")
        else:
            logger.info(f"\n✓ Migration completed successfully!")
            logger.info(f"You can now update your stack.env to use MongoDB:")
            logger.info(f"  USE_MONGODB=1")
            logger.info(f"  DATABASE_URI={self.mongodb_uri}")

    def run_migration(self):
        """Run the complete migration process"""
        try:
            logger.info("Starting SQLite to MongoDB migration...")
            logger.info(f"SQLite: {self.sqlite_path}")
            logger.info(f"MongoDB: {self.mongodb_uri}")
            logger.info(f"Dry run: {self.dry_run}")
            logger.info(f"Batch size: {self.batch_size}")
            
            # Connect to databases
            self.connect_databases()
            
            # Get table counts
            counts = self.get_table_counts()
            logger.info("\nTable counts in SQLite:")
            for table, count in counts.items():
                if count > 0:
                    logger.info(f"  {table}: {count}")
            
            # Confirm migration
            if not self.dry_run:
                total_records = sum(counts.values())
                if total_records == 0:
                    logger.info("No data to migrate!")
                    return
                
                logger.warning(f"\nThis will migrate {total_records} records to MongoDB.")
                logger.warning("This operation may take several minutes for large datasets.")
                
                response = input("\nDo you want to continue? (yes/no): ").lower().strip()
                if response not in ['yes', 'y']:
                    logger.info("Migration cancelled by user")
                    return
            
            # Run migrations in order
            start_time = datetime.now()
            
            self.migrate_snapshots()
            self.migrate_bucket_snapshots()
            self.migrate_webhook_events()
            self.migrate_bucket_configurations()
            self.migrate_b2_buckets()
            self.migrate_webhook_statistics()
            
            end_time = datetime.now()
            duration = end_time - start_time
            
            # Print summary
            self.print_migration_summary()
            logger.info(f"\nMigration completed in {duration}")
            
        except KeyboardInterrupt:
            logger.error("\nMigration interrupted by user")
            sys.exit(1)
        except Exception as e:
            logger.error(f"Migration failed: {e}")
            if self.verbose:
                import traceback
                traceback.print_exc()
            sys.exit(1)

def main():
    parser = argparse.ArgumentParser(
        description="Migrate data from SQLite to MongoDB",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run to see what would be migrated
  python scripts/migrate_sqlite_to_mongodb.py --dry-run
  
  # Migrate with custom batch size
  python scripts/migrate_sqlite_to_mongodb.py --batch-size 500
  
  # Migrate with verbose output
  python scripts/migrate_sqlite_to_mongodb.py --verbose
  
  # Force migration without prompts (for automation)
  python scripts/migrate_sqlite_to_mongodb.py --force --verbose
        """
    )
    
    parser.add_argument(
        '--sqlite-path',
        default='/data/backblaze_snapshots.db',
        help='Path to SQLite database (default: /data/backblaze_snapshots.db)'
    )
    
    parser.add_argument(
        '--mongodb-uri',
        default=os.getenv('DATABASE_URI', 'mongodb://mongodb:27017/bbssr_db'),
        help='MongoDB connection URI (default: from DATABASE_URI env var)'
    )
    
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be migrated without actually doing it'
    )
    
    parser.add_argument(
        '--batch-size',
        type=int,
        default=1000,
        help='Number of records to process at once (default: 1000)'
    )
    
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Enable verbose logging'
    )
    
    parser.add_argument(
        '--force',
        action='store_true',
        help='Skip confirmation prompts'
    )
    
    args = parser.parse_args()
    
    # Override confirmation if force is specified
    if args.force:
        # Monkey patch input to always return 'yes'
        import builtins
        builtins.input = lambda _: 'yes'
    
    # Create and run migrator
    migrator = SQLiteToMongoMigrator(
        sqlite_path=args.sqlite_path,
        mongodb_uri=args.mongodb_uri,
        dry_run=args.dry_run,
        batch_size=args.batch_size,
        verbose=args.verbose
    )
    
    migrator.run_migration()

if __name__ == '__main__':
    main() 