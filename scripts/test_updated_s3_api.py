#!/usr/bin/env python3
"""
Test script for the updated Backblaze S3 API integration
This script tests the S3 API integration according to the latest Backblaze documentation
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
    """Test the updated S3BackblazeClient implementation"""
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
            logger.info("✅ S3 client successfully initialized")
            
            # Test listing buckets using S3 API
            try:
                response = client.s3_client.list_buckets()
                buckets = response.get('Buckets', [])
                logger.info(f"✅ Found {len(buckets)} buckets using direct S3 API call")
                
                for i, bucket in enumerate(buckets):
                    bucket_name = bucket.get('Name')
                    logger.info(f"  Bucket {i+1}: {bucket_name}")
                    
                    # Test direct S3 API calls on this bucket
                    try:
                        # Test bucket exists
                        client.s3_client.head_bucket(Bucket=bucket_name)
                        logger.info(f"  ✅ Verified bucket '{bucket_name}' exists with head_bucket")
                        
                        # Get bucket location
                        try:
                            location = client.s3_client.get_bucket_location(Bucket=bucket_name)
                            region = location.get('LocationConstraint') or 'default'
                            logger.info(f"  ✅ Bucket '{bucket_name}' location: {region}")
                        except Exception as e:
                            logger.warning(f"  ⚠️ Could not get location for bucket '{bucket_name}': {str(e)}")
                        
                        # List some objects
                        objects = client.s3_client.list_objects_v2(
                            Bucket=bucket_name, 
                            MaxKeys=5
                        )
                        contents = objects.get('Contents', [])
                        logger.info(f"  ✅ Listed {len(contents)} objects in bucket '{bucket_name}'")
                        
                        # Use our bucket usage function
                        logger.info(f"Testing full bucket usage statistics for '{bucket_name}'")
                        bucket_stats = client.get_s3_bucket_usage(bucket_name)
                        
                        if bucket_stats:
                            storage_bytes = bucket_stats.get('total_size', 0)
                            files_count = bucket_stats.get('files_count', 0)
                            source = bucket_stats.get('source', 'unknown')
                            largest_files = bucket_stats.get('largest_files', [])
                            
                            logger.info(f"✅ S3 API bucket statistics:"
                                       f"\n    - Size: {storage_bytes/1024/1024:.2f} MB"
                                       f"\n    - Files: {files_count}"
                                       f"\n    - Data source: {source}")
                            
                            if largest_files:
                                logger.info(f"  Largest file: {largest_files[0]['fileName']} - {largest_files[0]['size']/1024/1024:.2f} MB")
                        else:
                            logger.error(f"❌ Failed to get bucket statistics for '{bucket_name}'")
                    
                    except Exception as bucket_error:
                        logger.error(f"❌ Error testing bucket '{bucket_name}': {str(bucket_error)}")
                    
                    # Only test the first bucket to keep output manageable
                    if i >= 0:
                        break
            except Exception as api_error:
                logger.error(f"❌ Error using S3 API: {str(api_error)}")
                return False
                
            # Test taking a snapshot
            logger.info("📸 Taking a full account snapshot...")
            snapshot = client.take_snapshot()
            
            if snapshot:
                logger.info("✅ Successfully created a snapshot using S3-enabled client")
                total_size = snapshot.get('total_storage_bytes', 0) 
                total_cost = snapshot.get('total_cost', 0)
                buckets = snapshot.get('buckets', [])
                
                logger.info(f"📊 Snapshot summary:"
                           f"\n  - Total storage: {total_size/1024/1024/1024:.2f} GB"
                           f"\n  - Estimated cost: ${total_cost:.2f}"
                           f"\n  - Buckets: {len(buckets)}")
                           
                for bucket_data in buckets:
                    method = bucket_data.get('reporting_method', 'unknown')
                    name = bucket_data.get('name', 'unknown')
                    size = bucket_data.get('storage_bytes', 0)
                    
                    logger.info(f"  → {name}: {size/1024/1024/1024:.2f} GB (method: {method})")
                
                return True
            else:
                logger.error("❌ Failed to take snapshot")
                return False
        else:
            logger.error("❌ S3 client was not initialized - check logs for details")
            return False
    except Exception as e:
        logger.error(f"❌ Error during test: {type(e).__name__}: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return False

if __name__ == "__main__":
    logger.info("=== Testing Updated Backblaze S3 API Integration ===")
    
    if test_s3_client():
        logger.info("✅ All tests passed successfully!")
        sys.exit(0)
    else:
        logger.error("❌ Test failed - see logs for details")
        sys.exit(1)
