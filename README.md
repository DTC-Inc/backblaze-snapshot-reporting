# Backblaze Snapshot Reporting

A Python web application that monitors Backblaze B2 usage and costs, helping you track spending and identify significant changes in your cloud storage expenses.

## ⚡ Features

- **Automated Cost Tracking**: Scheduled snapshots of your Backblaze B2 usage and costs
- **Cost Change Alerts**: Get notified when your costs change significantly
- **Bucket-Level Analysis**: See which buckets are costing you the most
- **Historical Trends**: Track cost changes over time with beautiful charts
- **Webhook Event Monitoring**: Real-time monitoring of Backblaze object events
- **Redis Buffering**: High-performance event buffering to reduce database writes
- **Multiple Database Options**: SQLite (default) or MongoDB for high-volume operations
- **Database Migration**: Built-in script to migrate from SQLite to MongoDB
- **Responsive Web Interface**: Clean, modern UI that works on all devices
- **Docker Support**: Easy deployment with Docker Compose
- **S3 API Support**: Optional S3 API compatibility for enhanced performance

## Deployment Options

### Prerequisites

- Docker and Docker Compose
- Backblaze B2 account with API credentials
- SMTP server access (if using email notifications)

### Quick Start

1. Clone this repository:
   ```
   git clone https://github.com/your-username/backblaze-snapshot-reporting.git
   cd backblaze-snapshot-reporting
   ```

2. Create your environment file:
   ```
   cp stack.env.example stack.env
   ```

3. Edit the `stack.env` file and add your Backblaze B2 API credentials:
   ```
   # Required
   B2_APPLICATION_KEY_ID=your_key_id
   B2_APPLICATION_KEY=your_application_key
   
   # Optional: Change the default stack name if desired
   STACK_NAME=bbssr
   ```

4. Start the services:
   ```
   docker compose up -d
   ```

   For production with external volumes:
   ```
   docker compose -f docker-compose.yml -f docker-compose.external.yml up -d
   ```

   For local development:
   ```
   docker compose -f docker-compose.yml -f docker-compose.local.yml up -d
   ```

5. Access the application at http://localhost:5000 (or the port you configured)

### Storage Configuration Options

The application supports three deployment options:

#### 1. Docker Volumes (Default for Development)

By default, the application uses Docker local volumes for data storage. This is recommended for development.

In your `stack.env` file:
```
USE_DOCKER_VOLUMES=true
DATA_VOLUME_NAME=bbssr_data  # Optional, defaults to bbssr_data
```

Start the application with:
```
docker compose -f docker-compose.yml -f docker-compose.local.yml up -d
```

#### 2. External Volumes (Recommended for Production)

For production deployments, it's recommended to use external volumes that you create and manage separately:

1. Create the external volume:
   ```
   docker volume create bbssr_data
   ```

2. Start the application using the external volume configuration:
   ```
   docker compose -f docker-compose.yml -f docker-compose.external.yml up -d
   ```

This ensures your data persists even if you remove the stack.

#### 3. Local Storage Paths

If you prefer to use local filesystem paths instead of Docker volumes:

1. In your `stack.env` file:
   ```
   USE_DOCKER_VOLUMES=false
   DATA_BASE_PATH=/path/to/your/data
   ```

2. Start the application using the local storage override:
   ```
   docker compose -f docker-compose.yml -f docker-compose.local.yml up -d
   ```

### Database Options

#### SQLite (Default)

By default, the application uses SQLite, which is simple and requires no additional configuration.

#### MongoDB

To use MongoDB instead of SQLite:

1. Set `USE_MONGODB=true` in your `stack.env` file
2. Configure the MongoDB settings:
   ```
   USE_MONGODB=true
   MONGODB_USER=bbssr_user
   MONGODB_PASSWORD=secure_password_here
   MONGODB_DB=bbssr_db
   ```

If you're using external volumes for production, also create the MongoDB volume:
```
docker volume create bbssr_db
```

#### Migrating from SQLite to MongoDB

If you're currently using SQLite and want to migrate to MongoDB for better performance with high-volume webhook events, the application includes a built-in migration script.

**When to migrate:**
- You experience database lock errors with high webhook volume
- You need better performance for concurrent operations
- You're processing more than 100 webhook events per second
- You want to scale horizontally in the future

**Quick migration steps:**

1. **Enable MongoDB** in your stack configuration:
   ```bash
   # In stack.env, add:
   USE_MONGODB=1
   DATABASE_URI=mongodb://mongodb:27017/bbssr_db
   ```

2. **Start MongoDB** service:
   ```bash
   docker compose up -d mongodb
   ```

3. **Run migration dry-run** to see what will be migrated:
   ```bash
   docker exec bbssr_web python scripts/migrate_sqlite_to_mongodb.py --dry-run --verbose
   ```

4. **Backup your SQLite database**:
   ```bash
   docker exec bbssr_web cp /data/backblaze_snapshots.db /data/backups/backup_$(date +%Y%m%d_%H%M%S).db
   ```

5. **Run the migration**:
   ```bash
   docker exec bbssr_web python scripts/migrate_sqlite_to_mongodb.py --verbose
   ```

6. **Restart the application** with new configuration:
   ```bash
   docker compose up -d
   ```

For detailed migration instructions, troubleshooting, and rollback procedures, see [docs/MIGRATION_SQLITE_TO_MONGODB.md](docs/MIGRATION_SQLITE_TO_MONGODB.md).

**Migration features:**
- **Safe migration**: Dry-run mode to preview changes
- **Batch processing**: Efficient handling of large datasets
- **Progress tracking**: Real-time progress updates and statistics
- **Error recovery**: Handles partial failures gracefully
- **Data integrity**: Maintains foreign key relationships
- **Rollback support**: Easy rollback to SQLite if needed

### Deploying with Portainer

The docker-compose configuration is compatible with Portainer. To deploy:

1. In Portainer, go to Stacks → Add stack
2. Upload the docker-compose.yml file or paste its contents
3. Set your environment variables:
   - For SQLite (default): Set `STACK_NAME=bbssr` and other required variables
   - For MongoDB: Add `USE_MONGODB=1` to enable the MongoDB service
4. Deploy the stack

For persistent volumes in Portainer:
1. First create the volume(s) in Portainer's Volumes section
2. Make sure to name them exactly as configured (e.g., bbssr_data)
3. In the advanced deployment options in Portainer, check "External volumes" 

### Cloudflare Tunnel Integration (Optional)

For secure remote access without exposing ports:

1. Add your Cloudflare Tunnel token to the `stack.env` file:
```
CLOUDFLARE_TUNNEL_TOKEN=your_tunnel_token_here
```

2. Cloudflared service is included in the standard docker-compose.yml file

## Application Usage

- Dashboard shows latest snapshot and cost trends
- Significant cost changes are highlighted
- Take manual snapshots as needed
- View detailed data by bucket

### Snapshot Scheduling

Configure snapshot scheduling to meet your needs:

1. Navigate to "Snapshot Scheduling" in the sidebar
2. Choose from multiple schedule types:
   - **Interval**: Take snapshots every X hours
   - **Daily**: Take a snapshot at a specific time each day
   - **Weekly**: Take a snapshot on a specific day of the week
   - **Monthly**: Take a snapshot on a specific day of the month
3. Configure retention period to automatically clean up old snapshots

You can also take manual snapshots at any time from the dashboard or snapshots page.

### Accurate Bucket Size Reporting

The application includes improved bucket size reporting that provides more accurate storage usage information:

1. **Enable accurate bucket size calculation** by setting in your `stack.env` file:
   ```
   USE_ACCURATE_BUCKET_SIZE=True
   ```

2. **Why use this feature?**
   - Get bucket sizes that more closely match what Backblaze reports
   - More accurately calculate storage costs
   - Comprehensive reporting that accounts for all file versions

### S3 API Integration

For even more accurate bucket size reporting, the application can use Backblaze B2's S3-compatible API:

1. **Enable S3 API integration** by setting in your `stack.env` file:
   ```
   USE_S3_API=True
   ```

## Maintenance

### Viewing Logs

```
docker compose logs -f
```

### Updating the Application

```
git pull
docker compose build
docker compose up -d
```

### Backup Data

#### For Docker Volumes

```
docker run --rm -v bbssr_data:/data -v $(pwd):/backup alpine tar -czf /backup/data.tar.gz /data
```

#### For Local Storage

Simply back up the directory specified in `DATA_BASE_PATH`.

## Troubleshooting

### Check Container Status

```
docker compose ps
```

### Container Won't Start

Check the logs for errors:
```
docker compose logs web
```

### WebSocket Connection Issues

If you experience WebSocket connection issues:

1. Make sure port 5000 is open on your firewall
2. Check the logs for any socket.io related errors
3. Try restarting the container
```
docker compose restart web
```

### Webhook Configuration

The application now supports real-time webhooks from Backblaze B2 to track object-level events. This allows you to monitor file uploads, downloads, deletions, and other activities as they happen.

#### Setting Up Webhooks

1. **Navigate to Webhook Management** in the application sidebar
2. **Add your buckets** and configure which events to track:
   - Object Created (file uploads)
   - Object Deleted (file deletions)
   - Object Restored (files restored from archive)
   - Object Archived (files moved to archive)
3. **Copy the webhook URL** provided by the application
4. **Configure your Backblaze B2 bucket** to send webhooks to this URL
5. **Test the configuration** by uploading or deleting a file

#### Webhook Features

- **Real-time event tracking**: See object-level activity as it happens
- **Per-bucket configuration**: Configure different settings for each bucket
- **Event filtering**: Choose which event types to track
- **Security**: Webhook signature verification with auto-generated secrets
- **Analytics**: View statistics and trends for webhook activity
- **Event history**: Browse and search through historical webhook events

#### Webhook Security

For production deployments, always:
- Use HTTPS for your webhook endpoints
- Enable webhook secrets for signature verification
- Monitor webhook activity for unusual patterns
- Keep webhook secrets secure and rotate them periodically

For detailed webhook setup instructions, see [docs/WEBHOOK_SETUP.md](docs/WEBHOOK_SETUP.md).

## Configuration Options

| Environment Variable | Description | Default |
|---------------------|-------------|---------|
| STACK_NAME | Prefix for container names and volumes | bbssr |
| APP_PORT | Port to expose the web application | 5000 |
| PID | Process ID for the container user | 1000 |
| GID | Group ID for the container user | 1000 |
| DATA_PATH | Base path for local data storage | ./data |
| USE_MONGODB | Use MongoDB instead of SQLite | false |
| MONGODB_USER | MongoDB username | bbssr_user |
| MONGODB_PASSWORD | MongoDB password | - |
| MONGODB_DB | MongoDB database name | bbssr_db |
| B2_APPLICATION_KEY_ID | Backblaze B2 Application Key ID | - |
| B2_APPLICATION_KEY | Backblaze B2 Application Key | - |
| USE_ACCURATE_BUCKET_SIZE | Use accurate but potentially slower bucket size calculation | True |
| USE_S3_API | Use S3 API for maximum bucket size accuracy | True |
| SNAPSHOT_SCHEDULE_TYPE | Type of snapshot schedule ('interval', 'daily', 'weekly', 'monthly') | interval |
| SNAPSHOT_INTERVAL_HOURS | Hours between automated snapshots (used with 'interval' schedule) | 24 |
| SNAPSHOT_RETAIN_DAYS | Days to keep snapshot data | 90 |
| COST_CHANGE_THRESHOLD | Percentage change to trigger alerts | 10.0 |
| EMAIL_ENABLED | Enable email notifications | False |

## Development

For development setup and contribution guidelines, see [DEVELOPMENT.md](DEVELOPMENT.md).

## License

MIT
