#!/usr/bin/env python3
"""
Debug script for testing webhook receiver endpoint
"""
import requests
import json
import hmac
import hashlib

def test_webhook_request():
    # Test payload
    payload = {
        "eventType": "b2:ObjectCreated:MultipartUpload",
        "eventTimestamp": "2025-01-15T10:30:00.000Z",
        "bucketName": "development-assets",
        "bucketId": "bucket_123456",
        "objectName": "test-file.jpg",
        "objectSize": 1024,
        "objectVersionId": "4_z12345_67890",
        "contentType": "image/jpeg",
        "contentSha1": "da39a3ee5e6b4b0d3255bfef95601890afd80709",
        "requestId": "test-request-123",
        "sourceIpAddress": "192.168.1.1",
        "userAgent": "Test-Client/1.0"
    }
    
    payload_json = json.dumps(payload)
    webhook_secret = "3cdf749e1252c47e3f776f10f2b2c45f"  # From database query
    
    # Create signature
    signature = hmac.new(
        webhook_secret.encode('utf-8'),
        payload_json.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    signature_header = f"sha256={signature}"
    
    headers = {
        'Content-Type': 'application/json',
        'X-Hub-Signature-256': signature_header,
        'User-Agent': 'Test-Webhook-Client/1.0'
    }
    
    webhook_url = "http://localhost:5000/api/webhooks/backblaze"
    
    print(f"Testing webhook URL: {webhook_url}")
    print(f"Payload: {payload_json}")
    print(f"Signature: {signature_header}")
    
    try:
        response = requests.post(
            webhook_url,
            data=payload_json,
            headers=headers,
            timeout=10
        )
        
        print(f"Response Status: {response.status_code}")
        print(f"Response Headers: {dict(response.headers)}")
        print(f"Response Body: {response.text}")
        
        if response.status_code == 200:
            print("✅ Webhook request successful!")
        else:
            print(f"❌ Webhook request failed with status {response.status_code}")
            
    except requests.exceptions.RequestException as e:
        print(f"❌ Connection error: {e}")

if __name__ == '__main__':
    test_webhook_request() 