#!/usr/bin/env python3
"""
Synthetic Test Script for Webhook Events Monitoring
==================================================

This script generates realistic test data for the Backblaze webhook events monitoring system.
It creates fake B2 events, webhook configurations, and can even send test webhook requests.

Usage:
    python test_webhook_events.py [options]

Options:
    --clear-data    Clear all existing test data first
    --send-webhooks Send actual HTTP webhook requests to test the receiver
    --test-deletion Test deletion API endpoints
    --events N      Number of events to generate (default: 50)
    --buckets N     Number of test buckets to create (default: 5)
"""

import os
import sys
import json
import secrets
import random
import hmac
import hashlib
import requests
import argparse
from datetime import datetime, timedelta
from faker import Faker

# Add the app directory to the Python path so we can import our modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'app'))

from models.database import Database
from config import DATABASE_URI

# Initialize faker for generating realistic test data
fake = Faker()

class WebhookTestGenerator:
    def __init__(self, database_path=None):
        """Initialize the test generator with database connection."""
        if database_path is None:
            database_path = DATABASE_URI.replace('sqlite:///', '')
        
        self.db = Database(database_path)
        print(f"✅ Connected to database: {database_path}")
        
        # Test bucket names
        self.test_buckets = [
            "test-photos-backup",
            "development-assets", 
            "production-logs",
            "user-uploads-staging",
            "analytics-data-warehouse"
        ]
        
        # B2 event types
        self.event_types = [
            "b2:ObjectCreated:Upload",
            "b2:ObjectCreated:MultipartUpload", 
            "b2:ObjectCreated:Copy",
            "b2:ObjectDeleted:Delete",
            "b2:HideMarkerCreated:Hide"
        ]
        
        # Sample file extensions and their typical sizes
        self.file_patterns = {
            '.jpg': (50000, 5000000),    # 50KB - 5MB
            '.png': (10000, 2000000),    # 10KB - 2MB
            '.pdf': (100000, 10000000),  # 100KB - 10MB
            '.mp4': (1000000, 100000000), # 1MB - 100MB
            '.zip': (500000, 50000000),  # 500KB - 50MB
            '.log': (1000, 1000000),     # 1KB - 1MB
            '.json': (500, 100000),      # 500B - 100KB
            '.csv': (5000, 5000000),     # 5KB - 5MB
            '.txt': (100, 50000),        # 100B - 50KB
            '.sql': (1000, 10000000),    # 1KB - 10MB
        }

    def generate_webhook_secret(self):
        """Generate a secure webhook secret (32 hex characters)."""
        return secrets.token_hex(16)

    def setup_test_bucket_configurations(self):
        """Create webhook configurations for test buckets."""
        print("\n📦 Setting up test bucket configurations...")
        
        for i, bucket_name in enumerate(self.test_buckets):
            # Enable webhooks for most buckets, but not all
            # Let's enable webhooks for all test_buckets for simplicity during send_test_webhooks phase
            # The disabling logic can be conditional if truly needed for a specific test scenario later.
            webhook_enabled = True 
            
            if webhook_enabled:
                webhook_secret = self.generate_webhook_secret()
                # For testing, let's allow all defined event types for enabled buckets
                events_to_track = list(self.event_types) 
            else:
                # This else block might not be hit if webhook_enabled is always True now
                webhook_secret = None
                events_to_track = []
            
            success = self.db.save_bucket_configuration(
                bucket_name=bucket_name,
                webhook_enabled=webhook_enabled,
                webhook_secret=webhook_secret,
                events_to_track=events_to_track
            )
            
            status = "✅ enabled" if webhook_enabled else "❌ disabled"
            print(f"  {bucket_name}: {status}")
            if webhook_enabled:
                print(f"    Secret: {webhook_secret}")
                print(f"    Events: {', '.join(events_to_track)}")

    def generate_file_path(self):
        """Generate a realistic file path with random directory structure."""
        # Random directory depth (1-4 levels)
        depth = random.randint(1, 4)
        
        path_parts = []
        for _ in range(depth):
            if random.random() < 0.3:
                # Sometimes use date-based folders
                path_parts.append(fake.date_object().strftime('%Y/%m/%d'))
            else:
                # Regular folder names
                folder_names = [
                    'uploads', 'documents', 'images', 'videos', 'backups',
                    'exports', 'temp', 'archive', 'processed', 'raw',
                    'user-data', 'system-logs', 'analytics', 'reports'
                ]
                path_parts.append(random.choice(folder_names))
        
        # Generate filename
        extensions = list(self.file_patterns.keys())
        extension = random.choice(extensions)
        
        # Different filename patterns
        filename_patterns = [
            f"{fake.word()}_{fake.random_int(1000, 9999)}{extension}",
            f"{fake.date_object().strftime('%Y-%m-%d')}-{fake.word()}{extension}",
            f"backup_{fake.random_int(10000, 99999)}{extension}",
            f"{fake.word()}-{fake.word()}{extension}",
            f"IMG_{fake.random_int(1000, 9999)}{extension}",
            f"doc_{datetime.now().strftime('%Y%m%d_%H%M%S')}{extension}"
        ]
        
        filename = random.choice(filename_patterns)
        
        return '/'.join(path_parts + [filename])

    def generate_object_size(self, file_path):
        """Generate realistic object size based on file extension."""
        extension = os.path.splitext(file_path)[1].lower()
        
        if extension in self.file_patterns:
            min_size, max_size = self.file_patterns[extension]
            return random.randint(min_size, max_size)
        else:
            # Default size for unknown extensions
            return random.randint(1000, 1000000)

    def generate_webhook_payload(self, bucket_name, event_type, object_key, object_size):
        """Generate a realistic B2 webhook payload."""
        event_timestamp = fake.date_time_between(
            start_date='-7d', 
            end_date='now'
        ).isoformat() + 'Z'
        
        # Base payload structure according to B2 docs
        payload = {
            "eventType": event_type,
            "eventTimestamp": event_timestamp,
            "bucketName": bucket_name,
            "bucketId": f"bucket_{fake.random_int(100000, 999999)}",
            "objectName": object_key,
            "objectSize": object_size,
            "objectVersionId": f"4_z{fake.random_int(1000000, 9999999)}_{fake.random_int(100000000, 999999999)}",
            "contentType": self.guess_content_type(object_key),
            "contentSha1": fake.sha1(),
            "requestId": fake.uuid4(),
            "sourceIpAddress": fake.ipv4(),
            "userAgent": random.choice([
                "B2 Java SDK/6.1.1",
                "B2 Python SDK/1.17.3", 
                "B2 CLI/3.2.1",
                "rclone/v1.60.1",
                "Duplicacy/2.7.2"
            ])
        }
        
        # Add event-specific fields
        if "Created" in event_type:
            payload.update({
                "contentLength": object_size,
                "uploadTimestamp": event_timestamp
            })
        elif "Deleted" in event_type:
            payload.update({
                "deleteTimestamp": event_timestamp
            })
        elif "Hide" in event_type:
            payload.update({
                "hideTimestamp": event_timestamp
            })
            
        return payload

    def guess_content_type(self, object_key):
        """Guess content type from file extension."""
        extension = os.path.splitext(object_key)[1].lower()
        
        content_types = {
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.gif': 'image/gif',
            '.pdf': 'application/pdf',
            '.mp4': 'video/mp4',
            '.zip': 'application/zip',
            '.log': 'text/plain',
            '.txt': 'text/plain',
            '.json': 'application/json',
            '.csv': 'text/csv',
            '.sql': 'application/sql',
            '.xml': 'application/xml',
            '.html': 'text/html'
        }
        
        return content_types.get(extension, 'application/octet-stream')

    def generate_test_events(self, num_events=50):
        """Generate a specified number of test webhook events."""
        print(f"\n🎲 Generating {num_events} test webhook events...")
        
        generated_events = []
        
        for i in range(num_events):
            # Pick random bucket and event type
            bucket_name = random.choice(self.test_buckets)
            event_type = random.choice(self.event_types)
            
            # Generate file details
            object_key = self.generate_file_path()
            object_size = self.generate_object_size(object_key)
            
            # Create webhook payload
            payload = self.generate_webhook_payload(bucket_name, event_type, object_key, object_size)
            
            # Save to database using the payload directly (save_webhook_event expects webhook format)
            # The save_webhook_event method expects the webhook payload format, not database field names
            # Note: B2 sends 'objectName' but save_webhook_event expects 'objectKey', so provide both
            webhook_payload_for_db = {
                'eventTimestamp': payload['eventTimestamp'],
                'bucketName': bucket_name,
                'eventType': event_type,
                'objectName': object_key,     # Correct B2 field name
                'objectKey': object_key,      # What save_webhook_event expects (seems to be a bug)
                'objectSize': object_size,
                'objectVersionId': payload['objectVersionId'],
                'sourceIpAddress': payload['sourceIpAddress'],
                'userAgent': payload['userAgent'],
                'requestId': payload['requestId'],
                # Include the full payload as well
                **payload
            }
            
            # Save to database
            event_id = self.db.save_webhook_event(webhook_payload_for_db)
            generated_events.append((payload, webhook_payload_for_db))
            
            if (i + 1) % 10 == 0:
                print(f"  ✅ Generated {i + 1}/{num_events} events")
        
        print(f"✅ Successfully generated {num_events} test events")
        return generated_events

    def create_webhook_signature(self, payload_json, secret):
        """Create HMAC-SHA256 signature for webhook payload."""
        signature = hmac.new(
            secret.encode('utf-8'),
            payload_json.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        return f"sha256={signature}"

    def send_test_webhooks(self, base_url="http://localhost:5000", num_requests=5):
        """Send actual HTTP webhook requests to test the receiver endpoint."""
        print(f"\n🌐 Sending {num_requests} test webhook requests to {base_url}...")
        
        webhook_url = f"{base_url}/api/webhooks/backblaze"
        
        for i in range(num_requests):
            # Generate test event
            bucket_name = random.choice(self.test_buckets)
            event_type = random.choice(self.event_types)
            object_key = self.generate_file_path()
            object_size = self.generate_object_size(object_key)
            
            payload = self.generate_webhook_payload(bucket_name, event_type, object_key, object_size)
            payload_json = json.dumps(payload)
            
            # Get bucket configuration for secret
            print(f"  DEBUG: Attempting to get config for bucket: {bucket_name} for webhook {i+1}")
            bucket_config = self.db.get_bucket_configuration(bucket_name)
            
            headers = {
                'Content-Type': 'application/json',
                'User-Agent': payload.get('userAgent', 'Test-Webhook-Client/1.0')
            }
            
            # Add signature if bucket has webhook secret
            if bucket_config and bucket_config.get('webhook_secret'):
                secret_for_signing = bucket_config['webhook_secret']
                print(f"  DEBUG: Using secret for signing for bucket {bucket_name} (webhook {i+1}): [{secret_for_signing}]")
                print(f"  DEBUG: Payload JSON for signing (webhook {i+1}): [{payload_json}]")
                signature = self.create_webhook_signature(payload_json, secret_for_signing)
                headers['X-Hub-Signature-256'] = signature
                print(f"  DEBUG: Generated signature for webhook {i+1}: [{signature}]")
            else:
                print(f"  DEBUG: No secret found or not using signature for bucket {bucket_name} (webhook {i+1}). Config: {bucket_config}")
            
            try:
                print(f"  DEBUG: Sending webhook {i+1} to {webhook_url} with headers: {headers}")
                response = requests.post(
                    webhook_url,
                    data=payload_json,
                    headers=headers,
                    timeout=10
                )
                
                if response.status_code == 200:
                    print(f"  ✅ Webhook {i+1}: {event_type} for {bucket_name} - {response.status_code}")
                else:
                    print(f"  ❌ Webhook {i+1}: {event_type} for {bucket_name} - {response.status_code} {response.text}")
                    
            except requests.exceptions.RequestException as e:
                print(f"  ❌ Webhook {i+1}: Connection error - {e}")
        
        print("✅ Webhook sending completed")

    def test_deletion_apis(self, base_url="http://localhost:5000"):
        """Test the deletion API endpoints"""
        print(f"\n🗑️ Testing deletion APIs at {base_url}...")
        
        headers = {
            'Content-Type': 'application/json',
            # Note: In a real test, you'd need proper CSRF token handling
        }
        
        try:
            # Test 1: Delete events by bucket
            print("\n1. Testing delete by bucket...")
            test_bucket = self.test_buckets[0]  # test-photos-backup
            
            response = requests.delete(
                f"{base_url}/api/webhook_events/delete/bucket/{test_bucket}",
                headers=headers,
                timeout=10
            )
            
            if response.status_code == 200:
                result = response.json()
                print(f"   ✅ Deleted {result.get('deleted_count', 0)} events for bucket {test_bucket}")
            else:
                print(f"   ❌ Error deleting bucket events: {response.status_code}")
            
            # Test 2: Delete old events
            print("\n2. Testing delete old events...")
            delete_old_data = {"days": 365}  # Delete events older than 1 year
            
            response = requests.delete(
                f"{base_url}/api/webhook_events/delete/old",
                headers=headers,
                json=delete_old_data,
                timeout=10
            )
            
            if response.status_code == 200:
                result = response.json()
                print(f"   ✅ Deleted {result.get('deleted_count', 0)} old events")
            else:
                print(f"   ❌ Error deleting old events: {response.status_code}")
            
            # Test 3: Delete specific events (get some event IDs first)
            print("\n3. Testing delete specific events...")
            
            # Get some events to delete
            events_response = requests.get(f"{base_url}/api/webhook_events/list?limit=3")
            if events_response.status_code == 200:
                events_data = events_response.json()
                if events_data.get('events'):
                    event_ids = [event['id'] for event in events_data['events'][:2]]
                    
                    delete_specific_data = {"event_ids": event_ids}
                    response = requests.delete(
                        f"{base_url}/api/webhook_events/delete",
                        headers=headers,
                        json=delete_specific_data,
                        timeout=10
                    )
                    
                    if response.status_code == 200:
                        result = response.json()
                        print(f"   ✅ Deleted {result.get('deleted_count', 0)} specific events")
                    else:
                        print(f"   ❌ Error deleting specific events: {response.status_code}")
                else:
                    print("   ⚠️ No events found to delete")
            
            print("\n✅ Deletion API testing completed")
            print("💡 Note: Actual deletion requires proper authentication and CSRF tokens")
            
        except requests.exceptions.RequestException as e:
            print(f"❌ Connection error during deletion testing: {e}")

    def add_test_b2_buckets(self):
        """Add test B2 bucket entries to the b2_buckets table."""
        print("\n🪣 Adding test B2 bucket entries...")
        
        test_buckets_data = []
        for i, bucket_name in enumerate(self.test_buckets):
            bucket_data = {
                'bucketId': f"bucket_{fake.random_int(100000, 999999)}",
                'bucketName': bucket_name,
                'accountId': f"account_{fake.random_int(100000, 999999)}",
                'bucketType': random.choice(['allPrivate', 'allPublic']),
                'corsRules': [],
                'eventNotificationRules': [],
                'lifecycleRules': [],
                'bucketInfo': {},
                'options': [],
                'fileLockConfiguration': {},
                'defaultServerSideEncryption': {},
                'replicationConfiguration': {},
                'revision': 1
            }
            test_buckets_data.append(bucket_data)
        
        self.db.save_b2_bucket_details(test_buckets_data)
        print(f"✅ Added {len(test_buckets_data)} test B2 bucket entries")

    def clear_test_data(self):
        """Clear all test data from the database."""
        print("\n🧹 Clearing existing test data...")
        
        try:
            with self.db._get_connection() as conn:
                cursor = conn.cursor()
                
                # Clear webhook events
                cursor.execute("DELETE FROM webhook_events")
                events_deleted = cursor.rowcount
                
                # Clear bucket configurations  
                cursor.execute("DELETE FROM bucket_configurations")
                configs_deleted = cursor.rowcount
                
                # Clear webhook statistics
                cursor.execute("DELETE FROM webhook_statistics")
                stats_deleted = cursor.rowcount
                
                # Clear test B2 buckets
                cursor.execute("DELETE FROM b2_buckets WHERE bucket_name LIKE 'test-%' OR bucket_name LIKE 'development-%' OR bucket_name LIKE 'production-%' OR bucket_name LIKE 'user-%' OR bucket_name LIKE 'analytics-%'")
                buckets_deleted = cursor.rowcount
                
                conn.commit()
                
                print(f"  ✅ Deleted {events_deleted} webhook events")
                print(f"  ✅ Deleted {configs_deleted} bucket configurations")
                print(f"  ✅ Deleted {stats_deleted} webhook statistics")
                print(f"  ✅ Deleted {buckets_deleted} test B2 buckets")
                
        except Exception as e:
            print(f"  ❌ Error clearing test data: {e}")

    def print_summary(self):
        """Print a summary of the current test data."""
        print("\n📊 Test Data Summary:")
        print("=" * 50)
        
        try:
            with self.db._get_connection() as conn:
                cursor = conn.cursor()
                
                # Count webhook events
                cursor.execute("SELECT COUNT(*) FROM webhook_events")
                events_count = cursor.fetchone()[0]
                
                # Count by event type
                cursor.execute("SELECT event_type, COUNT(*) FROM webhook_events GROUP BY event_type")
                event_types = cursor.fetchall()
                
                # Count bucket configurations
                cursor.execute("SELECT COUNT(*) FROM bucket_configurations")
                configs_count = cursor.fetchone()[0]
                
                # Count enabled webhook configurations
                cursor.execute("SELECT COUNT(*) FROM bucket_configurations WHERE webhook_enabled = 1")
                enabled_configs = cursor.fetchone()[0]
                
                print(f"📈 Total Events: {events_count}")
                print(f"📦 Bucket Configurations: {configs_count} ({enabled_configs} enabled)")
                
                if event_types:
                    print("\n📊 Events by Type:")
                    for event_type, count in event_types:
                        print(f"  {event_type}: {count}")
                
                # Show recent events
                cursor.execute("SELECT bucket_name, event_type, object_key, timestamp FROM webhook_events ORDER BY timestamp DESC LIMIT 5")
                recent_events = cursor.fetchall()
                
                if recent_events:
                    print("\n🕒 Recent Events:")
                    for bucket, event_type, object_key, timestamp in recent_events:
                        print(f"  {timestamp} | {bucket} | {event_type} | {object_key}")
                
        except Exception as e:
            print(f"❌ Error generating summary: {e}")

def main():
    parser = argparse.ArgumentParser(description="Generate synthetic webhook test data")
    parser.add_argument('--clear-data', action='store_true', help='Clear existing test data first')
    parser.add_argument('--send-webhooks', action='store_true', help='Send actual HTTP webhook requests')
    parser.add_argument('--test-deletion', action='store_true', help='Test deletion API endpoints')
    parser.add_argument('--events', type=int, default=50, help='Number of events to generate (default: 50)')
    parser.add_argument('--buckets', type=int, default=5, help='Number of test buckets (default: 5)')
    parser.add_argument('--webhook-url', default='http://localhost:5000', help='Base URL for webhook testing')
    parser.add_argument('--summary-only', action='store_true', help='Only show current data summary')
    
    args = parser.parse_args()
    
    print("🧪 Webhook Events Test Data Generator")
    print("=" * 50)
    
    # Initialize the test generator
    try:
        generator = WebhookTestGenerator()
    except Exception as e:
        print(f"❌ Failed to initialize test generator: {e}")
        return 1
    
    # Show summary only if requested
    if args.summary_only:
        generator.print_summary()
        return 0
    
    # Test deletion APIs if requested
    if args.test_deletion:
        generator.test_deletion_apis(args.webhook_url)
        return 0
    
    # Clear existing data if requested
    if args.clear_data:
        generator.clear_test_data()
    
    # Generate test data
    try:
        # Set up bucket configurations
        generator.setup_test_bucket_configurations()
        
        # Add test B2 bucket entries
        generator.add_test_b2_buckets()
        
        # Generate webhook events
        events = generator.generate_test_events(args.events)
        
        # Send webhook requests if requested
        if args.send_webhooks:
            generator.send_test_webhooks(args.webhook_url, min(10, args.events // 5))
        
        # Show summary
        generator.print_summary()
        
        print("\n✅ Test data generation completed successfully!")
        print("\n💡 Next Steps:")
        print("   1. Start your Flask app: python run.py")
        print("   2. Navigate to: http://localhost:5000/webhook_events")
        print("   3. Test the real-time monitoring interface")
        print("   4. Try the filters and bucket-specific views")
        print("   5. Test bulk operations and deletion features")
        
        if args.send_webhooks:
            print("   6. Check that the webhook requests were received and processed")
        
        return 0
        
    except Exception as e:
        print(f"❌ Error during test data generation: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == '__main__':
    exit(main()) 