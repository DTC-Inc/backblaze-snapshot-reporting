import os
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Path to store credentials
CREDENTIALS_FILE = Path(os.getenv('CREDENTIALS_FILE', '/data/credentials.json'))
S3_CREDENTIALS_FILE = Path(os.getenv('S3_CREDENTIALS_FILE', '/data/s3_credentials.json')) # New file for S3

def get_credentials():
    """
    Get the stored API credentials if available.
    Returns a dictionary with key_id and application_key.
    """
    if not CREDENTIALS_FILE.exists():
        logger.debug("Credentials file not found")
        return None
    
    try:
        with open(CREDENTIALS_FILE, 'r') as f:
            credentials = json.load(f)
        return credentials
    except Exception as e:
        logger.error(f"Error reading credentials: {e}")
        return None

def save_credentials(key_id, application_key):
    """
    Save API credentials to a file.
    """
    # Create directory if it doesn't exist
    CREDENTIALS_FILE.parent.mkdir(parents=True, exist_ok=True)
    
    try:
        credentials = {
            'key_id': key_id,
            'application_key': application_key
        }
        
        with open(CREDENTIALS_FILE, 'w') as f:
            json.dump(credentials, f)
        logger.info("API credentials saved successfully")
        return True
    except Exception as e:
        logger.error(f"Error saving credentials: {e}")
        return False

def delete_credentials():
    """
    Delete stored API credentials.
    """
    if CREDENTIALS_FILE.exists():
        try:
            CREDENTIALS_FILE.unlink()
            logger.info("API credentials deleted")
            return True
        except Exception as e:
            logger.error(f"Error deleting credentials: {e}")
    return False

def get_s3_credentials():
    """
    Get the stored S3 API credentials if available.
    Returns a dictionary with aws_access_key_id, aws_secret_access_key, endpoint_url, region_name.
    """
    if not S3_CREDENTIALS_FILE.exists():
        logger.debug("S3 credentials file not found")
        return None
    
    try:
        with open(S3_CREDENTIALS_FILE, 'r') as f:
            credentials = json.load(f)
        # Basic validation
        if not all(k in credentials for k in ['aws_access_key_id', 'aws_secret_access_key', 'endpoint_url']):
            logger.warning(f"S3 credentials file {S3_CREDENTIALS_FILE} is missing one or more required keys.")
            return None
        return credentials
    except Exception as e:
        logger.error(f"Error reading S3 credentials: {e}")
        return None

def save_s3_credentials(aws_access_key_id, aws_secret_access_key, endpoint_url, region_name=None):
    """
    Save S3 API credentials to a file.
    """
    S3_CREDENTIALS_FILE.parent.mkdir(parents=True, exist_ok=True)
    
    try:
        credentials = {
            'aws_access_key_id': aws_access_key_id,
            'aws_secret_access_key': aws_secret_access_key,
            'endpoint_url': endpoint_url
        }
        if region_name: # Optional
            credentials['region_name'] = region_name
        
        with open(S3_CREDENTIALS_FILE, 'w') as f:
            json.dump(credentials, f)
        logger.info("S3 API credentials saved successfully")
        return True
    except Exception as e:
        logger.error(f"Error saving S3 credentials: {e}")
        return False

def delete_s3_credentials():
    """
    Delete stored S3 API credentials.
    """
    if S3_CREDENTIALS_FILE.exists():
        try:
            S3_CREDENTIALS_FILE.unlink()
            logger.info("S3 API credentials deleted")
            return True
        except Exception as e:
            logger.error(f"Error deleting S3 credentials: {e}")
    return False
