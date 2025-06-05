#!/usr/bin/env python3
"""
Debug script to troubleshoot webhook signature validation issues.
This will help identify why Backblaze webhook signatures are failing.
"""

import hmac
import hashlib
import json
import base64
from app.models.database import Database
from app.webhooks import WebhookProcessor

def test_signature_methods():
    """Test different signature calculation methods"""
    
    # Sample data (you'll replace this with real webhook data)
    sample_payload = json.dumps({
        "events": [{
            "eventType": "b2:ObjectCreated:Upload",
            "bucketName": "test-bucket",
            "objectName": "test-file.txt",
            "objectSize": 1024,
            "eventTimestamp": 1696877654000,
            "eventId": "test-event-123"
        }]
    })
    
    sample_secret = "your-webhook-secret-here"
    
    print("=== WEBHOOK SIGNATURE DEBUG ===")
    print(f"Sample payload: {sample_payload}")
    print(f"Sample secret: {sample_secret}")
    print()
    
    # Method 1: Current implementation (what your app does)
    print("1. Current app method:")
    signature1 = hmac.new(
        sample_secret.encode('utf-8'),
        sample_payload.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    print(f"   Signature: sha256={signature1}")
    print()
    
    # Method 2: Base64 encoding (alternative B2 might use)
    print("2. Base64 encoded method:")
    signature2 = base64.b64encode(
        hmac.new(
            sample_secret.encode('utf-8'),
            sample_payload.encode('utf-8'),
            hashlib.sha256
        ).digest()
    ).decode('utf-8')
    print(f"   Signature: sha256={signature2}")
    print()
    
    # Method 3: Secret as base64 (if secret is base64 encoded)
    print("3. Secret as base64 method:")
    try:
        secret_bytes = base64.b64decode(sample_secret)
        signature3 = hmac.new(
            secret_bytes,
            sample_payload.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        print(f"   Signature: sha256={signature3}")
    except:
        print("   Secret is not valid base64")
    print()
    
    # Method 4: Payload as bytes without encoding
    print("4. Raw bytes method:")
    signature4 = hmac.new(
        sample_secret.encode('utf-8'),
        sample_payload.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    print(f"   Signature: sha256={signature4}")
    print()

def test_with_real_data():
    """Test with real webhook data from your database"""
    
    print("=== TESTING WITH REAL DATABASE DATA ===")
    
    # Connect to database
    try:
        db = Database('./backblaze_snapshots.db')
        
        # Get a bucket configuration with webhook secret
        configs = db.get_all_bucket_configurations()
        webhook_config = None
        
        for config in configs:
            if config.get('webhook_secret') and config.get('webhook_enabled'):
                webhook_config = config
                break
        
        if not webhook_config:
            print("No bucket configurations found with webhook_secret and webhook_enabled=True")
            return
            
        bucket_name = webhook_config['bucket_name']
        secret = webhook_config['webhook_secret']
        
        print(f"Found config for bucket: {bucket_name}")
        print(f"Secret: {secret}")
        print(f"Secret length: {len(secret)} characters")
        print(f"Secret type: {type(secret)}")
        print()
        
        # Test the current verification method
        processor = WebhookProcessor(db)
        
        # Create a test payload
        test_payload = json.dumps({
            "events": [{
                "eventType": "b2:ObjectCreated:Upload",
                "bucketName": bucket_name,
                "objectName": "debug-test.txt",
                "objectSize": 12345,
                "eventTimestamp": 1696877654000,
                "eventId": "debug-test-123"
            }]
        })
        
        # Calculate what our app would generate
        our_signature = hmac.new(
            secret.encode('utf-8'),
            test_payload.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        print(f"Test payload: {test_payload}")
        print(f"Our calculated signature: sha256={our_signature}")
        
        # Test verification with our own signature
        is_valid = processor.verify_webhook_signature(test_payload, f"sha256={our_signature}", secret)
        print(f"Self-verification result: {is_valid}")
        
        if not is_valid:
            print("ERROR: Our own signature doesn't verify! There's a bug in the verification method.")
        
    except Exception as e:
        print(f"Error testing with real data: {e}")

def analyze_signature_format():
    """Analyze different signature header formats"""
    
    print("=== SIGNATURE FORMAT ANALYSIS ===")
    
    test_secret = "test-secret-123"
    test_payload = '{"test": "data"}'
    
    # Generate signature
    raw_signature = hmac.new(
        test_secret.encode('utf-8'),
        test_payload.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    
    print(f"Raw signature: {raw_signature}")
    print()
    
    # Test different header formats
    formats = [
        f"sha256={raw_signature}",
        f"SHA256={raw_signature}",
        raw_signature,
        f"sha256:{raw_signature}",
        f"HMAC-SHA256={raw_signature}"
    ]
    
    for fmt in formats:
        print(f"Testing format: '{fmt}'")
        
        # Simulate what your verification code does
        signature = fmt
        if signature.startswith('sha256='):
            signature = signature[7:]
        elif signature.startswith('SHA256='):
            signature = signature[7:]
        elif signature.startswith('sha256:'):
            signature = signature[7:]
        elif signature.startswith('HMAC-SHA256='):
            signature = signature[12:]
            
        matches = hmac.compare_digest(raw_signature, signature)
        print(f"   Extracted: '{signature}'")
        print(f"   Matches: {matches}")
        print()

if __name__ == "__main__":
    print("Backblaze Webhook Signature Debug Tool")
    print("=" * 50)
    print()
    
    test_signature_methods()
    test_with_real_data()
    analyze_signature_format()
    
    print("\n=== RECOMMENDATIONS ===")
    print("1. Check the actual signature header from B2 in your logs")
    print("2. Verify the webhook secret matches exactly on both ends")
    print("3. Ensure the payload is not modified before signature calculation")
    print("4. Check for encoding issues (UTF-8)")
    print("5. Verify B2 is using HMAC-SHA256 with hexdigest format") 