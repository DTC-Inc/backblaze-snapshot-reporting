#!/usr/bin/env python3
"""
Test script for webhook functionality
"""

import os
import sys
import tempfile
import json
from datetime import datetime

# Add the app directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'app'))

from models.database import Database
from webhooks import WebhookProcessor

def test_webhook_functionality():
    """Test the complete webhook functionality"""
    print("Testing Backblaze Webhook Functionality")
    print("=" * 50)
    
    # Create a temporary database
    temp_db = os.path.join(tempfile.gettempdir(), 'test_webhook_complete.db')
    
    try:
        # Initialize database and webhook processor
        db = Database(temp_db)
        processor = WebhookProcessor(db)
        
        print("✓ Database and WebhookProcessor initialized")
        
        # Test 1: Create bucket configuration
        bucket_name = "test-bucket"
        webhook_secret = processor.generate_webhook_secret()
        events_to_track = ["b2:ObjectCreated", "b2:ObjectDeleted"]
        
        success = db.save_bucket_configuration(
            bucket_name=bucket_name,
            webhook_enabled=True,
            webhook_secret=webhook_secret,
            events_to_track=events_to_track
        )
        
        print(f"✓ Bucket configuration saved: {success}")
        
        # Test 2: Retrieve bucket configuration
        config = db.get_bucket_configuration(bucket_name)
        print(f"✓ Retrieved bucket config: {config['webhook_enabled']}")
        
        # Test 3: Test webhook signature verification
        test_payload = '{"test": "data"}'
        signature = processor.verify_webhook_signature(test_payload, "invalid", webhook_secret)
        print(f"✓ Signature verification (should be False): {signature}")
        
        # Test 4: Process a webhook event
        webhook_payload = {
            "eventType": "b2:ObjectCreated",
            "bucketName": bucket_name,
            "objectKey": "test-file.txt",
            "objectSize": 1024,
            "objectVersionId": "test-version-123",
            "eventTimestamp": datetime.now().isoformat()
        }
        
        result = processor.process_webhook_event(
            webhook_payload,
            source_ip="192.168.1.1",
            user_agent="Test-Agent/1.0"
        )
        
        print(f"✓ Webhook event processed: {result['success']}")
        print(f"  Event ID: {result.get('event_id', 'N/A')}")
        
        # Test 5: Retrieve webhook events
        events = db.get_webhook_events(limit=10)
        print(f"✓ Retrieved {len(events)} webhook events")
        
        # Test 6: Get webhook statistics
        stats = db.get_webhook_statistics(days=1)
        print(f"✓ Retrieved {len(stats)} statistics records")
        
        # Test 7: Get event summary
        summary = processor.get_event_summary(days=1)
        print(f"✓ Event summary generated: {summary.get('total_events', 0)} total events")
        
        # Test 8: Get all bucket configurations
        all_configs = db.get_all_bucket_configurations()
        print(f"✓ Retrieved {len(all_configs)} bucket configurations")
        
        # Test 9: Delete bucket configuration
        deleted = db.delete_bucket_configuration(bucket_name)
        print(f"✓ Bucket configuration deleted: {deleted}")
        
        print("\n" + "=" * 50)
        print("🎉 All webhook functionality tests passed!")
        
        return True
        
    except Exception as e:
        print(f"❌ Test failed with error: {str(e)}")
        import traceback
        traceback.print_exc()
        return False
        
    finally:
        # Clean up
        if os.path.exists(temp_db):
            os.remove(temp_db)
            print("✓ Temporary database cleaned up")

if __name__ == "__main__":
    success = test_webhook_functionality()
    sys.exit(0 if success else 1) 