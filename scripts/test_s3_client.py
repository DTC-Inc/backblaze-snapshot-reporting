#!/usr/bin/env python3
"""
Test script for the Backblaze S3 API integration
"""

import os
import sys
import logging
import json
import time
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Add parent directory to path to allow importing app modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

def test_s3_client():
    """Test the S3BackblazeClient implementation"""
    try:
        # Import the client
        from app.backblaze_s3_api import S3BackblazeClient
        
        # Check for environment variables
        key_id = os.environ.get('B2_APPLICATION_KEY_ID')
        app_key = os.environ.get('B2_APPLICATION_KEY')
        
        if not key_id or not app_key:
            logger.error("Missing environment variables: B2_APPLICATION_KEY_ID and/or B2_APPLICATION_KEY")
            logger.info("Please set these variables before running this test")
            return False
            
        logger.info(f"Using key ID with length {len(key_id)}")
        
        # Create client
        client = S3BackblazeClient()
        
        # Check if S3 client was initialized
        if client.s3_client:
            logger.info("S3 client successfully initialized")
            
            # Test listing buckets
            buckets_response = client.list_buckets()
            buckets = buckets_response.get('buckets', [])
            logger.info(f"Found {len(buckets)} buckets")
            
            if buckets:
                # Get details of first bucket
                bucket = buckets[0]
                bucket_id = bucket.get('bucketId')
                bucket_name = bucket.get('bucketName')
                logger.info(f"Testing with bucket: {bucket_name}")
                
                # Test getting accurate bucket usage via S3
                bucket_stats = client.get_bucket_usage(bucket_id, bucket_name)
                
                if bucket_stats:
                    storage_bytes = bucket_stats.get('total_size', 0)
                    files_count = bucket_stats.get('files_count', 0)
                    source = bucket_stats.get('source', 'unknown')
                    
                    logger.info(f"Bucket statistics - Size: {storage_bytes} bytes, Files: {files_count}, Source: {source}")
                    
                    # If the source is 's3_api', the S3 API integration is working
                    if source == 's3_api':
                        logger.info("SUCCESS: S3 API integration is working correctly")
                    else:
                        logger.warning(f"S3 API not used - fell back to {source}")
                else:
                    logger.error("Failed to get bucket statistics")
                    return False
                    
                # Try taking a snapshot
                logger.info("Taking a full account snapshot...")
                snapshot = client.take_snapshot()
                
                if snapshot:
                    logger.info("Successfully created a snapshot using S3-enabled client")
                    total_size = snapshot.get('total_storage_bytes', 0)
                    total_cost = snapshot.get('total_cost', 0)
                    logger.info(f"Total storage: {total_size} bytes")
                    logger.info(f"Estimated cost: ${total_cost:.2f}")
                    return True
                else:
                    logger.error("Failed to take snapshot")
                    return False
            else:
                logger.warning("No buckets found in the account")
                return False
        else:
            logger.error("S3 client was not initialized - check logs for details")
            return False
    except Exception as e:
        logger.error(f"Error during test: {type(e).__name__}: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return False

if __name__ == "__main__":
    logger.info("=== Testing Backblaze S3 API Integration ===")
    
    if test_s3_client():
        logger.info("All tests passed successfully")
        sys.exit(0)
    else:
        logger.error("Test failed - see logs for details")
        sys.exit(1)
