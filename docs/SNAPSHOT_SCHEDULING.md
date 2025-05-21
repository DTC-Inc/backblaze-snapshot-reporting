# Developing and Testing Features

This section provides guidance for developers working on specific features of the application.

## Snapshot Scheduling

The application supports multiple snapshot scheduling options:

### Schedule Types

1. **Interval-based**: Takes a snapshot every X hours
2. **Daily**: Takes a snapshot at a specific time each day
3. **Weekly**: Takes a snapshot on a specific day of the week at a specific time
4. **Monthly**: Takes a snapshot on a specific day of the month at a specific time

### Testing Different Schedule Types

To test different schedule types during development:

```bash
# Modify .env file with desired schedule settings
SNAPSHOT_SCHEDULE_TYPE=interval  # Options: interval, daily, weekly, monthly
SNAPSHOT_INTERVAL_HOURS=1        # For interval schedule: Take snapshot every hour
SNAPSHOT_HOUR=13                 # For daily/weekly/monthly: Hour of day (0-23)
SNAPSHOT_MINUTE=30               # For daily/weekly/monthly: Minute of hour (0-59)
SNAPSHOT_DAY_OF_WEEK=1           # For weekly: Day of week (0=Monday, 6=Sunday)
SNAPSHOT_DAY_OF_MONTH=15         # For monthly: Day of month (1-31)
SNAPSHOT_RETAIN_DAYS=7           # Number of days to keep snapshots
```

After changing these settings, restart the application:

```bash
docker-compose -f docker-compose.dev.yml restart web
```

For quicker testing, you can also use the web interface at `/settings/schedule` to change scheduling options without restarting.

### Debugging Schedule Issues

To debug scheduling issues, check the application logs:

```bash
docker-compose -f docker-compose.dev.yml logs -f web
```

Look for log entries related to snapshot scheduling:
- "Taking scheduled snapshot"
- "Interval of X hours has passed, taking snapshot" 
- "Daily snapshot time reached: HH:MM"
- "Weekly snapshot time reached: day X, time HH:MM"
- "Monthly snapshot time reached: day X, time HH:MM"

### Testing Snapshot Retention

To test the snapshot retention feature:

1. Set `SNAPSHOT_RETAIN_DAYS` to a small number (e.g., 1)
2. Take multiple snapshots
3. Wait for the cleanup to run (automatically during the next snapshot)
4. Verify that older snapshots have been deleted

You can manually trigger cleanup by visiting `/snapshots` and using the "Cleanup Old Snapshots" button.
