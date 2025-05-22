import requests
import time
import logging
import json
import os
from datetime import datetime, timedelta
from functools import lru_cache
import concurrent.futures # Added import
from app.config import (
    B2_APPLICATION_KEY_ID, B2_APPLICATION_KEY,
    STORAGE_COST_PER_GB, DOWNLOAD_COST_PER_GB,
    CLASS_A_TRANSACTION_COST, CLASS_B_TRANSACTION_COST,
    API_CACHE_TTL, SNAPSHOT_CACHE_DIR, BUCKET_STATS_CACHE_HOURS,
    PARALLEL_BUCKET_OPERATIONS, # Import for default value
    MAX_FILES_PER_BUCKET, # Added import for MAX_FILES_PER_BUCKET
    CACHE_ENABLED as OBJECT_CACHE_ENABLED, # Renaming to avoid conflict if used directly
    CACHE_DIR as OBJECT_CACHE_DIR,
    CACHE_TTL_SECONDS as OBJECT_CACHE_TTL_SECONDS
)
from app.credentials import get_credentials

logger = logging.getLogger(__name__)

class BackblazeClient:
    """Client for interacting with the Backblaze B2 API"""
    
    # Use pricing from config, which can be overridden by environment variables
    STORAGE_COST_PER_GB = STORAGE_COST_PER_GB
    DOWNLOAD_COST_PER_GB = DOWNLOAD_COST_PER_GB
    CLASS_A_TRANSACTION_COST = CLASS_A_TRANSACTION_COST
    CLASS_B_TRANSACTION_COST = CLASS_B_TRANSACTION_COST
    
    def __init__(self, parallel_operations=None): # Added parallel_operations parameter
        """Initialize the Backblaze B2 client"""
        self.api_url = None
        self.auth_token = None
        self.account_id = None
        self.download_url = None
        self.api_calls_made = 0
        self.auth_timestamp = None
        self.auth_expiration = 86400  # Default auth token expiration (24 hours)
        
        # For B2 API general caching (like list_buckets, auth)
        self.snapshot_cache_dir = SNAPSHOT_CACHE_DIR 
        os.makedirs(self.snapshot_cache_dir, exist_ok=True)

        # For B2 bucket stats caching (similar to S3 object metadata caching)
        self.object_cache_dir_abs = None
        if OBJECT_CACHE_ENABLED:
            try:
                project_root = os.getcwd()
                # OBJECT_CACHE_DIR is 'instance/cache/object_metadata'
                self.object_cache_dir_abs = os.path.abspath(os.path.join(project_root, OBJECT_CACHE_DIR))
                os.makedirs(self.object_cache_dir_abs, exist_ok=True)
                logger.info(f"B2 API client: Object metadata cache directory ensured at: {self.object_cache_dir_abs}")
            except Exception as e:
                logger.error(f"B2 API client: Could not create object cache directory at {OBJECT_CACHE_DIR} (abs: {self.object_cache_dir_abs}): {e}")

        # Store parallel_operations, defaulting to value from config
        self.parallel_operations = parallel_operations if parallel_operations is not None else PARALLEL_BUCKET_OPERATIONS
        
        # Check for cached auth data first
        if not self._load_cached_auth():            # If no cache or expired, authorize
            self.authorize()
            
    def clear_auth_cache(self):
        """Remove the authentication cache file to force re-authorization with new credentials"""
        cache_file = os.path.join(self.snapshot_cache_dir, 'auth_cache.json')
        try:
            if os.path.exists(cache_file):
                os.remove(cache_file)
                logger.info("Cleared authentication cache")
                return True
            return False
        except Exception as e:
            logger.warning(f"Failed to clear auth cache: {e}")
            return False
        
    def _load_cached_auth(self):
        """Load cached authorization data if available and not expired"""
        cache_file = os.path.join(self.snapshot_cache_dir, 'auth_cache.json')
        
        try:
            if os.path.exists(cache_file):
                with open(cache_file, 'r') as f:
                    cache_data = json.load(f)
                
                # Check if cache is still valid
                cached_time = datetime.fromisoformat(cache_data.get('timestamp', '2000-01-01'))
                if datetime.now() - cached_time < timedelta(seconds=self.auth_expiration - 3600):
                    # Use cached data (with 1-hour safety margin)
                    self.api_url = cache_data.get('apiUrl')
                    self.auth_token = cache_data.get('authorizationToken')
                    self.account_id = cache_data.get('accountId')
                    self.download_url = cache_data.get('downloadUrl')
                    self.auth_timestamp = cached_time
                    logger.info("Using cached authentication data")
                    return True
        except Exception as e:
            logger.warning(f"Could not load cached auth data: {e}")
        return False
        
    def _save_auth_cache(self, auth_data):
        """Save authorization data to cache"""
        cache_file = os.path.join(self.snapshot_cache_dir, 'auth_cache.json')
        try:
            cache_data = auth_data.copy()
            cache_data['timestamp'] = datetime.now().isoformat()
            with open(cache_file, 'w') as f:
                json.dump(cache_data, f)
            logger.debug("Saved authentication data to cache")
        except Exception as e:
            logger.warning(f"Could not save auth cache: {e}")
            
    def authorize(self):
        """Authorize with the Backblaze B2 API"""
        url = 'https://api.backblazeb2.com/b2api/v2/b2_authorize_account'
        
        # Get API credentials, prioritizing environment variables
        key_id = B2_APPLICATION_KEY_ID
        app_key = B2_APPLICATION_KEY
        
        # If not set in environment, try to get from stored credentials
        if not (key_id and app_key):
            stored_creds = get_credentials()
            if stored_creds:
                key_id = stored_creds.get('key_id')
                app_key = stored_creds.get('application_key')
        
        if not (key_id and app_key):
            logger.error("No Backblaze API credentials available")
            return False
        
        try:
            response = requests.get(
                url, 
                auth=(key_id, app_key),
                timeout=30
            )
            response.raise_for_status()
            
            auth_data = response.json()
            self.api_url = auth_data['apiUrl']
            self.auth_token = auth_data['authorizationToken']
            self.account_id = auth_data['accountId']
            self.download_url = auth_data['downloadUrl']
            self.api_calls_made += 1
            self.auth_timestamp = datetime.now()
            # Save to cache
            self._save_auth_cache(auth_data)
            logger.info(f"Successfully authorized with Backblaze B2 API")
            return True
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to authorize with Backblaze B2 API: {str(e)}")
            return False
            
    def _get_cache_key(self, endpoint, method, data=None, params=None):
        """Generate a cache key for an API request"""
        key_parts = [endpoint, method.lower()]
        
        if data:
            # Sort dictionary keys to ensure consistent cache keys
            key_parts.append(json.dumps(data, sort_keys=True))
        
        if params:
            key_parts.append(json.dumps(params, sort_keys=True))
            
        return '_'.join(key_parts).replace('/', '_')
    
    def _get_cached_response(self, cache_key):
        """Get a cached API response if available and not expired"""
        cache_file = os.path.join(self.snapshot_cache_dir, f"{cache_key}.json")
        
        try:
            if os.path.exists(cache_file):
                file_age = time.time() - os.path.getmtime(cache_file)
                
                if file_age < API_CACHE_TTL:
                    with open(cache_file, 'r') as f:
                        logger.debug(f"Using cached response for {cache_key}")
                        return json.load(f)
        except Exception as e:
            logger.warning(f"Error reading cache file {cache_key}: {e}")
            
        return None
    
    def _save_cached_response(self, cache_key, response_data):
        """Save an API response to cache"""
        cache_file = os.path.join(self.snapshot_cache_dir, f"{cache_key}.json")
        
        try:
            with open(cache_file, 'w') as f:
                json.dump(response_data, f)
                logger.debug(f"Cached response for {cache_key}")
        except Exception as e:
            logger.warning(f"Error saving cache file {cache_key}: {e}")

    def _make_api_request(self, endpoint, method='get', data=None, params=None, use_cache=True, retry_count=0, max_retries=3):
        """Make an API request to the Backblaze B2 API with caching and retry logic"""
        # Check if auth token is expired (if it's more than 23 hours old)
        if (self.auth_timestamp and 
                datetime.now() - self.auth_timestamp > timedelta(hours=23)):
            logger.info("Auth token age > 23h, refreshing...")
            self.authorize()
        
        if not self.auth_token or not self.api_url:
            self.authorize()
        
        # Try to use cached response for read-only operations
        if use_cache and method.lower() == 'get':
            cache_key = self._get_cache_key(endpoint, method, data, params)
            cached_response = self._get_cached_response(cache_key)
            if cached_response:
                return cached_response
        
        url = f"{self.api_url}/b2api/v2/{endpoint}"
        headers = {'Authorization': self.auth_token}
        
        try:
            if method.lower() == 'get':
                response = requests.get(url, headers=headers, params=params, timeout=30)
            elif method.lower() == 'post':
                response = requests.post(url, headers=headers, json=data, timeout=30)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")
                
            response.raise_for_status()
            self.api_calls_made += 1
            response_data = response.json()
            
            # Cache the response for GET requests
            if use_cache and method.lower() == 'get':
                cache_key = self._get_cache_key(endpoint, method, data, params)
                self._save_cached_response(cache_key, response_data)
            
            return response_data
            
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 401:
                # Token expired, try to authorize again and retry the request
                logger.warning("Auth token expired, reauthorizing...")
                if self.authorize():
                    return self._make_api_request(endpoint, method, data, params, use_cache)
            elif e.response.status_code == 503 and endpoint == 'b2_list_file_versions':
                # Service temporarily unavailable, try to get a different API endpoint
                logger.warning(f"Service temporarily unavailable (503) for {url}. Clearing auth cache and reauthorizing...")
                self.clear_auth_cache()
                if self.authorize():
                    logger.info(f"Reauthorized. New API URL: {self.api_url}")
                    return self._make_api_request(endpoint, method, data, params, use_cache)
            elif retry_count < max_retries and e.response.status_code in [429, 500, 502, 503, 504]:
                # Retry for rate limits (429) and server errors (5xx) with exponential backoff
                retry_count += 1
                wait_time = 2 ** retry_count  # Exponential backoff: 2, 4, 8 seconds
                logger.warning(f"Transient error {e.response.status_code} on attempt {retry_count}/{max_retries}. Retrying in {wait_time} seconds...")
                time.sleep(wait_time)
                return self._make_api_request(endpoint, method, data, params, use_cache, retry_count, max_retries)
            
            logger.error(f"HTTP error in API request to {endpoint}: {str(e)}")
            raise
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            # Retry connection and timeout errors with exponential backoff
            if retry_count < max_retries:
                retry_count += 1
                wait_time = 2 ** retry_count
                logger.warning(f"Connection error on attempt {retry_count}/{max_retries}. Retrying in {wait_time} seconds...")
                time.sleep(wait_time)
                return self._make_api_request(endpoint, method, data, params, use_cache, retry_count, max_retries)
            logger.error(f"Connection error in API request to {endpoint} after {max_retries} retries: {str(e)}")
            raise
        except requests.exceptions.RequestException as e:
            logger.error(f"Error in API request to {endpoint}: {str(e)}")
            raise
            
    def list_buckets(self):
        """List all buckets in the account"""
        return self._make_api_request('b2_list_buckets', 'post', {"accountId": self.account_id})
        
    def get_bucket_usage(self, bucket_id, bucket_name, progress_callback=None):
        """Get usage statistics for a specific bucket with caching, using the object metadata cache settings."""
        
        cache_file_path = None
        if OBJECT_CACHE_ENABLED and self.object_cache_dir_abs:
            cache_filename = f"b2_bucket_usage_{bucket_id}.json"
            cache_file_path = os.path.join(self.object_cache_dir_abs, cache_filename)
            logger.debug(f"B2 API cache file path for {bucket_name} ({bucket_id}): {cache_file_path}")

            if os.path.exists(cache_file_path):
                try:
                    with open(cache_file_path, 'r') as f:
                        cached_data = json.load(f)
                    
                    cache_timestamp = cached_data.get('timestamp', 0)
                    if (time.time() - cache_timestamp) < OBJECT_CACHE_TTL_SECONDS:
                        logger.info(f"Returning cached B2 bucket usage for {bucket_name} from {cache_file_path}")
                        # Ensure 'source' field for consistency
                        cached_data_payload = cached_data.get('payload', {})
                        cached_data_payload['source'] = cached_data_payload.get('source', 'b2_api_cache')
                        return cached_data_payload
                    else:
                        logger.info(f"B2 API cache for {bucket_name} is stale. Fetching fresh data.")
                except Exception as e:
                    logger.warning(f"Error reading B2 API cache file {cache_file_path}: {e}. Fetching fresh data.")
        else:
            logger.debug("B2 API: Object cache not enabled or directory not initialized. Skipping cache read.")

        # If no cache or stale, calculate usage accurately by fetching ALL files
        logger.info(f"Calculating accurate B2 bucket usage for {bucket_name} (ID: {bucket_id}) via B2 API")
        
        total_size = 0
        file_count = 0
        largest_files = []
        processed_files = 0
        pagination_count = 0

        # Pagination variables
        start_filename = None
        start_file_id = None
        has_more = True
        
        while has_more:
            pagination_count += 1
            
            # Report pagination progress if callback provided
            if progress_callback:
                progress_callback("BUCKET_PROGRESS", {
                    "bucket_name": bucket_name,
                    "objects_processed_in_bucket": processed_files,
                    "last_object_key": f"Pagination page {pagination_count}",
                    "pagination_info": {
                        "current_page": pagination_count,
                        "files_processed": processed_files
                    }
                })
            
            # Get a batch of files (up to 1000 per API call)
            if start_filename is not None and start_file_id is not None:
                files_response = self.list_file_versions(bucket_id, start_filename=start_filename, 
                                                        start_file_id=start_file_id, max_file_count=1000)
            else:
                files_response = self.list_file_versions(bucket_id, max_file_count=1000)
            
            # Process this batch of files
            batch_files = files_response.get('files', [])
            
            for file in batch_files:
                if file.get('action') == 'upload' and file.get('fileId') != 'none':
                    file_size = file.get('contentLength', 0)
                    total_size += file_size
                    file_count += 1
                    
                    # Keep track of largest files for reporting
                    if len(largest_files) < 10:
                        largest_files.append({
                            'fileName': file.get('fileName', 'unknown'),
                            'size': file_size,
                            'uploadTimestamp': file.get('uploadTimestamp')
                        })
                        largest_files.sort(key=lambda x: x['size'], reverse=True)
                    elif file_size > largest_files[-1]['size']:
                        largest_files[-1] = {
                            'fileName': file.get('fileName', 'unknown'),
                            'size': file_size,
                            'uploadTimestamp': file.get('uploadTimestamp')
                        }
                        largest_files.sort(key=lambda x: x['size'], reverse=True)
            
            processed_files += len(batch_files)
            
            # More concise logging that doesn't spam the console
            if pagination_count % 10 == 0 or processed_files % 10000 == 0 or not has_more:
                logger.info(f"Processed {processed_files} files in {bucket_name} (Pagination: Page {pagination_count})")
            
            # Check if there are more files to fetch
            if len(batch_files) > 0 and 'nextFileName' in files_response and 'nextFileId' in files_response:
                start_filename = files_response['nextFileName']
                start_file_id = files_response['nextFileId']
                has_more = True
            else:
                # Stop if either no more pagination tokens OR no files in this batch (prevents infinite loop)
                has_more = False
                if len(batch_files) == 0 and 'nextFileName' in files_response:
                    logger.warning(f"Stopping pagination for {bucket_name} at page {pagination_count}: Got nextFileName token but no files returned")
        
        logger.info(f"Accurate calculation of {bucket_name} size: {total_size} bytes across {file_count} files (Pages: {pagination_count})")
        
        result = {
            'total_size': total_size,
            'files_count': file_count,
            'largest_files': largest_files,
            'accurate': True,  # Now using accurate count instead of estimation
            'source': 'b2_api',
            'pagination_pages': pagination_count
        }

        # Save to the object metadata cache
        if OBJECT_CACHE_ENABLED and cache_file_path and self.object_cache_dir_abs:
            try:
                os.makedirs(self.object_cache_dir_abs, exist_ok=True) 
                with open(cache_file_path, 'w') as f:
                    json.dump({'timestamp': time.time(), 'payload': result}, f)
                logger.info(f"B2 bucket usage for {bucket_name} cached to {cache_file_path}")
            except Exception as e:
                logger.error(f"Error writing B2 API cache file {cache_file_path}: {e}")

        return result
    
    def list_file_versions(self, bucket_id, start_filename=None, start_file_id=None, max_file_count=1000):
        """List file versions in a bucket with enhanced error handling"""
        data = {
            "bucketId": bucket_id,
            "maxFileCount": max_file_count
        }
        
        if start_filename and start_file_id:
            data["startFileName"] = start_filename
            data["startFileId"] = start_file_id
        
        try:    
            return self._make_api_request('b2_list_file_versions', 'post', data)
        except requests.exceptions.HTTPError as e:
            # Log detailed error information
            status_code = getattr(e.response, 'status_code', None)
            error_detail = None
            
            try:
                error_detail = e.response.json()
            except:
                try:
                    error_detail = e.response.text
                except:
                    error_detail = str(e)
                    
            logger.error(f"B2 API Error listing file versions for bucket {bucket_id}: {status_code} - {error_detail}")
            
            # If this is the B2 native client and we're getting persistent errors,
            # suggest trying S3 API instead as a more reliable alternative
            logger.warning("Consider using the S3 API client (S3BackblazeClient) for more reliable access if available")
            
            # Re-raise the exception for the caller to handle
            raise
    
    def get_bucket_files_info(self, bucket_id, limit=None):
        """Get detailed information about files in a bucket with optional limit"""
        all_files = []
        start_filename = None
        start_file_id = None
        
        # Use the configured max files limit to avoid excessive API calls
        max_files = limit or 10000
        
        # This will make multiple API calls if there are more than 1000 files
        while len(all_files) < max_files:
            response = self.list_file_versions(bucket_id, start_filename, start_file_id)
            files = response.get('files', [])
            
            # Check if we got any files in this batch
            if not files:
                logger.warning(f"No files returned in batch for bucket {bucket_id} but hit max files limit")
                break
                
            all_files.extend(files)
            
            if len(files) > 0 and response.get('nextFileName') and len(all_files) < max_files:
                start_filename = response.get('nextFileName')
                start_file_id = response.get('nextFileId')
            else:
                break
                
        return all_files
    
    def get_account_info(self):
        """Get account information
        
        Note: Since B2 API doesn't have a direct endpoint called get_account_info,
        we return a dictionary with account information we already have from authorization
        and supplement it with bucket information.
        """
        # Start with information we have from authorization
        account_info = {
            'accountId': self.account_id,
            'apiUrl': self.api_url,
            'downloadUrl': self.download_url
        }
        
        # Add information about buckets
        try:
            bucket_data = self.list_buckets()
            account_info['buckets'] = bucket_data.get('buckets', [])
            account_info['bucketCount'] = len(account_info['buckets'])
        except Exception as e:
            logger.warning(f"Could not get bucket information for account info: {e}")
            account_info['buckets'] = []
            account_info['bucketCount'] = 0
            
        return account_info
    
    def get_file_download_stats(self, bucket_id, days=30):
        """
        Simulate getting download statistics
        
        Note: B2 doesn't have a direct API for download stats.
        In a real implementation, you would need to analyze B2 server logs
        or use a third-party tracking solution.
        """
        # This is a placeholder implementation        # In a real app, you would parse server logs or use Backblaze reporting features
        return {
            'download_bytes': 0,  # Placeholder
            'download_count': 0   # Placeholder
        }
        
    def _process_bucket_for_snapshot(self, bucket, prev_snapshot, progress_callback=None, account_info=None): # Added account_info
        """Helper method to process a single bucket's data for a snapshot."""
        bucket_id = bucket.get('bucketId')
        bucket_name = bucket.get('bucketName')
        
        if progress_callback:
            progress_callback("BUCKET_START", {"bucket_name": bucket_name})

        logger.info(f"Processing bucket (B2 API): {bucket_name}")
        
        # Report initial progress for B2 API
        if progress_callback:
            progress_callback("BUCKET_PROGRESS", {
                "bucket_name": bucket_name, 
                "objects_processed_in_bucket": 0,
                "last_object_key": "Starting bucket processing"
            })

        try:
            bucket_stats = self.get_bucket_usage(bucket_id, bucket_name, progress_callback=progress_callback)
            
            storage_bytes = bucket_stats.get('total_size', 0)
            storage_gb = storage_bytes / (1024 * 1024 * 1024)
            storage_cost = storage_gb * self.STORAGE_COST_PER_GB
            
            download_bytes = 0
            if prev_snapshot:
                for prev_bucket_item in prev_snapshot.get('buckets', []):
                    if prev_bucket_item.get('name') == bucket_name:
                        download_bytes = prev_bucket_item.get('download_bytes', 0)
                        break
            
            download_gb = download_bytes / (1024 * 1024 * 1024)
            download_cost = max(0, download_gb * self.DOWNLOAD_COST_PER_GB)
            
            bucket_total_cost = storage_cost + download_cost

            bucket_info = {
                'name': bucket_name,
                'id': bucket_id,
                'storage_bytes': storage_bytes,
                'storage_cost': storage_cost,
                'download_bytes': download_bytes,
                'download_cost': download_cost,
                'api_calls': 0, 
                'api_cost': 0,
                'total_cost': bucket_total_cost,
                'files_count': bucket_stats.get('files_count', 0),
                'reporting_method': bucket_stats.get('source', 'b2_api'),
                'largest_files': bucket_stats.get('largest_files', []),
                'pagination_pages': bucket_stats.get('pagination_pages', 0)
            }
            
            if progress_callback:
                progress_callback("BUCKET_COMPLETE", {
                    "bucket_name": bucket_name, 
                    "objects_processed_in_bucket": bucket_stats.get('files_count', 0), # Total files as "objects"
                    "pagination_info": {
                        "total_pages": bucket_stats.get('pagination_pages', 0),
                        "files_processed": bucket_stats.get('files_count', 0)
                    }
                })
            return bucket_info

        except Exception as e:
            logger.error(f"Error processing B2 bucket {bucket_name}: {e}", exc_info=True)
            if progress_callback:
                progress_callback("BUCKET_ERROR", {"bucket_name": bucket_name, "error": str(e)})
            return None # Or raise to be caught by the main snapshot loop

    def take_snapshot(self, snapshot_name_unused, progress_callback=None, account_info=None): # Added snapshot_name_unused and account_info
        """Take a snapshot of the current account usage and costs with optimized data collection"""
        logger.info(f"Starting Backblaze usage snapshot (B2 API, Parallel Ops: {self.parallel_operations})")
        start_time = time.time()
        initial_api_calls = self.api_calls_made
        
        processed_buckets_count = 0
        total_buckets_to_process = 0
        bucket_data_results = []

        try:
            prev_snapshot = self._load_cached_snapshot()
            
            # Get list of buckets
            # The account_info passed to snapshot_worker might already have this if fetched by the app
            # If not, or if we prefer the client to always fetch, we call list_buckets()
            # For B2, account_info from app.py's snapshot_worker will contain client.get_account_info()
            # which includes the bucket list.
            
            buckets = []
            if account_info and 'buckets' in account_info:
                buckets = account_info.get('buckets', [])
                logger.info(f"Using bucket list from provided account_info. Count: {len(buckets)}")
            else:
                logger.warning("No bucket list in account_info, fetching fresh list from B2 API.")
                buckets_response = self.list_buckets() # This makes an API call
                buckets = buckets_response.get('buckets', [])
                logger.info(f"Fetched fresh bucket list. Count: {len(buckets)}")

            total_buckets_to_process = len(buckets)
            
            if progress_callback:
                progress_callback("SNAPSHOT_SETUP", {
                    "total_buckets": total_buckets_to_process,
                    "bucket_names": [b.get('bucketName') for b in buckets]
                })

            if total_buckets_to_process == 0:
                logger.info("No buckets found to process for B2 snapshot.")
                # No need to proceed further if no buckets
                # The SNAPSHOT_SETUP callback has already informed the progress system.
                # The final snapshot structure will be empty of bucket data.


            total_storage_bytes = 0
            total_storage_cost = 0
            total_download_bytes = 0
            total_download_cost = 0
            
            if total_buckets_to_process > 0: # Only run executor if there are buckets
                with concurrent.futures.ThreadPoolExecutor(max_workers=self.parallel_operations) as executor:
                    future_to_bucket_info = {}
                    for bucket in buckets:
                        # Pass progress_callback and account_info (if needed by helper, though not directly used by B2's _process_bucket_for_snapshot)
                        future = executor.submit(self._process_bucket_for_snapshot, bucket, prev_snapshot, progress_callback, account_info)
                        future_to_bucket_info[future] = bucket.get('bucketName')
                    
                    for future in concurrent.futures.as_completed(future_to_bucket_info):
                        bucket_name = future_to_bucket_info[future]
                        try:
                            bucket_info_result = future.result()
                            if bucket_info_result: # Check if not None (i.e., no error in _process_bucket_for_snapshot)
                                bucket_data_results.append(bucket_info_result)
                                total_storage_bytes += bucket_info_result['storage_bytes']
                                total_storage_cost += bucket_info_result['storage_cost']
                                total_download_bytes += bucket_info_result['download_bytes']
                                total_download_cost += bucket_info_result['download_cost']
                            # Progress for BUCKET_COMPLETE or BUCKET_ERROR is handled within _process_bucket_for_snapshot
                        except Exception as exc:
                            logger.error(f'Bucket {bucket_name} generated an exception in B2 API snapshot main loop: {exc}', exc_info=True)
                            if progress_callback: # Ensure error is reported if not caught by _process_bucket_for_snapshot
                                progress_callback("BUCKET_ERROR", {"bucket_name": bucket_name, "error": str(exc)})
                        # processed_buckets_count is implicitly handled by BUCKET_COMPLETE/BUCKET_ERROR callbacks

            api_calls_for_snapshot = self.api_calls_made - initial_api_calls
            estimated_api_cost = (api_calls_for_snapshot * (self.CLASS_A_TRANSACTION_COST + self.CLASS_B_TRANSACTION_COST) / 2)

            snapshot = {
                'timestamp': datetime.utcnow().isoformat(),
                'total_storage_bytes': total_storage_bytes,
                'total_storage_cost': total_storage_cost,
                'total_download_bytes': total_download_bytes,
                'total_download_cost': total_download_cost,
                'total_api_calls': api_calls_for_snapshot, 
                'total_api_cost': estimated_api_cost,
                'total_cost': total_storage_cost + total_download_cost + estimated_api_cost, 
                'buckets': bucket_data_results,
                'api_calls_made': api_calls_for_snapshot,
                'snapshot_type': 'b2_native' # Add type
            }
            
            self._save_cached_snapshot(snapshot)
            
            elapsed = time.time() - start_time
            logger.info(f"B2 API Snapshot completed in {elapsed:.2f}s with {api_calls_for_snapshot} API calls")
            
            # SNAPSHOT_COMPLETE/SNAPSHOT_ERROR is handled by the main app.py worker based on overall success/failure.
            # The progress_callback here is for individual bucket events.

            return snapshot
            
        except Exception as e:
            logger.error(f"Error taking B2 API snapshot: {str(e)}", exc_info=True)
            # The main app.py worker will handle setting the global error state.
            # If progress_callback was called with SNAPSHOT_SETUP, it knows about the buckets.
            # If the error is very early (e.g. listing buckets fails), SNAPSHOT_SETUP might not have all info.
            # The app.py worker's finally block should ensure the global state is cleaned up.
            raise # Re-raise to be caught by snapshot_worker in app.py

    def get_accurate_bucket_usage(self, bucket_id, bucket_name):
        """
        Get more accurate usage statistics for a specific bucket by iterating through all files.
        WARNING: This can be very slow and make many API calls for large buckets.
        """
        all_files = []
        start_filename = None
        start_file_id = None
        
        # Use a statistics-only approach to limit API calls
        response = self.list_file_versions(bucket_id, max_file_count=1000)
        files = response.get('files', [])
        all_files.extend(files)
        
        # If there are more files, we need to paginate
        while files and response.get('nextFileName'):
            start_filename = response.get('nextFileName')
            start_file_id = response.get('nextFileId')
            
            response = self.list_file_versions(bucket_id, start_filename, start_file_id, max_file_count=1000)
            files = response.get('files', [])
            
            if not files:
                logger.warning(f"Stopping pagination for {bucket_name}: Got nextFileName token but no files returned")
                break
                
            all_files.extend(files)
        
        total_size = sum(file.get('contentLength', 0) for file in all_files)
        file_count = len(all_files)
        
        # For largest files, sort and take top 10
        largest_files = sorted(all_files, key=lambda x: x.get('contentLength', 0), reverse=True)[:10]
        
        return {
            'total_size': total_size,
            'files_count': file_count,
            'largest_files': largest_files,
            'source': 'b2_api_full_scan'  # Indicate this was a full scan
        }

    # --- Snapshot caching helpers (simple, to avoid AttributeError) ---
    def _load_cached_snapshot(self):
        """Load the last saved snapshot from cache (returns None if not present)."""
        file_path = os.path.join(self.snapshot_cache_dir, 'last_snapshot.json')
        try:
            if os.path.exists(file_path):
                with open(file_path, 'r') as f:
                    return json.load(f)
        except Exception as e:
            logger.warning(f"Could not read cached snapshot: {e}")
        return None

    def _save_cached_snapshot(self, snapshot_data):
        """Persist latest snapshot to cache for quick diff on next run."""
        file_path = os.path.join(self.snapshot_cache_dir, 'last_snapshot.json')
        try:
            with open(file_path, 'w') as f:
                json.dump(snapshot_data, f)
        except Exception as e:
            logger.warning(f"Could not write cached snapshot: {e}")
