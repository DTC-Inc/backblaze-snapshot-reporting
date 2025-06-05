# Migrating from SQLite to MongoDB

This guide explains how to migrate your existing data from SQLite to MongoDB for better performance with high-volume webhook events.

## When to Migrate

Consider migrating from SQLite to MongoDB if you experience:

- **High webhook volume**: More than 100 events per second
- **Database lock errors**: SQLite struggles with concurrent writes
- **Performance issues**: Slow query response times
- **Future scaling needs**: Planning for horizontal scaling

## Prerequisites

1. **Running application**: Your BBSSR application should be running
2. **MongoDB service**: MongoDB container should be available
3. **Data backup**: Always backup your data before migration
4. **Downtime window**: Plan for application downtime during migration

## Migration Process

### Step 1: Backup Your SQLite Database

First, create a backup of your existing SQLite database:

```bash
# Create a backup directory
docker exec bbssr_web mkdir -p /data/backups

# Create a backup with timestamp
docker exec bbssr_web cp /data/backblaze_snapshots.db /data/backups/backblaze_snapshots_$(date +%Y%m%d_%H%M%S).db

# Verify backup exists
docker exec bbssr_web ls -la /data/backups/
```

### Step 2: Ensure MongoDB is Running

Make sure MongoDB is properly configured and running:

```bash
# Check MongoDB container status
docker compose ps mongodb

# Test MongoDB connection
docker exec bbssr_mongodb mongosh --eval "db.adminCommand('ping')"

# Check MongoDB logs if needed
docker compose logs mongodb
```

### Step 3: Run Migration Dry Run

First, run a dry run to see what would be migrated:

```bash
docker exec bbssr_web python scripts/migrate_sqlite_to_mongodb.py --dry-run --verbose
```

This will show you:
- How many records exist in each table
- What would be migrated
- Any potential issues

Example output:
```
2024-01-15 10:30:00 - INFO - Starting SQLite to MongoDB migration...
2024-01-15 10:30:00 - INFO - SQLite: /data/backblaze_snapshots.db
2024-01-15 10:30:00 - INFO - MongoDB: mongodb://mongodb:27017/bbssr_db
2024-01-15 10:30:00 - INFO - Dry run: True
2024-01-15 10:30:01 - INFO - ✓ SQLite connection established
2024-01-15 10:30:01 - INFO - ✓ MongoDB connection established

Table counts in SQLite:
  snapshots: 45
  bucket_snapshots: 180
  webhook_events: 15420
  bucket_configurations: 3
  b2_buckets: 3

2024-01-15 10:30:01 - INFO - DRY RUN: Would migrate 45 snapshots
2024-01-15 10:30:01 - INFO - DRY RUN: Would migrate 180 bucket snapshots
...
```

### Step 4: Stop the Application (Optional)

For the safest migration, stop the application to prevent new data being written:

```bash
docker compose stop web
```

**Note**: You can also run the migration while the application is running, but there's a small risk of missing very recent data.

### Step 5: Run the Actual Migration

Execute the migration:

```bash
docker exec bbssr_web python scripts/migrate_sqlite_to_mongodb.py --verbose
```

You'll be prompted to confirm:
```
This will migrate 15648 records to MongoDB.
This operation may take several minutes for large datasets.

Do you want to continue? (yes/no): yes
```

The migration will proceed with progress updates:
```
2024-01-15 10:35:00 - INFO - Migrating snapshots...
2024-01-15 10:35:01 - INFO - ✓ Migrated 45 snapshots
2024-01-15 10:35:01 - INFO - Migrating bucket snapshots...
2024-01-15 10:35:02 - INFO - ✓ Migrated 180 bucket snapshots
2024-01-15 10:35:02 - INFO - Migrating webhook events...
2024-01-15 10:35:02 - INFO -   Processed 10000 webhook events...
2024-01-15 10:35:05 - INFO - ✓ Migrated 15420 webhook events
...

============================================================
MIGRATION SUMMARY
============================================================
snapshots           :     45/    45 (100.0%) - 0 errors
bucket_snapshots     :    180/   180 (100.0%) - 0 errors
webhook_events       :  15420/ 15420 (100.0%) - 0 errors
bucket_configurations:      3/     3 (100.0%) - 0 errors
b2_buckets           :      3/     3 (100.0%) - 0 errors
------------------------------------------------------------
TOTAL                :  15651 records migrated, 0 errors

✓ Migration completed successfully!
You can now update your stack.env to use MongoDB:
  USE_MONGODB=1
  DATABASE_URI=mongodb://mongodb:27017/bbssr_db
```

### Step 6: Update Configuration

Update your `stack.env` file to use MongoDB:

```bash
# Change these lines in stack.env:
USE_MONGODB=1
DATABASE_URI=mongodb://mongodb:27017/bbssr_db

# Comment out the SQLite configuration:
# DATABASE_URI=sqlite:////data/backblaze_snapshots.db
# USE_MONGODB=0
```

### Step 7: Restart the Application

Restart the application with the new configuration:

```bash
docker compose up -d
```

### Step 8: Verify Migration

Check that the application is working correctly:

1. **Check application logs**:
   ```bash
   docker compose logs web
   ```

2. **Access the web interface**: Visit your application URL

3. **Verify data**: Check that your snapshots and configurations are visible

4. **Test webhook events**: Send a test webhook to ensure new events are recorded

## Migration Options

### Command Line Options

The migration script supports several options:

```bash
# Basic migration
python scripts/migrate_sqlite_to_mongodb.py

# Dry run (recommended first)
python scripts/migrate_sqlite_to_mongodb.py --dry-run

# Custom batch size (for memory-constrained environments)
python scripts/migrate_sqlite_to_mongodb.py --batch-size 500

# Verbose output for debugging
python scripts/migrate_sqlite_to_mongodb.py --verbose

# Skip confirmation prompts (for automation)
python scripts/migrate_sqlite_to_mongodb.py --force

# Custom database paths
python scripts/migrate_sqlite_to_mongodb.py \
  --sqlite-path /data/custom.db \
  --mongodb-uri mongodb://mongodb:27017/custom_db
```

### Batch Processing

The script processes records in batches for efficiency:
- **Default batch size**: 1000 records
- **Large datasets**: Use smaller batch sizes (500-1000) for memory efficiency
- **Small datasets**: Can use larger batch sizes (2000-5000) for speed

## Troubleshooting

### Common Issues

1. **MongoDB Connection Failed**:
   ```
   Error: Failed to connect to MongoDB: ...
   ```
   - Check MongoDB container is running: `docker compose ps mongodb`
   - Verify MongoDB URI in environment variables
   - Check MongoDB logs: `docker compose logs mongodb`

2. **SQLite Database Locked**:
   ```
   Error: database is locked
   ```
   - Stop the application: `docker compose stop web`
   - Wait a few seconds and try again
   - Ensure no other processes are accessing the database

3. **Out of Memory**:
   ```
   Error: MemoryError during batch processing
   ```
   - Reduce batch size: `--batch-size 500`
   - Check available container memory
   - Consider processing smaller chunks

4. **Partial Migration**:
   ```
   snapshots           :     40/    45 ( 88.9%) - 5 errors
   ```
   - Check error messages for specific issues
   - Run with `--verbose` for detailed error information
   - Address data consistency issues and re-run

### Recovery from Failed Migration

If migration fails partway through:

1. **Check the summary**: See which tables completed successfully
2. **Fix the issue**: Address connection problems, memory issues, etc.
3. **Re-run migration**: The script handles duplicate records gracefully
4. **MongoDB upserts**: Duplicate records will be updated, not duplicated

### Data Verification

After migration, verify your data:

```bash
# Check record counts in MongoDB
docker exec bbssr_mongodb mongosh bbssr_db --eval "
  print('snapshots:', db.snapshots.countDocuments({}));
  print('bucket_snapshots:', db.bucket_snapshots.countDocuments({}));
  print('webhook_events:', db.webhook_events.countDocuments({}));
  print('bucket_configurations:', db.bucket_configurations.countDocuments({}));
  print('b2_buckets:', db.b2_buckets.countDocuments({}));
"

# Compare with SQLite counts
docker exec bbssr_web sqlite3 /data/backblaze_snapshots.db "
  SELECT 'snapshots', COUNT(*) FROM snapshots
  UNION ALL SELECT 'bucket_snapshots', COUNT(*) FROM bucket_snapshots
  UNION ALL SELECT 'webhook_events', COUNT(*) FROM webhook_events
  UNION ALL SELECT 'bucket_configurations', COUNT(*) FROM bucket_configurations
  UNION ALL SELECT 'b2_buckets', COUNT(*) FROM b2_buckets;
"
```

## Performance Considerations

### Migration Speed

Migration speed depends on:
- **Data volume**: Larger datasets take longer
- **Batch size**: Larger batches are faster but use more memory
- **System resources**: CPU, memory, and disk I/O
- **Network**: If MongoDB is remote

Typical speeds:
- **Small datasets** (< 10k records): 1-2 minutes
- **Medium datasets** (10k-100k records): 5-15 minutes
- **Large datasets** (> 100k records): 30+ minutes

### Post-Migration Performance

After migration to MongoDB, you should see:
- **Better webhook performance**: Faster writes for high-volume events
- **Improved concurrency**: No more database lock errors
- **Faster queries**: Better indexing for large datasets
- **Horizontal scaling**: Ability to scale MongoDB across multiple nodes

## Rollback Plan

If you need to rollback to SQLite:

1. **Stop the application**:
   ```bash
   docker compose stop web
   ```

2. **Restore SQLite configuration**:
   ```bash
   # In stack.env:
   USE_MONGODB=0
   DATABASE_URI=sqlite:////data/backblaze_snapshots.db
   ```

3. **Restore backup if needed**:
   ```bash
   docker exec bbssr_web cp /data/backups/backblaze_snapshots_YYYYMMDD_HHMMSS.db /data/backblaze_snapshots.db
   ```

4. **Restart application**:
   ```bash
   docker compose up -d
   ```

## Best Practices

1. **Always backup**: Create backups before migration
2. **Test with dry run**: Always run `--dry-run` first
3. **Monitor progress**: Use `--verbose` for large migrations
4. **Plan downtime**: Schedule migration during low-activity periods
5. **Verify data**: Check record counts after migration
6. **Keep backups**: Retain SQLite backups for a reasonable period

## Next Steps

After successful migration:

1. **Monitor performance**: Watch for improvements in webhook processing
2. **Optimize MongoDB**: Consider additional indexing for your query patterns
3. **Update monitoring**: Adjust any monitoring that was specific to SQLite
4. **Plan scaling**: Consider MongoDB replica sets for high availability
5. **Clean up**: Remove old SQLite backups after confirming stability 