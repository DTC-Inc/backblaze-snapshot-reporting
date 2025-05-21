#!/usr/bin/env python3
"""
Test script to verify boto3 installation and Backblaze S3 API connectivity.
"""

import sys
import os
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

def check_boto3():
    """Verify boto3 installation"""
    try:
        import boto3
        import botocore
        logger.info(f"boto3 version: {boto3.__version__}")
        logger.info(f"botocore version: {botocore.__version__}")
        return True
    except ImportError as e:
        logger.error(f"Failed to import boto3: {e}")
        logger.error("Please install boto3: pip install boto3")
        return False
        
def test_s3_connection():
    """Test connecting to Backblaze B2 via S3 API"""
    try:
        # Import required modules
        import boto3
        from botocore.exceptions import ClientError, NoCredentialsError
        
        # Get credentials (preferably from environment variables)
        key_id = os.environ.get('B2_APPLICATION_KEY_ID')
        app_key = os.environ.get('B2_APPLICATION_KEY')
        
        if not key_id or not app_key:
            logger.error("Missing B2_APPLICATION_KEY_ID or B2_APPLICATION_KEY environment variables")
            return False
            
        logger.info(f"Using key ID with length: {len(key_id)}")
        
        # Add suffix if key is in older format
        s3_key_id = key_id
        if len(key_id) == 12:  # Old style B2 key
            s3_key_id = key_id + "0010"
            logger.info(f"Converted key ID from length {len(key_id)} to {len(s3_key_id)}")
            
        # Try multiple endpoints
        endpoints = [
            f'https://s3.{key_id[:6]}.backblazeb2.com',  # Region-specific endpoint
            'https://s3.us-west-000.backblazeb2.com',  # Default endpoint
            'https://s3.us-west-002.backblazeb2.com',  # US West 002
            'https://s3.us-west-001.backblazeb2.com',  # US West 001
            'https://s3.us-east-005.backblazeb2.com',  # US East
            'https://s3.eu-central-003.backblazeb2.com'  # EU
        ]
        
        for endpoint in endpoints:
            logger.info(f"Trying endpoint: {endpoint}")
            try:
                # Create S3 client
                s3_client = boto3.client(
                    service_name='s3',
                    endpoint_url=endpoint,
                    aws_access_key_id=s3_key_id,
                    aws_secret_access_key=app_key,
                    config=boto3.session.Config(
                        signature_version='s3v4',
                        connect_timeout=10,
                        retries={'max_attempts': 2}
                    )
                )
                
                # Test connection
                response = s3_client.list_buckets()
                buckets = response.get('Buckets', [])
                
                logger.info(f"Successfully connected to {endpoint}")
                logger.info(f"Found {len(buckets)} buckets:")
                for bucket in buckets:
                    logger.info(f"  - {bucket.get('Name')}")
                    
                return True
                
            except ClientError as e:
                error_code = e.response.get('Error', {}).get('Code', 'Unknown')
                logger.error(f"Failed with error code {error_code}: {str(e)}")
            except NoCredentialsError:
                logger.error("No credentials provided")
            except Exception as e:
                logger.error(f"Unexpected error: {type(e).__name__}: {str(e)}")
                
        logger.error("Failed to connect to any endpoint")
        return False
    
    except Exception as e:
        logger.error(f"Error in test: {type(e).__name__}: {str(e)}")
        return False

if __name__ == "__main__":
    logger.info("Testing boto3 installation...")
    if check_boto3():
        logger.info("boto3 is installed correctly")
        logger.info("Testing S3 connection to Backblaze B2...")
        if test_s3_connection():
            logger.info("S3 connection successful!")
            sys.exit(0)
        else:
            logger.error("S3 connection failed")
            sys.exit(1)
    else:
        logger.error("boto3 installation issues detected")
        sys.exit(1)
