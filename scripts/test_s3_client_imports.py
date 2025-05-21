#!/usr/bin/env python3
"""
Test script that serves as a standalone S3 client health checker
"""

import os
import sys
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Add parent directory to path to allow importing app modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

def test_s3_client_imports():
    """Test S3 client imports from various implementations"""
    results = []
    
    # Test boto3
    try:
        import boto3
        results.append(f"boto3 available: {boto3.__version__}")
    except ImportError:
        results.append("boto3 not available - S3 functionality will be limited")
        return results
    
    # Test new S3 client
    try:
        from app.backblaze_s3_api_new import S3BackblazeClient
        results.append("S3BackblazeClient available from backblaze_s3_api_new")
    except ImportError:
        # Test fixed S3 client
        try:
            from app.backblaze_s3_api_fixed import S3BackblazeClient
            results.append("S3BackblazeClient available from backblaze_s3_api_fixed")
        except ImportError:
            # Test original S3 client
            try:
                from app.backblaze_s3_api import S3BackblazeClient
                results.append("S3BackblazeClient available from backblaze_s3_api")
            except ImportError as e:
                results.append(f"S3 client not available from any source: {str(e)}")
            except Exception as e:
                results.append(f"Error importing S3 client: {str(e)}")
    
    return results

def main():
    """Main entry point"""
    results = test_s3_client_imports()
    for result in results:
        print(result)
    
    return 0 if any("S3BackblazeClient available" in r for r in results) else 1

if __name__ == "__main__":
    sys.exit(main())
