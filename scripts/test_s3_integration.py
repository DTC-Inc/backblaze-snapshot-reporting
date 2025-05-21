#!/usr/bin/env python3
"""
Test script to check if the S3 API integration for Backblaze B2 is working properly
This can help diagnose configuration issues before deploying the application
"""

import os
import sys
import boto3
import logging
import argparse

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def check_boto3_installation():
    """Verify boto3 is properly installed"""
    try:
        logger.info(f"boto3 version: {boto3.__version__}")
        return True
    except Exception as e:
        logger.error(f"boto3 not properly installed: {str(e)}")
        return False

def check_environment_variables():
    """Check if required environment variables are set"""
    key_id = os.environ.get('B2_APPLICATION_KEY_ID')
    app_key = os.environ.get('B2_APPLICATION_KEY')
    
    if not key_id or not app_key:
        logger.error("Missing required environment variables B2_APPLICATION_KEY_ID or B2_APPLICATION_KEY")
        return False
        
    logger.info("Environment variables for Backblaze B2 credentials are set")
    return True

def test_s3_connection(endpoint_url=None):
    """Test connection to Backblaze B2 S3 API"""
    key_id = os.environ.get('B2_APPLICATION_KEY_ID')
    app_key = os.environ.get('B2_APPLICATION_KEY')
    
    if not endpoint_url:
        endpoint_url = 'https://s3.us-west-002.backblazeb2.com'
        
    logger.info(f"Testing connection to {endpoint_url} with provided credentials")
    
    try:
        # Initialize S3 client
        s3_client = boto3.client(
            service_name='s3',
            endpoint_url=endpoint_url,
            aws_access_key_id=key_id,
            aws_secret_access_key=app_key
        )
        
        # List buckets to verify connectivity
        response = s3_client.list_buckets()
        
        # Check if we can access buckets
        if 'Buckets' in response:
            logger.info(f"Successfully connected to Backblaze B2 S3 API")
            logger.info(f"Found {len(response['Buckets'])} bucket(s)")
            
            for bucket in response['Buckets']:
                logger.info(f"Bucket: {bucket['Name']}")
                
            return True
        else:
            logger.error("Failed to retrieve bucket list")
            return False
            
    except Exception as e:
        logger.error(f"Failed to connect to S3 API: {str(e)}")
        return False

def main():
    parser = argparse.ArgumentParser(description="Test Backblaze B2 S3 API integration")
    parser.add_argument('--endpoint', help='S3 endpoint URL (defaults to https://s3.us-west-002.backblazeb2.com)')
    args = parser.parse_args()
    
    # Run tests
    logger.info("=== Backblaze B2 S3 API Integration Test ===")
    
    # Check boto3 installation
    if not check_boto3_installation():
        logger.error("boto3 not properly installed. Install it with: pip install boto3")
        sys.exit(1)
    
    # Check environment variables
    if not check_environment_variables():
        logger.error("Please set B2_APPLICATION_KEY_ID and B2_APPLICATION_KEY environment variables")
        sys.exit(1)
        
    # Test S3 connection
    if not test_s3_connection(args.endpoint):
        logger.error("S3 API connection test failed")
        sys.exit(1)
    
    logger.info("All tests passed! S3 API integration is working correctly")
    
if __name__ == "__main__":
    main()
