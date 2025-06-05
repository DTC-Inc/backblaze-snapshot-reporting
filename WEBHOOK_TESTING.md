# Webhook Events Testing Guide

This guide explains how to test the webhook events monitoring system using synthetic data and real HTTP requests.

## 🚀 Quick Start

### Option 1: Using the Bash Script (Recommended)

```bash
# Install test dependencies and generate test data
./run_webhook_tests.sh

# Clear existing data and generate 100 events
./run_webhook_tests.sh --clear-data --events 100

# Full test with HTTP webhook requests
./run_webhook_tests.sh --clear-data --send-webhooks
```

### Option 2: Using Python Directly

```bash
# Install dependencies
pip install -r test_requirements.txt

# Generate test data
python test_webhook_events.py

# See all options
python test_webhook_events.py --help
```

## 📋 What the Test Script Does

The test script (`test_webhook_events.py`) creates realistic synthetic data for testing:

### 🪣 Test Buckets Created
- `test-photos-backup` (webhooks enabled)
- `development-assets` (webhooks enabled) 
- `production-logs` (webhooks enabled)
- `user-uploads-staging` (webhooks enabled)
- `analytics-data-warehouse` (webhooks disabled)

### 🔐 Webhook Secrets Generated
Each enabled bucket gets a unique 32-character hex secret:
- Used for HMAC-SHA256 signature verification
- Automatically generated using `secrets.token_hex(16)`
- Stored in the bucket configuration

### 📊 Event Types Generated
- `b2:ObjectCreated:Upload` (file uploads)
- `b2:ObjectCreated:MultipartUpload` (large file uploads)
- `b2:ObjectCreated:Copy` (file copies)
- `b2:ObjectDeleted:Delete` (file deletions)
- `b2:HideMarkerCreated:Hide` (file hiding)

### 📁 Realistic File Paths
The script generates realistic file structures:
```
uploads/images/IMG_4532.jpg
2024/01/15/backup_84729.zip
documents/processed/report-analytics.pdf
temp/user-data/export_20241215_143022.csv
```

### 💾 Database Tables Populated
- **webhook_events**: Individual event records
- **bucket_configurations**: Webhook settings per bucket
- **b2_buckets**: Test B2 bucket metadata
- **webhook_statistics**: Aggregated statistics

## 🎯 Testing Scenarios

### Basic Data Generation
```bash
# Generate 50 events (default)
python test_webhook_events.py

# Generate 200 events
python test_webhook_events.py --events 200
```

### Data Management
```bash
# Clear all test data first
python test_webhook_events.py --clear-data

# Show current data summary
python test_webhook_events.py --summary-only
```

### HTTP Webhook Testing
```bash
# Send actual webhook requests to your running app
python test_webhook_events.py --send-webhooks

# Test against different URL
python test_webhook_events.py --send-webhooks --webhook-url http://localhost:8000
```

### Full Integration Test
```bash
# Complete test: clear data, generate events, send webhooks
python test_webhook_events.py --clear-data --events 100 --send-webhooks
```

## 🔍 Verifying the Test Data

After running the test script:

1. **Start your Flask app:**
   ```bash
   python run.py
   ```

2. **Visit the webhook events page:**
   ```
   http://localhost:5000/webhook_events
   ```

3. **Test the interface:**
   - Filter by bucket name
   - Filter by event type
   - Filter by time range
   - Click events to see details
   - Test real-time updates (if WebSocket connected)

## 🧪 Example Test Workflow

```bash
# 1. Clear any existing data and start fresh
./run_webhook_tests.sh --clear-data

# 2. Generate a good amount of test data
./run_webhook_tests.sh --events 150

# 3. Start your Flask app (in another terminal)
python run.py

# 4. Visit http://localhost:5000/webhook_events

# 5. Test the interface filters and features

# 6. Test real webhook receiving (with app running)
./run_webhook_tests.sh --send-webhooks

# 7. Check that new events appear in real-time
```

## 📊 Generated Data Examples

### Sample Webhook Event
```json
{
  "eventType": "b2:ObjectCreated:Upload",
  "eventTimestamp": "2024-12-15T10:30:45Z",
  "bucketName": "test-photos-backup",
  "bucketId": "bucket_548293",
  "objectName": "uploads/images/IMG_4532.jpg",
  "objectSize": 2847392,
  "objectVersionId": "4_z7482910_839472848",
  "contentType": "image/jpeg",
  "contentSha1": "da39a3ee5e6b4b0d3255bfef95601890afd80709",
  "requestId": "550e8400-e29b-41d4-a716-446655440000",
  "sourceIpAddress": "192.168.1.100",
  "userAgent": "B2 Python SDK/1.17.3"
}
```

### Sample Bucket Configuration
```python
{
  "bucket_name": "test-photos-backup",
  "webhook_enabled": True,
  "webhook_secret": "a1b2c3d4e5f6789012345678901234567890abcd",
  "events_to_track": ["b2:ObjectCreated:Upload", "b2:ObjectDeleted:Delete"]
}
```

## 🔧 Troubleshooting

### Import Errors
```bash
# Make sure you're in the correct directory
cd /path/to/backblaze-snapshot-reporting

# Install dependencies
pip install -r test_requirements.txt
```

### Database Errors
```bash
# Check if database file exists and has correct permissions
ls -la *.db

# Run with verbose error output
python test_webhook_events.py --events 10
```

### Webhook Connection Errors
```bash
# Make sure Flask app is running
python run.py

# Check the correct URL
curl http://localhost:5000/api/webhooks/backblaze

# Test with custom URL
python test_webhook_events.py --send-webhooks --webhook-url http://your-domain.com
```

## 🎲 Advanced Testing

### Custom Event Patterns
Modify the script to test specific scenarios:

```python
# In test_webhook_events.py, modify generate_test_events()

# Test burst of events from one bucket
for i in range(20):
    bucket_name = "test-photos-backup"  # Fixed bucket
    event_type = "b2:ObjectCreated:Upload"  # Fixed event type
    # ... rest of generation
```

### Performance Testing
```bash
# Generate large dataset
python test_webhook_events.py --clear-data --events 1000

# Test with many webhook requests
python test_webhook_events.py --send-webhooks --events 50
```

### Real-time Testing
1. Generate initial data
2. Start Flask app  
3. Open webhook events page
4. Run webhook sending in background
5. Watch events appear in real-time

## 📚 What's Generated

- **50+ realistic webhook events** (or custom amount)
- **5 test buckets** with varied configurations
- **Webhook secrets** for authentication testing
- **File paths** that look like real B2 usage
- **Proper B2 payload structure** matching official docs
- **HMAC signatures** for security testing

The test data will help you verify:
- ✅ Event filtering and searching
- ✅ Real-time WebSocket updates  
- ✅ Webhook signature verification
- ✅ Bucket-specific event views
- ✅ Statistics and aggregations
- ✅ UI responsiveness with data

Happy testing! 🎉 