#!/usr/bin/env python3
"""
Script to test the fixed Backblaze S3 API client
"""

import os
import sys
import logging
import time

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Add parent directory to path to allow importing from app
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

def main():
    logger.info("=== Testing Fixed S3BackblazeClient ===")
      # Import the fixed S3 client
    try:
        from app.backblaze_s3_api import S3BackblazeClient
        logger.info("Successfully imported S3BackblazeClient")
    except Exception as e:
        logger.error(f"Failed to import S3BackblazeClient: {str(e)}")
        sys.exit(1)
        
    # Check environment variables
    key_id = os.environ.get('B2_APPLICATION_KEY_ID')
    app_key = os.environ.get('B2_APPLICATION_KEY')
    
    if not key_id or not app_key:
        logger.error("Missing required environment variables B2_APPLICATION_KEY_ID or B2_APPLICATION_KEY")
        sys.exit(1)
        
    logger.info("Environment variables for Backblaze B2 credentials are set")
    
    # Initialize the client
    try:
        client = S3BackblazeClient()
        logger.info("Successfully initialized S3BackblazeClient")
    except Exception as e:
        logger.error(f"Failed to initialize S3BackblazeClient: {str(e)}")
        sys.exit(1)
        
    # Check if S3 client was correctly initialized
    if client.s3_client:
        logger.info("S3 client was successfully initialized")
    else:
        logger.error("Failed to initialize S3 client")
        sys.exit(1)
        
    # List buckets
    try:
        buckets_response = client.list_buckets()
        buckets = buckets_response.get('buckets', [])
        logger.info(f"Found {len(buckets)} bucket(s)")
        
        # Try to get stats for the first bucket
        if buckets:
            bucket = buckets[0]
            bucket_id = bucket.get('bucketId')
            bucket_name = bucket.get('bucketName')
            
            logger.info(f"Getting usage statistics for bucket {bucket_name}")
            
            # Test bucket stats from S3 API
            stats = client.get_s3_bucket_usage(bucket_name)
            
            if stats:
                total_size = stats.get('total_size', 0)
                files_count = stats.get('files_count', 0)
                logger.info(f"S3 API bucket stats: {total_size} bytes across {files_count} files")
                
                # Try taking a snapshot
                logger.info("Taking snapshot...")
                snapshot = client.take_snapshot()
                
                if snapshot:
                    logger.info("Snapshot successful!")
                    
                    # Log some details
                    total_cost = snapshot.get('total_cost', 0)
                    total_storage_bytes = snapshot.get('total_storage_bytes', 0)
                    logger.info(f"Total storage: {total_storage_bytes} bytes")
                    logger.info(f"Total cost: ${total_cost:.2f}")
                else:
                    logger.error("Failed to take snapshot")
            else:
                logger.error("Failed to get bucket statistics")
    except Exception as e:
        logger.error(f"Error testing S3BackblazeClient: {str(e)}")
        sys.exit(1)
        
    logger.info("Test completed successfully!")
    
if __name__ == "__main__":
    main()
