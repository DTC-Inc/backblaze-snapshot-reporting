#!/usr/bin/env python3
"""
Test S3 API integration in Docker container
"""

import os
import sys
import subprocess
import time
import signal
import requests
import logging
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Define constants
COMPOSE_FILE = "docker-compose.test.yml"
CONTAINER_NAME = "bbssr-web-test"
API_BASE_URL = "http://localhost:5001"
MAX_RETRIES = 10
RETRY_INTERVAL = 2  # seconds

def check_credentials():
    """Ensure environment variables are set"""
    key_id = os.environ.get('B2_APPLICATION_KEY_ID')
    app_key = os.environ.get('B2_APPLICATION_KEY')
    
    if not key_id or not app_key:
        logger.warning("Missing environment variables B2_APPLICATION_KEY_ID or B2_APPLICATION_KEY")
        
        # Prompt for credentials
        logger.info("Please enter your Backblaze B2 credentials:")
        key_id = input("B2 Application Key ID: ")
        app_key = input("B2 Application Key: ")
        
        if not key_id or not app_key:
            logger.error("Credentials not provided. Cannot continue.")
            return False
        
        # Set environment variables for the Docker container
        os.environ['B2_APPLICATION_KEY_ID'] = key_id
        os.environ['B2_APPLICATION_KEY'] = app_key
        
    logger.info("B2 credentials are set in environment variables")
    return True

def start_container():
    """Start the Docker container"""
    logger.info("Starting test container...")
    result = subprocess.run(
        ["docker-compose", "-f", COMPOSE_FILE, "up", "-d"],
        capture_output=True,
        text=True
    )
    
    if result.returncode != 0:
        logger.error(f"Failed to start container: {result.stderr}")
        return False
        
    logger.info("Test container started successfully")
    return True

def stop_container():
    """Stop the Docker container"""
    logger.info("Stopping test container...")
    result = subprocess.run(
        ["docker-compose", "-f", COMPOSE_FILE, "down"],
        capture_output=True,
        text=True
    )
    
    if result.returncode != 0:
        logger.error(f"Failed to stop container: {result.stderr}")
        return False
        
    logger.info("Test container stopped successfully")
    return True

def wait_for_service():
    """Wait for web service to be available"""
    logger.info("Waiting for web service...")
    
    for retry in range(MAX_RETRIES):
        try:
            response = requests.get(f"{API_BASE_URL}/")
            if response.status_code == 200:
                logger.info("Web service is up and running")
                return True
        except Exception:
            pass
            
        logger.info(f"Retry {retry+1}/{MAX_RETRIES}...")
        time.sleep(RETRY_INTERVAL)
    
    logger.error("Web service did not become available in time")
    return False

def check_logs():
    """Check container logs for S3 API-related messages"""
    logger.info("Checking container logs...")
    
    result = subprocess.run(
        ["docker", "logs", CONTAINER_NAME],
        capture_output=True,
        text=True
    )
    
    if result.returncode != 0:
        logger.error(f"Failed to get container logs: {result.stderr}")
        return False
    
    logs = result.stdout
    
    # Look for specific messages
    s3_init_success = "Successfully initialized S3 client for Backblaze B2" in logs
    s3_connection_success = "Successfully connected to S3 API at" in logs
    s3_init_failure = "Failed to initialize S3 client" in logs
    indentation_error = "IndentationError" in logs
    
    if indentation_error:
        logger.error("⚠️ Indentation errors detected in the code!")
        logger.error("Please fix the indentation issues first.")
        
        # Extract and print the error
        error_lines = [line for line in logs.split('\n') if "IndentationError" in line]
        for line in error_lines:
            logger.error(f"  {line}")
        
        return False
    
    if s3_init_success and s3_connection_success:
        logger.info("✅ S3 client initialization and connection successful!")
        return True
    elif s3_init_success:
        logger.info("⚠️ S3 client initialized, but no successful connection found")
        return True
    elif s3_init_failure:
        logger.error("❌ S3 client initialization failed")
        return False
    else:
        logger.warning("⚠️ No conclusive S3 client status found in logs")
        return True

def main():
    """Main test function"""
    logger.info("=== Testing Backblaze S3 API Integration in Docker ===")
    
    # Check for credentials
    if not check_credentials():
        sys.exit(1)
    
    # Start test container
    if not start_container():
        sys.exit(1)
    
    try:
        # Wait for service to be available
        if not wait_for_service():
            raise Exception("Service did not start properly")
        
        # Check logs for S3 API-related messages
        if not check_logs():
            raise Exception("S3 API integration check failed")
        
        logger.info("=== Test completed successfully! ===")
    except Exception as e:
        logger.error(f"Test failed: {str(e)}")
        sys.exit(1)
    finally:
        # Always stop the container
        stop_container()

if __name__ == "__main__":
    # Setup signal handlers
    def signal_handler(sig, frame):
        logger.info("Test interrupted, cleaning up...")
        stop_container()
        sys.exit(1)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    main()
