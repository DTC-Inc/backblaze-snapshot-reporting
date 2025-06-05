#!/usr/bin/env python3
"""
Simple test to check if webhook endpoint exists
"""
import requests

def test_webhook_endpoint_exists():
    """Test if the webhook endpoint responds at all"""
    
    webhook_url = "https://bbssr.bierlysmith.com/api/webhooks/backblaze"
    
    print(f"Testing webhook endpoint: {webhook_url}")
    
    # Test with a simple GET request first (should return 405 Method Not Allowed if endpoint exists)
    try:
        response = requests.get(webhook_url, timeout=10)
        print(f"GET Response: {response.status_code} - {response.text}")
        
        if response.status_code == 405:
            print("✅ Endpoint exists (GET not allowed, which is expected)")
        elif response.status_code == 404:
            print("❌ Endpoint does not exist (404)")
        else:
            print(f"? Unexpected response: {response.status_code}")
            
    except requests.exceptions.RequestException as e:
        print(f"❌ Connection error: {e}")
    
    # Test with empty POST (should give a different error than 404)
    try:
        response = requests.post(webhook_url, timeout=10)
        print(f"POST (empty) Response: {response.status_code} - {response.text}")
        
        if response.status_code == 404:
            print("❌ Endpoint does not exist (404)")
        else:
            print("✅ Endpoint exists (non-404 response)")
            
    except requests.exceptions.RequestException as e:
        print(f"❌ Connection error: {e}")

if __name__ == '__main__':
    test_webhook_endpoint_exists() 