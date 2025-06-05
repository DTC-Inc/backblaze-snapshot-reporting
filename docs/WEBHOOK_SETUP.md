# Backblaze B2 Webhook Setup Guide

This guide explains how to set up and configure webhooks for Backblaze B2 buckets to track object events in real-time.

## Overview

The webhook functionality allows you to:
- Receive real-time notifications when objects are created, deleted, restored, or archived in your B2 buckets
- Track object-level activity across all your configured buckets
- View detailed statistics and event history
- Configure webhook settings per bucket with custom event filtering

## Quick Start

1. **Access Webhook Management**: Navigate to the "Webhook Management" page in the application
2. **Add a Bucket**: Enter your bucket name and select the events you want to track
3. **Configure in B2**: Use the provided webhook URL to configure your bucket in Backblaze B2
4. **Test**: Create or delete a file in your bucket to verify events are being received

## Detailed Setup Instructions

### Step 1: Configure Bucket in the Application

1. Go to **Webhook Management** in the navigation menu
2. In the "Add New Bucket" section:
   - Enter your bucket name exactly as it appears in B2
   - Select the event types you want to track:
     - **Object Created**: Triggered when files are uploaded
     - **Object Deleted**: Triggered when files are deleted
     - **Object Restored**: Triggered when files are restored from archive
     - **Object Archived**: Triggered when files are archived
   - Optionally provide a webhook secret (leave empty to auto-generate)
3. Click "Add Bucket Configuration"

### Step 2: Configure Webhook in Backblaze B2

1. Log in to your Backblaze B2 Console
2. Navigate to your bucket settings
3. Find the "Event Notifications" or "Webhooks" section
4. Add a new webhook with:
   - **URL**: Copy the webhook URL from the application (shown in the configuration section)
   - **Events**: Select the same events you configured in the application
   - **Secret**: Use the webhook secret from the application (if configured)

### Step 3: Test the Configuration

1. Upload or delete a file in your configured bucket
2. Return to the Webhook Management page
3. Check the "Recent Webhook Events" section to see if events are being received
4. View the statistics cards for real-time counts

## Webhook URL Format

The webhook URL format is:
```
https://your-app-domain.com/api/webhooks/backblaze
```

For bucket-specific configurations, you can optionally append:
```
https://your-app-domain.com/api/webhooks/backblaze?bucket=your-bucket-name
```

## Supported Event Types

| Event Type | Description |
|------------|-------------|
| `b2:ObjectCreated` | File uploaded to bucket |
| `b2:ObjectDeleted` | File deleted from bucket |
| `b2:ObjectRestore` | File restored from archive |
| `b2:ObjectArchive` | File archived |

## Webhook Security

### Signature Verification

When you configure a webhook secret, the application will verify the signature of incoming webhooks using HMAC-SHA256. This ensures that webhooks are genuinely from Backblaze and haven't been tampered with.

The signature is expected in the `X-Hub-Signature-256` header in the format:
```
sha256=<calculated_signature>
```

### Best Practices

1. **Always use webhook secrets** for production environments
2. **Use HTTPS** for your webhook endpoints
3. **Monitor webhook events** regularly for unexpected activity
4. **Keep webhook secrets secure** and rotate them periodically

## Event Data Structure

Each webhook event contains the following information:
- Event timestamp
- Bucket name
- Event type
- Object key (file path)
- Object size
- Object version ID
- Source IP address
- User agent
- Request ID

## Managing Configurations

### Editing Bucket Configurations

1. Find your bucket in the "Bucket Configurations" table
2. Click "Edit" to modify:
   - Enable/disable webhooks
   - Change tracked event types
   - Update webhook secret
3. Save changes and update your B2 bucket configuration if needed

### Viewing Webhook Events

The application provides several ways to view webhook activity:
- **Recent Events**: Live view of the most recent webhook events
- **Statistics Cards**: Quick overview of total events, recent activity, and active buckets
- **Event Filtering**: Filter events by bucket name or event type

### Deleting Configurations

1. Click "Delete" next to the bucket configuration
2. Confirm the deletion
3. Remember to also remove the webhook configuration from your B2 bucket

## API Endpoints

The webhook functionality exposes several API endpoints:

### Receive Webhooks
```
POST /api/webhooks/backblaze
```
Receives webhook events from Backblaze B2.

### Get Webhook Events
```
GET /api/webhooks/events?limit=100&bucket=bucket-name&event_type=b2:ObjectCreated
```
Retrieve webhook events with optional filtering.

### Get Webhook Statistics
```
GET /api/webhooks/statistics?days=30
```
Get webhook activity statistics.

### Manage Bucket Configurations
```
GET    /api/webhooks/buckets                    # List all configurations
GET    /api/webhooks/buckets/{bucket-name}      # Get specific configuration
POST   /api/webhooks/buckets/{bucket-name}      # Create/update configuration
DELETE /api/webhooks/buckets/{bucket-name}      # Delete configuration
```

## Troubleshooting

### Webhooks Not Being Received

1. **Check bucket configuration**: Ensure the bucket name matches exactly
2. **Verify webhook URL**: Make sure the URL is accessible from the internet
3. **Check event types**: Ensure you've selected the correct event types in both places
4. **Review logs**: Check application logs for any error messages

### Invalid Signature Errors

1. **Verify webhook secret**: Ensure the secret matches between the app and B2
2. **Check header format**: Backblaze should send the signature in `X-Hub-Signature-256`
3. **Test without secret**: Temporarily disable signature verification to isolate the issue

### Missing Events

1. **Check event type configuration**: Ensure all desired event types are enabled
2. **Verify bucket permissions**: Ensure the bucket is configured to send webhooks
3. **Monitor rate limits**: Very high-frequency events might be rate-limited

## Environment Variables

You can configure webhook behavior using environment variables:

```bash
# Enable/disable webhook functionality
WEBHOOK_ENABLED=true

# Auto-generate webhook secrets
WEBHOOK_SECRET_AUTO_GENERATE=true

# Default event types for new configurations
WEBHOOK_DEFAULT_EVENTS=b2:ObjectCreated,b2:ObjectDeleted
```

## Security Considerations

- Webhook endpoints are publicly accessible to receive events from Backblaze
- Authentication is handled through webhook signatures (when configured)
- Event data is stored in the local database and visible to authenticated users
- Webhook secrets should be treated as sensitive information
- Consider implementing rate limiting for high-traffic buckets
- Regularly review webhook event logs for unusual activity

## Performance Notes

- Webhook processing is designed to be fast and non-blocking
- Events are stored in a local SQLite database
- Statistics are pre-calculated for quick dashboard loading
- Large volumes of events (1000s per minute) may require database optimization
- Consider implementing event cleanup policies for long-running installations 