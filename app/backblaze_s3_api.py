"""
This module enhances the existing Backblaze client by adding S3 API support 
for more accurate bucket size reporting.
"""

import boto3
import botocore
import logging
import os
import time
import json
from datetime import datetime
from botocore.exceptions import ClientError, NoCredentialsError, CredentialRetrievalError
from app.backblaze_api import BackblazeClient # Corrected import
from app.config import PARALLEL_BUCKET_OPERATIONS # Import parallel config
import concurrent.futures # Import concurrent.futures for ThreadPoolExecutor
from app.config import CACHE_ENABLED, CACHE_DIR, CACHE_TTL_SECONDS # Import cache config

logger = logging.getLogger(__name__)

class S3BackblazeClient(BackblazeClient):
    """Enhanced Backblaze client that uses the S3 API for more accurate bucket statistics"""
    
    def __init__(self, aws_access_key_id=None, aws_secret_access_key=None, endpoint_url=None, region_name=None, parallel_operations=None): # Added S3 credentials
        """Initialize the enhanced S3-capable Backblaze client"""
        super().__init__(parallel_operations=parallel_operations)
        self.s3_client = None
        self.s3_resource = None
        self.current_s3_key_id = None # This was for B2 key ID, now S3 key ID
        
        # Store provided S3 credentials
        self.aws_access_key_id = aws_access_key_id
        self.aws_secret_access_key = aws_secret_access_key
        self.endpoint_url = endpoint_url
        self.region_name = region_name # Optional, but good to have

        if not self._check_boto3_installed():
            logger.error("boto3 package not properly installed or configured - S3 functionality will be disabled")
        else:
            # Pass credentials to the initialization method
            self._initialize_s3_client(
                aws_access_key_id=self.aws_access_key_id,
                aws_secret_access_key=self.aws_secret_access_key,
                endpoint_url=self.endpoint_url,
                region_name=self.region_name
            )
    
    def _check_boto3_installed(self):
        """Check if boto3 is properly installed and usable"""
        try:
            import boto3
            logger.debug(f"boto3 package is installed (version: {boto3.__version__})")
            return True
        except ImportError:
            logger.error("boto3 package is not installed. Install it with: pip install boto3")
            return False
        except Exception as e:
            logger.error(f"Error importing boto3: {str(e)}")
            return False
    
    def _initialize_s3_client(self, aws_access_key_id=None, aws_secret_access_key=None, endpoint_url=None, region_name=None, force_reinitialize=False): # Added S3 creds
        """Initialize the S3 client for accessing Backblaze B2 via S3 API"""
        
        # Determine the key_id to check for changes (use provided S3 key if available)
        key_id_to_check = aws_access_key_id
        credential_source_for_check = "provided S3 credentials"

        if not key_id_to_check:
            key_id_to_check = os.environ.get('B2_APPLICATION_KEY_ID') # Fallback to B2 env var for key ID check
            credential_source_for_check = "B2 environment variables"
            if not key_id_to_check:
                from app.credentials import get_credentials # B2 native credentials
                stored_b2_creds = get_credentials()
                if stored_b2_creds:
                    key_id_to_check = stored_b2_creds.get('key_id')
                    credential_source_for_check = "stored B2 credentials file"
        
        if self.s3_client and not force_reinitialize and key_id_to_check == self.current_s3_key_id:
            logger.debug(f"S3 client already initialized with the same key_id ({credential_source_for_check}). Skipping re-initialization.")
            return
        elif self.s3_client and key_id_to_check != self.current_s3_key_id:
             logger.info(f"S3 Key ID has changed (from {self.current_s3_key_id} using {credential_source_for_check} to {key_id_to_check}). Forcing re-initialization of S3 client.")
             force_reinitialize = True # Ensure re-init if key changed

        logger.info(f"Initializing S3 client. Force reinitialize: {force_reinitialize}")
        self.s3_client = None 
        self.s3_resource = None
        self.current_s3_key_id = None

        s3_access_key_id_to_use = aws_access_key_id
        s3_secret_key_to_use = aws_secret_access_key
        s3_endpoint_url_to_use = endpoint_url
        s3_region_name_to_use = region_name
        credential_source = "provided S3 credentials"

        if not all([s3_access_key_id_to_use, s3_secret_key_to_use, s3_endpoint_url_to_use]):
            logger.info("Provided S3 credentials incomplete. Falling back to environment variables for S3.")
            s3_access_key_id_to_use = os.environ.get('AWS_ACCESS_KEY_ID') # Standard S3 env var
            s3_secret_key_to_use = os.environ.get('AWS_SECRET_ACCESS_KEY') # Standard S3 env var
            s3_endpoint_url_to_use = os.environ.get('B2_S3_ENDPOINT_URL') # B2 specific S3 endpoint
            s3_region_name_to_use = os.environ.get('B2_S3_REGION') # B2 specific S3 region
            credential_source = "S3 environment variables (AWS_ACCESS_KEY_ID, etc.)"
            
            if not all([s3_access_key_id_to_use, s3_secret_key_to_use, s3_endpoint_url_to_use]):
                logger.warning("S3 environment variables also incomplete. S3 client cannot be initialized with S3-specific credentials.")
                # As a last resort, try B2 native credentials if S3 specific ones are not found
                # This might be needed if the user intends to use B2 keys with S3 endpoint.
                logger.info("Attempting to use B2 native credentials for S3 client as a fallback.")
                b2_key_id_env = os.environ.get('B2_APPLICATION_KEY_ID')
                b2_app_key_env = os.environ.get('B2_APPLICATION_KEY')
                
                if b2_key_id_env and b2_app_key_env:
                    s3_access_key_id_to_use = b2_key_id_env
                    s3_secret_key_to_use = b2_app_key_env
                    # Endpoint still needs to be defined, B2 S3 endpoints are not fixed per key
                    # This part of the logic might need refinement based on how B2 S3 endpoints are determined
                    # For now, we'll rely on the list of common endpoints if s3_endpoint_url_to_use is still None
                    credential_source = "B2 native environment variables (B2_APPLICATION_KEY_ID)"
                    logger.info(f"Using B2 native credentials from env for S3 client. Endpoint URL: {s3_endpoint_url_to_use}")
                else:
                    from app.credentials import get_credentials as get_b2_credentials
                    stored_b2_creds = get_b2_credentials()
                    if stored_b2_creds and stored_b2_creds.get('key_id') and stored_b2_creds.get('application_key'):
                        s3_access_key_id_to_use = stored_b2_creds['key_id']
                        s3_secret_key_to_use = stored_b2_creds['application_key']
                        credential_source = "stored B2 native credentials file"
                        logger.info(f"Using stored B2 native credentials for S3 client. Endpoint URL: {s3_endpoint_url_to_use}")
                    else:
                        logger.error("No S3 or B2 credentials found to initialize S3 client.")
                        return

        if not s3_access_key_id_to_use or not s3_secret_key_to_use:
            logger.error(f"S3 Access Key ID or Secret Access Key is missing after checking all sources. Cannot initialize S3 client. Source: {credential_source}")
            return

        self.current_s3_key_id = s3_access_key_id_to_use # Store the key_id being used for S3

        logger.info(f"Attempting to initialize S3 client using {credential_source} with Key ID ending ...{s3_access_key_id_to_use[-4:] if len(s3_access_key_id_to_use) > 3 else s3_access_key_id_to_use}.")

        # If a specific endpoint_url is provided (either directly or from env), use it.
        # Otherwise, iterate through common B2 S3 endpoints.
        endpoints_to_try = []
        if s3_endpoint_url_to_use:
            endpoints_to_try.append(s3_endpoint_url_to_use)
        else: # Fallback to common B2 S3 endpoints if no specific one is given
            logger.info("No specific S3 endpoint URL provided, will try common Backblaze S3 endpoints.")
            endpoints_to_try = [
                'https://s3.us-west-004.backblazeb2.com',
                'https://s3.us-west-001.backblazeb2.com',
                'https://s3.us-west-002.backblazeb2.com',
                'https://s3.us-east-005.backblazeb2.com',
                'https://s3.eu-central-003.backblazeb2.com'
            ]
        
        successful_endpoint = None
        for endpoint_url_iter in endpoints_to_try:
            try:
                logger.info(f"Trying S3 endpoint: {endpoint_url_iter}")
                # Use s3_region_name_to_use if provided, otherwise Boto3 might infer or it might not be strictly needed for B2
                client_config_args = {
                    'service_name': 's3',
                    'endpoint_url': endpoint_url_iter,
                    'aws_access_key_id': s3_access_key_id_to_use,
                    'aws_secret_access_key': s3_secret_key_to_use,
                    'config': boto3.session.Config(
                        signature_version='s3v4',
                        connect_timeout=15,
                        retries={'max_attempts': 5}
                    )
                }
                if s3_region_name_to_use: # Add region if available
                    client_config_args['region_name'] = s3_region_name_to_use
                
                temp_s3_client = boto3.client(**client_config_args)
                
                response = temp_s3_client.list_buckets() 
                bucket_count = len(response.get('Buckets', []))
                
                self.s3_client = temp_s3_client
                # For s3_resource, ensure region_name is also passed if used for client
                resource_config_args = client_config_args.copy() # Start with client args
                del resource_config_args['service_name'] # service_name is not for resource directly
                self.s3_resource = boto3.resource('s3', **resource_config_args)

                successful_endpoint = endpoint_url_iter
                logger.info(f"Successfully connected to S3 API at {successful_endpoint} - found {bucket_count} buckets using key ID ...{s3_access_key_id_to_use[-4:] if len(s3_access_key_id_to_use) > 3 else s3_access_key_id_to_use}.")
                break 
            except ClientError as client_error:
                error_code = client_error.response.get('Error', {}).get('Code', 'Unknown')
                logger.warning(f"S3 endpoint {endpoint_url_iter} failed: {error_code} - {str(client_error)}. Key ID used: ...{s3_access_key_id_to_use[-4:] if len(s3_access_key_id_to_use) > 4 else s3_access_key_id_to_use}")
                if error_code == "InvalidAccessKeyId":
                    logger.error(f"Critical: Received InvalidAccessKeyId for key ...{s3_access_key_id_to_use[-4:] if len(s3_access_key_id_to_use) > 4 else s3_access_key_id_to_use} at endpoint {endpoint_url_iter}. Check credentials and key permissions for S3 API access.")
                # Clear before next attempt
                self.s3_client = None
                self.s3_resource = None
            except (NoCredentialsError, CredentialRetrievalError) as cred_error:
                logger.error(f"S3 endpoint {endpoint_url_iter} failed due to credential issue: {str(cred_error)}")
                self.s3_client = None
                self.s3_resource = None
                # If basic credential errors occur, probably no point trying other endpoints with same creds
                break 
            except botocore.exceptions.BotoCoreError as boto_error: # More generic Boto error
                logger.warning(f"S3 endpoint {endpoint_url_iter} failed with BotoCoreError: {str(boto_error)}")
                self.s3_client = None
                self.s3_resource = None
            except Exception as e:
                logger.error(f"Unexpected error trying S3 endpoint {endpoint_url_iter}: {type(e).__name__} - {str(e)}")
                self.s3_client = None
                self.s3_resource = None
                
        if self.s3_client and self.s3_resource:
            logger.info(f"S3 client initialized successfully with endpoint: {successful_endpoint}")
        else:
            logger.error(f"Failed to initialize S3 client with any endpoint. Last key ID tried: ...{s3_access_key_id_to_use[-4:] if len(s3_access_key_id_to_use) > 4 else s3_access_key_id_to_use}. Check logs for specific errors like InvalidAccessKeyId.")

    def clear_auth_cache(self): # This is from parent, S3 client has its own re-init logic
        """Clears the parent's auth cache and forces S3 client re-initialization."""
        super().clear_auth_cache() # Call parent method
        logger.info("Parent auth cache cleared. Forcing S3 client re-initialization.")
        self._initialize_s3_client(force_reinitialize=True)


    def get_s3_bucket_usage(self, bucket_name, progress_callback=None):
        """Get usage statistics for a specific bucket via the S3 API."""
        absolute_cache_dir = None
        cache_file_path = None
        
        # Cache handling setup
        if CACHE_ENABLED and CACHE_DIR:
            try:
                absolute_cache_dir = os.path.abspath(CACHE_DIR)
                cache_filename = f"s3_bucket_usage_{bucket_name}.json"
                cache_file_path = os.path.join(absolute_cache_dir, cache_filename)
                logger.debug(f"Cache file path for {bucket_name}: {cache_file_path}")

                # Ensure cache directory exists before trying to read
                os.makedirs(absolute_cache_dir, exist_ok=True)

                if os.path.exists(cache_file_path):
                    try:
                        with open(cache_file_path, 'r') as f:
                            cached_data = json.load(f)
                        
                        cache_timestamp = cached_data.get('timestamp', 0)
                        if (time.time() - cache_timestamp) < CACHE_TTL_SECONDS:
                            logger.info(f"Returning cached S3 bucket usage for {bucket_name} from {cache_file_path}")
                            cached_data_payload = cached_data.get('payload', {})
                            cached_data_payload['accurate'] = cached_data_payload.get('accurate', True)
                            cached_data_payload['source'] = cached_data_payload.get('source', 's3_api_cache')
                            return cached_data_payload
                        else:
                            logger.info(f"Cache for {bucket_name} is stale. Fetching fresh data.")
                    except Exception as e:
                        logger.warning(f"Error reading cache file {cache_file_path}: {e}. Fetching fresh data.")
            except Exception as e:
                logger.error(f"Error setting up cache directory {CACHE_DIR}: {e}. Caching might be affected.")
                # Continue without caching if directory setup fails
                cache_file_path = None # Ensure we don't try to write later if setup failed

        try:
            # First, test S3 connection by listing buckets
            try:
                self.s3_client.list_buckets()
                logger.info("S3 connection test successful")
                
                # Additional check: verify this bucket exists and is accessible
                try:
                    self.s3_client.head_bucket(Bucket=bucket_name)
                    logger.info(f"Bucket '{bucket_name}' exists and is accessible")
                except ClientError as e:
                    error_code = e.response.get('Error', {}).get('Code', 'Unknown')
                    if error_code == '404':
                        logger.error(f"Bucket '{bucket_name}' does not exist")
                    elif error_code == '403':
                        logger.error(f"Access denied to bucket '{bucket_name}'. Check permissions.")
                    else:
                        logger.error(f"Error accessing bucket '{bucket_name}': {error_code} - {str(e)}")
                    return None
                
            except Exception as conn_error:
                logger.error(f"S3 connection test failed: {str(conn_error)}")
                return None
                
            # Get bucket using S3 resource
            bucket = self.s3_resource.Bucket(bucket_name)
            
            # Initialize counters
            total_size = 0
            file_count = 0
            largest_files = []
            pagination_count = 0
            
            # Process objects
            logger.info(f"Getting S3 bucket stats for {bucket_name}")
            for obj in bucket.objects.all():
                file_count += 1
                if obj.size > 0:  # Skip zero-sized objects
                    total_size += obj.size
                    
                    # Track largest files
                    if len(largest_files) < 10:
                        largest_files.append({
                            'fileName': obj.key,
                            'size': obj.size,
                            'uploadTimestamp': obj.last_modified.timestamp() if hasattr(obj, 'last_modified') else None
                        })
                        largest_files.sort(key=lambda x: x['size'], reverse=True)
                    elif obj.size > largest_files[-1]['size']:
                        largest_files[-1] = {
                            'fileName': obj.key,
                            'size': obj.size,
                            'uploadTimestamp': obj.last_modified.timestamp() if hasattr(obj, 'last_modified') else None
                        }
                        largest_files.sort(key=lambda x: x['size'], reverse=True)
                        
                # Track pagination - S3 internally paginates by 1000 objects
                if file_count % 1000 == 0:
                    pagination_count = file_count // 1000
                    logger.info(f"Processed {file_count} objects in {bucket_name} (Pagination: Page {pagination_count})")
                    
                    # Report pagination progress if callback provided
                    if progress_callback:
                        progress_callback("BUCKET_PROGRESS", {
                            "bucket_name": bucket_name,
                            "objects_processed_in_bucket": file_count,
                            "last_object_key": obj.key if hasattr(obj, 'key') else f"Page {pagination_count}",
                            "pagination_info": {
                                "current_page": pagination_count,
                                "files_processed": file_count
                            }
                        })
            
            # Final pagination count
            pagination_count = (file_count // 1000) + (1 if file_count % 1000 > 0 else 0)
            
            result = {
                'total_size': total_size,
                'files_count': file_count,
                'largest_files': largest_files,
                'accurate': True,
                'source': 's3_api',
                'pagination_pages': pagination_count
            }
            
            logger.info(f"S3 API bucket stats for {bucket_name}: {total_size} bytes across {file_count} files (Pages: {pagination_count})")

            # Write to cache
            if CACHE_ENABLED and cache_file_path and absolute_cache_dir:
                try:
                    # Ensure directory exists again (it should, but defensive)
                    os.makedirs(absolute_cache_dir, exist_ok=True) 
                    with open(cache_file_path, 'w') as f:
                        json.dump({'timestamp': time.time(), 'payload': result}, f)
                    logger.info(f"S3 bucket usage for {bucket_name} cached to {cache_file_path}")
                except Exception as e:
                    logger.error(f"Error writing to cache file {cache_file_path}: {e}")
            
            return result
            
        except Exception as e:
            logger.error(f"Error getting S3 bucket stats: {str(e)}")
            return None
    
    def get_bucket_usage(self, bucket_id, bucket_name, use_accurate_method=True):
        """Get usage statistics for a specific bucket
        
        This enhanced version attempts to use the S3 API first for maximum accuracy,
        then falls back to the improved B2 API methods, and finally to the original method.
        
        Args:
            bucket_id: The ID of the bucket
            bucket_name: The name of the bucket
            use_accurate_method: If True, use more accurate but potentially slower methods
        """
        # Check cache first
        cache_key = f"bucket_stats_s3_{bucket_id}"
        cache_file = os.path.join(self.cache_dir, f"{cache_key}.json")
        
        try:
            from app.config import BUCKET_STATS_CACHE_HOURS
            
            if os.path.exists(cache_file):
                file_age_hours = (time.time() - os.path.getmtime(cache_file)) / 3600
                
                if file_age_hours < BUCKET_STATS_CACHE_HOURS:
                    with open(cache_file, 'r') as f:
                        logger.info(f"Using cached S3 bucket stats for {bucket_name} ({file_age_hours:.1f}h old)")
                        return json.load(f)
        except Exception as e:
            logger.warning(f"Error reading S3 bucket stats cache: {e}")
        
        # Try S3 API first
        if use_accurate_method and self.s3_client:
            logger.info(f"Using S3 API for {bucket_name} stats")
            s3_stats = self.get_s3_bucket_usage(bucket_name)
            
            if s3_stats:
                # Cache the results
                try:
                    with open(cache_file, 'w') as f:
                        json.dump(s3_stats, f)
                        logger.debug(f"Cached S3 bucket stats for {bucket_name}")
                except Exception as e:
                    logger.warning(f"Failed to cache S3 bucket stats: {e}")
                
                return s3_stats
                
            logger.info(f"S3 API stats not available for {bucket_name}, falling back to B2 API")
                
        # Fall back to accurate B2 API method
        if use_accurate_method:
            return super().get_accurate_bucket_usage(bucket_id, bucket_name)
            
        # Fall back to original estimation method
        return super().get_bucket_usage(bucket_id, bucket_name, use_accurate_method=False)
        
    def _load_cached_snapshot(self):
        """Load the most recent cached snapshot data"""
        cache_file = os.path.join(self.cache_dir, 'latest_snapshot.json')
        
        try:
            if os.path.exists(cache_file):
                with open(cache_file, 'r') as f:
                    data = json.load(f)
                    logger.info("Loaded previous snapshot as reference")
                    return data
        except Exception as e:
            logger.warning(f"Could not load cached snapshot: {e}")
            
        return None
        
    def _save_cached_snapshot(self, snapshot_data):
        """Cache the latest snapshot for future reference"""
        cache_file = os.path.join(self.cache_dir, 'latest_snapshot.json')
        
        try:
            with open(cache_file, 'w') as f:
                json.dump(snapshot_data, f)
                logger.debug("Saved latest snapshot to cache")
        except Exception as e: # Added except block
            logger.warning(f"Could not save snapshot cache: {e}")
            
    def take_snapshot(self, snapshot_name="S3 Snapshot", progress_callback=None, account_info=None): # Added snapshot_name, progress_callback, account_info
        """Take a snapshot of the current account usage and costs using S3 API.
        Args:
            snapshot_name (str): A descriptive name for this snapshot run.
            progress_callback (function): Optional function to call with progress updates.
                                          Expected signature: callback(event_type, data_dict)
            account_info (dict): Account information (not typically used by S3 client directly for listing,
                                 but passed for consistency with Native client if needed for other things).
        """
        logger.info(f"Starting S3 API usage snapshot: '{snapshot_name}' (Parallel Ops: {self.parallel_operations})")
        start_time = time.time()
        initial_api_calls = self.api_calls_made # Assuming parent class tracks this
        
        processed_buckets_count = 0
        total_buckets_for_progress = 0 # Initialize for progress reporting
        snapshot_data = {
            'snapshot_name': snapshot_name,
            'timestamp': datetime.utcnow().isoformat(),
            'api_type': 's3',
            'total_storage_bytes': 0,
            'total_storage_cost': 0,
            'total_download_bytes': 0, # S3 API does not provide this directly per snapshot
            'total_download_cost': 0,  # S3 API does not provide this directly per snapshot
            'total_api_calls': 0,    # Will be calculated based on actual calls
            'total_cost': 0,         # Sum of storage and estimated API cost
            'buckets': [],
            'account_id': account_info.get('accountId') if account_info else None, # If available
            'api_calls_made_during_snapshot': 0 # Specific to this snapshot
        }

        if not self.s3_client or not self.s3_resource:
            logger.error("S3 client or resource not initialized. Cannot take S3 snapshot.")
            if progress_callback:
                progress_callback("SNAPSHOT_ERROR", {"error": "S3 client not initialized", "message": "Failed to connect to S3 service."})
            return None

        try:
            # Initial progress update: SNAPSHOT_SETUP
            # Get list of buckets first to inform total_buckets
            s3_buckets_list = []
            try:
                s3_buckets_response = self.s3_client.list_buckets()
                s3_buckets_list = [{'bucketId': b['Name'], 'bucketName': b['Name']} for b in s3_buckets_response.get('Buckets', [])] # S3 uses Name as ID for many ops
                total_buckets_for_progress = len(s3_buckets_list)
                logger.info(f"Found {total_buckets_for_progress} buckets via S3 API.")
                if progress_callback:
                    progress_callback("SNAPSHOT_SETUP", {
                        "total_buckets": total_buckets_for_progress,
                        "bucket_names": [b['bucketName'] for b in s3_buckets_list]
                    })
            except Exception as e_list_buckets:
                logger.error(f"Failed to list S3 buckets: {e_list_buckets}", exc_info=True)
                if progress_callback:
                    progress_callback("SNAPSHOT_ERROR", {"error": "Failed to list S3 buckets", "message": str(e_list_buckets)})
                return None
            
            if total_buckets_for_progress == 0:
                logger.info("No S3 buckets found to process.")
                # Still report completion, even if no buckets
                if progress_callback:
                     progress_callback("BUCKET_COMPLETE", {"bucket_name": "N/A", "message": "No buckets found."}) # Generic completion for overall
                # Fall through to finalize and return empty snapshot structure

            # Helper function to process a single S3 bucket
            def process_s3_bucket(bucket_info):
                """Process a single bucket to get its stats (called by ThreadPoolExecutor)"""
                bucket_name = bucket_info['name']
                bucket_id = bucket_info.get('id')  # May not be needed for S3 API
                
                # Report start of bucket processing
                if progress_callback:
                    progress_callback("BUCKET_START", {"bucket_name": bucket_name})
                
                logger.info(f"Processing bucket (S3 API): {bucket_name}")
                
                # Report initial progress
                if progress_callback:
                    progress_callback("BUCKET_PROGRESS", {
                        "bucket_name": bucket_name,
                        "objects_processed_in_bucket": 0,
                        "last_object_key": "Starting S3 bucket processing"
                    })
                
                try:
                    # Use the enhanced S3 bucket usage method that directly uses boto3
                    bucket_stats = self.get_s3_bucket_usage(bucket_name, progress_callback=progress_callback)
                    
                    if not bucket_stats:
                        logger.warning(f"Could not get S3 stats for bucket {bucket_name}, skipping")
                        if progress_callback:
                            progress_callback("BUCKET_ERROR", {
                                "bucket_name": bucket_name, 
                                "error": "Failed to get S3 bucket statistics"
                            })
                        return None
                    
                    # Extract and calculate costs
                    storage_bytes = bucket_stats.get('total_size', 0)
                    storage_gb = storage_bytes / (1024 * 1024 * 1024)
                    storage_cost = storage_gb * self.STORAGE_COST_PER_GB
                    
                    # Get download stats from previous snapshot if available
                    download_bytes = 0
                    if prev_snapshot:
                        for prev_bucket in prev_snapshot.get('buckets', []):
                            if prev_bucket.get('name') == bucket_name:
                                download_bytes = prev_bucket.get('download_bytes', 0)
                                break
                    
                    download_gb = download_bytes / (1024 * 1024 * 1024)
                    download_cost = max(0, download_gb * self.DOWNLOAD_COST_PER_GB)
                    
                    # Total cost for this bucket
                    bucket_total_cost = storage_cost + download_cost
                    
                    # Create the bucket info object for the snapshot
                    bucket_result = {
                        'name': bucket_name,
                        'id': bucket_id or bucket_name,  # Use name as ID if no ID provided
                        'storage_bytes': storage_bytes,
                        'storage_cost': storage_cost,
                        'download_bytes': download_bytes,
                        'download_cost': download_cost,
                        'api_calls': 0,  # Not tracked in same way for S3
                        'api_cost': 0,   # Not tracked in same way for S3
                        'total_cost': bucket_total_cost,
                        'files_count': bucket_stats.get('files_count', 0),
                        'reporting_method': bucket_stats.get('source', 's3_api'),
                        'largest_files': bucket_stats.get('largest_files', []),
                        'pagination_pages': bucket_stats.get('pagination_pages', 0)
                    }
                    
                    # Report completion
                    if progress_callback:
                        progress_callback("BUCKET_COMPLETE", {
                            "bucket_name": bucket_name,
                            "objects_processed_in_bucket": bucket_stats.get('files_count', 0),
                            "pagination_info": {
                                "total_pages": bucket_stats.get('pagination_pages', 0),
                                "files_processed": bucket_stats.get('files_count', 0)
                            }
                        })
                    
                    return bucket_result
                    
                except Exception as e:
                    logger.error(f"Error processing S3 bucket {bucket_name}: {str(e)}", exc_info=True)
                    if progress_callback:
                        progress_callback("BUCKET_ERROR", {"bucket_name": bucket_name, "error": str(e)})
                    return None

            # Use ThreadPoolExecutor for parallel processing
            bucket_data_results = []
            with concurrent.futures.ThreadPoolExecutor(max_workers=self.parallel_operations) as executor:
                future_to_bucket_info = {executor.submit(process_s3_bucket, b_info): b_info for b_info in s3_buckets_list}
                
                for future in concurrent.futures.as_completed(future_to_bucket_info):
                    bucket_info_for_future = future_to_bucket_info[future]
                    try:
                        data = future.result()
                        if data: # If None, it means an error occurred and was handled in process_s3_bucket
                            bucket_data_results.append(data)
                            snapshot_data['total_storage_bytes'] += data['storage_bytes']
                            snapshot_data['total_storage_cost'] += data['storage_cost']
                            # Download bytes/cost are placeholders for S3, not summed here unless changed
                    except Exception as exc:
                        logger.error(f'S3 Bucket {bucket_info_for_future["bucketName"]} generated an exception during future processing: {exc}', exc_info=True)
                        if progress_callback:
                            progress_callback("BUCKET_ERROR", {"bucket_name": bucket_info_for_future["bucketName"], "error": str(exc)})
                    # processed_buckets_count is implicitly handled by BUCKET_COMPLETE/ERROR callbacks from within process_s3_bucket

            snapshot_data['buckets'] = bucket_data_results
            
            # API calls for S3 are harder to track precisely like B2's b2_authorize_account etc.
            # Boto3 might make multiple underlying HTTP calls.
            # For now, estimate or leave as a rough count if parent class tracks general HTTP.
            # Let's assume parent's self.api_calls_made is a general counter.
            snapshot_api_calls = self.api_calls_made - initial_api_calls
            snapshot_data['api_calls_made_during_snapshot'] = snapshot_api_calls
            snapshot_data['total_api_calls'] = snapshot_api_calls # Or a more S3-specific estimate

            # Estimate API cost (very rough for S3 without detailed call types)
            # Using a generic cost per 1000 calls, similar to B2 example
            generic_s3_call_cost_per_1000 = getattr(self, 'S3_CALL_COST_PER_1000', 0.004) # Example value
            estimated_api_cost = (snapshot_api_calls * generic_s3_call_cost_per_1000) / 1000
            snapshot_data['total_api_cost'] = estimated_api_cost # Add if you have this field
            
            snapshot_data['total_cost'] = snapshot_data['total_storage_cost'] + snapshot_data.get('total_download_cost',0) + estimated_api_cost
            
            # self._save_cached_snapshot(snapshot_data) # If S3 snapshots also use this generic cache

            elapsed = time.time() - start_time
            logger.info(f"S3 Snapshot '{snapshot_name}' completed in {elapsed:.2f}s. Total Storage: {snapshot_data['total_storage_bytes']} bytes. API Calls (estimated): {snapshot_api_calls}")
            
            # Final progress update for completion
            if progress_callback:
                progress_callback("SNAPSHOT_COMPLETE", {
                    "message": "S3 Snapshot process completed.",
                    "total_storage_bytes": snapshot_data['total_storage_bytes'],
                    "total_cost": snapshot_data['total_cost'],
                    "duration_seconds": elapsed
                })

            return snapshot_data
            
        except Exception as e:
            logger.error(f"Error taking S3 snapshot '{snapshot_name}': {str(e)}", exc_info=True)
            if progress_callback:
                progress_callback("SNAPSHOT_ERROR", {
                    "error": f"General error during S3 snapshot: {str(e)}",
                    "message": str(e)
                })
            return None
