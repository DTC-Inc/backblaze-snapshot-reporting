# Backblaze Snapshot Reporting

A Python web application that monitors Backblaze B2 usage and costs, helping you track spending and identify significant changes in your cloud storage expenses.

## Features

- Flexible snapshot scheduling (interval, daily, weekly, or monthly)
- Cost breakdowns by bucket and service type (storage, downloads, API calls)
- Detection of significant cost changes 
- Email notifications for cost threshold alerts
- Cost trends analysis
- Automatic retention and cleanup of old snapshot data
- Dockerized for easy deployment
- Efficient API usage to minimize Backblaze charges
- Data caching to reduce API calls
- SQLite database for snapshot history

## Getting Started

### Prerequisites

- Docker and Docker Compose
- Backblaze B2 account with API credentials
- SMTP server access (if using email notifications)

### Configuration

1. Create a `.env` file in the project root:

```
B2_APPLICATION_KEY_ID=your_key_id_here
B2_APPLICATION_KEY=your_application_key_here
SNAPSHOT_INTERVAL_HOURS=24
COST_CHANGE_THRESHOLD=10.0
SECRET_KEY=your_secret_key_here

# Email notifications (optional)
EMAIL_ENABLED=True
EMAIL_SENDER=your_email@example.com
EMAIL_RECIPIENTS=recipient1@example.com,recipient2@example.com
EMAIL_SERVER=smtp.example.com
EMAIL_PORT=587
EMAIL_USERNAME=your_username
EMAIL_PASSWORD=your_password
EMAIL_USE_TLS=True
```

### Installation and Running

1. Build and start the service:

```bash
docker-compose up -d
```

2. Access the web interface:
   - Open http://localhost:5000 in your browser (or the port specified in your .env file)

### Cloudflare Tunnel Integration (Optional)

For secure remote access without exposing ports:

1. Add your Cloudflare Tunnel token to the `.env` file:
```
CLOUDFLARE_TUNNEL_TOKEN=your_tunnel_token_here
```

2. Start the application with Cloudflared:
```bash
docker-compose --profile with-cloudflared up -d
```

See [Cloudflare Tunnel Documentation](docs/CLOUDFLARE_TUNNEL.md) for detailed setup instructions.

## Usage

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

1. **Enable accurate bucket size calculation** by setting in your `.env` file:
   ```
   USE_ACCURATE_BUCKET_SIZE=True
   ```

2. **Why use this feature?**
   - Get bucket sizes that more closely match what Backblaze reports
   - More accurately calculate storage costs
   - Comprehensive reporting that accounts for all file versions

3. **Performance considerations:**
   - More accurate reporting may require more API calls to Backblaze B2
   - For extremely large buckets, calculation may take longer
   - Results are cached according to your `BUCKET_STATS_CACHE_HOURS` setting

For more details, see [Accurate Bucket Size Reporting](docs/ACCURATE_BUCKET_SIZE_REPORTING.md).

### S3 API Integration

For even more accurate bucket size reporting, the application can use Backblaze B2's S3-compatible API:

1. **Enable S3 API integration** by setting in your `.env` file:
   ```
   USE_S3_API=True
   ```

2. **Benefits of S3 API integration:**
   - Maximum accuracy matching Backblaze's reported storage usage
   - Proper handling of all object versions and complex directory structures
   - Comprehensive object metadata

3. **Requirements:**
   - Application Key with S3 API access permissions
   - Properly configured Backblaze B2 buckets

For more details, see [S3 API Integration](docs/S3_API_INTEGRATION.md).

## Configuration Options

| Environment Variable | Description | Default |
|---------------------|-------------|---------|
| B2_APPLICATION_KEY_ID | Backblaze B2 Application Key ID | - |
| B2_APPLICATION_KEY | Backblaze B2 Application Key | - |
| USE_ACCURATE_BUCKET_SIZE | Use accurate but potentially slower bucket size calculation | True |
| USE_S3_API | Use S3 API for maximum bucket size accuracy | True |
| SNAPSHOT_SCHEDULE_TYPE | Type of snapshot schedule ('interval', 'daily', 'weekly', 'monthly') | interval |
| SNAPSHOT_INTERVAL_HOURS | Hours between automated snapshots (used with 'interval' schedule) | 24 |
| SNAPSHOT_HOUR | Hour of day for scheduled snapshots (0-23) | 0 |
| SNAPSHOT_MINUTE | Minute of hour for scheduled snapshots (0-59) | 0 |
| SNAPSHOT_DAY_OF_WEEK | Day of week for weekly snapshots (0=Monday, 6=Sunday) | 0 |
| SNAPSHOT_DAY_OF_MONTH | Day of month for monthly snapshots (1-31) | 1 |
| SNAPSHOT_RETAIN_DAYS | Days to keep snapshot data | 90 |
| COST_CHANGE_THRESHOLD | Percentage change to trigger alerts | 10.0 |
| EMAIL_ENABLED | Enable email notifications | False |
| EMAIL_SENDER | From email address for notifications | - |
| EMAIL_RECIPIENTS | Comma-separated list of recipients | - |
| EMAIL_SERVER | SMTP server hostname | - |
| EMAIL_PORT | SMTP server port | 587 |
| EMAIL_USERNAME | SMTP username | - |
| EMAIL_PASSWORD | SMTP password | - |
| EMAIL_USE_TLS | Use TLS for SMTP connection | True |
| EMAIL_USE_SSL | Use SSL for SMTP connection | False |
| STORAGE_COST_PER_GB | Cost per GB for storage | 0.005 |
| DOWNLOAD_COST_PER_GB | Cost per GB for downloads | 0.01 |
| CLASS_A_TRANSACTION_COST | Cost per 1000 Class A transactions | 0.004 |
| CLASS_B_TRANSACTION_COST | Cost per 1000 Class B transactions | 0.0004 |

## Data Persistence

Data is stored in an SQLite database at `/data/backblaze_snapshots.db` inside the container. This is mapped to a Docker volume for persistence.

## Email Notifications

The application can send email notifications when significant cost changes are detected:

1. Enable email notifications by setting `EMAIL_ENABLED=True` in your `.env` file
2. Configure your SMTP server settings and notification recipients
3. Notifications will be sent automatically when cost changes exceed the threshold
4. To test email notifications, access the `/api/test-email` endpoint

Notifications include:
- Summary of cost changes by category (storage, download, API)
- Detailed breakdown of bucket-specific changes
- Links to the dashboard for more information

## License

MIT
