#!/usr/bin/env python3
"""
Test script to verify Backblaze v1= signature format handling
"""

import hmac
import hashlib
import json
from app.webhooks import WebhookProcessor
from app.models.database import Database

def test_v1_signature_format():
    """Test the updated signature verification with v1= format"""
    print("=== Testing Backblaze v1= Signature Format ===")
    
    # Sample webhook payload like B2 sends
    test_payload = json.dumps({
        "events": [{
            "eventType": "b2:ObjectCreated:Upload",
            "bucketName": "test-bucket",
            "objectName": "test-file.txt", 
            "objectSize": 1024,
            "eventTimestamp": 1696877654000,
            "eventId": "test-event-123"
        }]
    })
    
    test_secret = "TestSecret123"
    
    # Calculate what B2 would send (v1= prefix format)
    raw_signature = hmac.new(
        test_secret.encode('utf-8'),
        test_payload.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    
    # Test different signature formats
    test_cases = [
        f"v1={raw_signature}",         # Official B2 format
        f"sha256={raw_signature}",     # Legacy/alternative format
        raw_signature                  # Raw hex (no prefix)
    ]
    
    # Initialize processor
    db = Database('./backblaze_snapshots.db')
    processor = WebhookProcessor(db)
    
    print(f"Test payload: {test_payload}")
    print(f"Test secret: {test_secret}")
    print(f"Expected signature (hex): {raw_signature}")
    print()
    
    for i, signature_header in enumerate(test_cases, 1):
        print(f"Test {i}: Signature header '{signature_header}'")
        is_valid = processor.verify_webhook_signature(test_payload, signature_header, test_secret)
        print(f"  Result: {'✓ VALID' if is_valid else '✗ INVALID'}")
        print()
    
    return True

if __name__ == "__main__":
    test_v1_signature_format() 