# Email Notification System

This document explains how to configure and test the email notification system for the Backblaze Snapshot Reporting application.

## Configuration

Email notifications are configured through environment variables or the web interface at `/settings`.

### Environment Variables

```bash
# Email notification settings
EMAIL_ENABLED=True
EMAIL_SENDER=your_email@example.com
EMAIL_RECIPIENTS=recipient1@example.com,recipient2@example.com
EMAIL_SERVER=smtp.example.com
EMAIL_PORT=587
EMAIL_USERNAME=your_username
EMAIL_PASSWORD=your_password
EMAIL_USE_TLS=True
EMAIL_USE_SSL=False
```

### Cost Change Threshold

The `COST_CHANGE_THRESHOLD` variable (default: 10.0) determines the percentage change in cost that triggers a notification. For example, with the default setting, a 10% or greater change in storage, download, or API costs will trigger a notification.

## Testing Email Notifications

### Through the Web Interface

1. Go to `/settings` in the web interface
2. Configure your email settings
3. Click the "Test Email Configuration" button
4. A test email will be sent to the configured recipients

### Through the API

You can also test email notifications via the API:

```bash
# Using curl (Linux/WSL2)
curl http://localhost:5000/api/test-email

# Using PowerShell (Windows)
Invoke-RestMethod http://localhost:5000/api/test-email
```

## Notification History

All sent notifications are recorded in the database. You can view notification history in the web interface at `/settings`.

You can also query the database directly:

```sql
SELECT * FROM notification_history ORDER BY timestamp DESC LIMIT 10;
```

## Debugging Email Issues

If emails aren't being sent, check the following:

1. Make sure `EMAIL_ENABLED` is set to `True`
2. Verify SMTP server details (server, port, username, password)
3. Check application logs for email-related error messages:
   ```bash
   docker-compose -f docker-compose.dev.yml logs -f web
   ```
4. Some email providers require specific security settings. Try adjusting `EMAIL_USE_TLS` and `EMAIL_USE_SSL` as needed.
5. Make sure your email provider allows SMTP access from applications.
