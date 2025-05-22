import os
import json
import logging
import threading # Import threading
from threading import Lock
import time
from datetime import datetime, timedelta
import copy

from flask import Flask, request, jsonify, render_template, redirect, url_for, flash, session, current_app
from flask_wtf.csrf import CSRFProtect # Removed unused validate_csrf
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user

# Add Flask-SocketIO for WebSockets
try:
    from flask_socketio import SocketIO, emit
    socketio_available = True
except ImportError:
    socketio_available = False
    print("WARNING: flask_socketio not installed. WebSocket functionality will be disabled.")
    print("To enable WebSockets, install with: pip install flask-socketio")

# Configure logging first so logger is available for imports
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# Config imports
import app.config as app_config
from app.config import (
    DATABASE_URI, SNAPSHOT_INTERVAL_HOURS, COST_CHANGE_THRESHOLD,
    DEBUG, SECRET_KEY, HOST, PORT,
    USE_S3_API, USE_ACCURATE_BUCKET_SIZE, PARALLEL_BUCKET_OPERATIONS,
    SNAPSHOT_CACHE_DIR
)

# Model and Client imports
from app.models.database import Database
from app.backblaze_api import BackblazeClient as NativeBackblazeClient

# Import S3 client and handle gracefully if it's not available
S3BackblazeClient = None
# Try multiple implementations of the S3 client in preference order
try:
    # Try the fixed implementation first
    from app.backblaze_s3_api_new import S3BackblazeClient
    logger.info("Successfully imported S3BackblazeClient from backblaze_s3_api_new")
except ImportError:
    try:
        # Next try the improved implementation
        from app.backblaze_s3_api_fixed import S3BackblazeClient
        logger.info("Successfully imported S3BackblazeClient from backblaze_s3_api_fixed")
    except ImportError:
        try:
            # Finally fall back to the original implementation
            from app.backblaze_s3_api import S3BackblazeClient
            logger.info("Successfully imported S3BackblazeClient from backblaze_s3_api")
        except ImportError as e:
            logger.error(f"Failed to import any version of S3BackblazeClient: {str(e)}")
            logger.warning("S3 functionality will be unavailable. Using only native API functionality.")
            S3BackblazeClient = None
        except Exception as e:
            logger.error(f"Unexpected error importing S3BackblazeClient: {str(e)}")
            logger.warning("S3 functionality will be unavailable due to errors. Using only native API functionality.")
            S3BackblazeClient = None
            S3BackblazeClient = None

# Credential function imports
from app.credentials import get_credentials, save_credentials, delete_credentials
try:
    from app.credentials import get_s3_credentials, save_s3_credentials, delete_s3_credentials # Import new S3 credential functions
except ImportError:
    logger.warning("get_s3_credentials, save_s3_credentials, or delete_s3_credentials not found in app.credentials.")
    def get_s3_credentials(): logger.error("Placeholder get_s3_credentials called!"); return None
    def save_s3_credentials(*args, **kwargs): logger.error("Placeholder save_s3_credentials called!"); return False
    def delete_s3_credentials(*args, **kwargs): logger.error("Placeholder delete_s3_credentials called!"); return False

# Other app module imports
from app.notifications import send_email_notification, format_cost_change_email
from app.scheduling import should_take_snapshot, cleanup_old_snapshots

# Initialize Flask app
app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config['DEBUG'] = DEBUG
app.config['PARALLEL_BUCKET_OPERATIONS'] = PARALLEL_BUCKET_OPERATIONS # From app.config

# Initialize SocketIO if available
if socketio_available:
    socketio = SocketIO(app, 
                       cors_allowed_origins="*", 
                       async_mode='threading',
                       ping_timeout=60,
                       ping_interval=25,
                       manage_session=False,  # Don't let Socket.IO manage sessions
                       logger=True,           # Enable Socket.IO internal logging
                       engineio_logger=True)  # Enable Engine.IO logging
    logger.info("WebSocket support enabled using Flask-SocketIO")
else:
    socketio = None
    logger.warning("WebSocket support disabled (flask_socketio not installed)")

# Initialize database (db and db_path are now global)
db_path = DATABASE_URI.replace('sqlite:///', '') # Define db_path globally
db = Database(db_path) # Define db globally

# Initialize CSRF Protection
csrf = CSRFProtect(app)

# Flask-Login setup
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Import routes from other modules AFTER app and extensions are initialized
from .schedule_routes import schedule_bp # Import the blueprint
app.register_blueprint(schedule_bp) # Register the blueprint

class User(UserMixin):
    def __init__(self, id_):
        self.id = id_

@login_manager.user_loader
def load_user(user_id):
    if session.get('_user_id') == user_id: # Basic check against session
        return User(user_id)
    return None

# Global variables for snapshot progress
snapshot_progress_global = {
    "active": False, "overall_percentage": 0, "status_message": "Not started",
    "error_message": None, "current_snapshot_type": None, "start_time": None,
    "end_time": None, "total_buckets": 0, "buckets_processed_count": 0,
    "current_processing_bucket_name": None, "buckets": [],
    "last_updated": None, "active_bucket": None
}
snapshot_progress_lock = Lock()

# WebSocket channels for broadcasting updates
ws_clients = set()

# Global client and scheduler variables
backblaze_client = None # For the global native B2 client, if needed outside snapshots
# last_snapshot_time = None # Review if this global is still used/needed
snapshot_thread = None # Global reference for the currently running snapshot_worker thread (manual or scheduled)
# stop_snapshot_thread = False # Review if this global is still used for scheduler control

# Callback for detailed progress
def update_snapshot_detailed_progress(event_type, data):
    """Update the detailed progress state of the snapshot process."""
    with snapshot_progress_lock:
        # Always update the timestamp for last activity
        snapshot_progress_global["last_updated"] = datetime.utcnow().isoformat()
        
        if event_type == "SNAPSHOT_SETUP":
            snapshot_progress_global["total_buckets"] = data.get("total_buckets", 0)
            snapshot_progress_global["buckets"] = []
            
            # Initialize each bucket in our progress tracking
            for bucket_name in data.get("bucket_names", []):
                snapshot_progress_global["buckets"].append({
                    "bucket_name": bucket_name,
                    "status": "pending",
                    "objects_processed_in_bucket": 0,
                    "last_object_key": None,
                    "error": None,
                    "pagination_info": {
                        "current_page": 0,
                        "total_pages": 0,
                        "files_processed": 0
                    }
                })
                
        elif event_type == "BUCKET_START":
            bucket_name = data.get("bucket_name")
            snapshot_progress_global["current_processing_bucket_name"] = bucket_name
            
            # Find and update the bucket status
            for bucket in snapshot_progress_global.get("buckets", []):
                if bucket["bucket_name"] == bucket_name:
                    bucket["status"] = "processing"
                    bucket["start_time"] = datetime.utcnow().isoformat()
                    break
                    
        elif event_type == "BUCKET_PROGRESS":
            bucket_name = data.get("bucket_name")
            objects_processed = data.get("objects_processed_in_bucket", 0)
            last_object_key = data.get("last_object_key", "N/A")
            pagination_info = data.get("pagination_info", {})
            
            # Find and update the bucket progress
            for bucket in snapshot_progress_global.get("buckets", []):
                if bucket["bucket_name"] == bucket_name:
                    bucket["status"] = "processing"
                    bucket["objects_processed_in_bucket"] = objects_processed
                    bucket["last_object_key"] = last_object_key
                    
                    # Update pagination info if available
                    if pagination_info:
                        bucket["pagination_info"] = {
                            "current_page": pagination_info.get("current_page", 0),
                            "total_pages": pagination_info.get("total_pages", 0),
                            "files_processed": pagination_info.get("files_processed", 0)
                        }
                    
                    # Set the active bucket for the UI
                    snapshot_progress_global["active_bucket"] = {
                        "bucket_name": bucket_name,
                        "objects_processed_in_bucket": objects_processed,
                        "last_object_key": last_object_key,
                        "pagination_info": pagination_info
                    }
                    break
                
        elif event_type == "BUCKET_COMPLETE":
            bucket_name = data.get("bucket_name")
            objects_processed = data.get("objects_processed_in_bucket", 0)
            pagination_info = data.get("pagination_info", {})
            
            # Find and update the bucket as completed
            for bucket in snapshot_progress_global.get("buckets", []):
                if bucket["bucket_name"] == bucket_name:
                    bucket["status"] = "completed"
                    bucket["objects_processed_in_bucket"] = objects_processed
                    bucket["end_time"] = datetime.utcnow().isoformat()
                    
                    # Update final pagination info
                    if pagination_info:
                        bucket["pagination_info"] = {
                            "current_page": pagination_info.get("current_page", 0),
                            "total_pages": pagination_info.get("total_pages", 0),
                            "files_processed": pagination_info.get("files_processed", 0)
                        }
                    
                    break
            
            # Update the count of processed buckets
            snapshot_progress_global["buckets_processed_count"] = sum(
                1 for b in snapshot_progress_global.get("buckets", []) 
                if b.get("status") in ["completed", "error"]
            )
            
            # Update the overall percentage
            if snapshot_progress_global["total_buckets"] > 0:
                snapshot_progress_global["overall_percentage"] = int(
                    (snapshot_progress_global["buckets_processed_count"] / snapshot_progress_global["total_buckets"]) * 100
                )
                
            # Clear the active bucket reference if we completed the current one
            if snapshot_progress_global.get("active_bucket", {}).get("bucket_name") == bucket_name:
                snapshot_progress_global["active_bucket"] = None
                
        elif event_type == "BUCKET_ERROR":
            bucket_name = data.get("bucket_name")
            error_message = data.get("error", "Unknown error")
            
            # Find and update the bucket with error
            for bucket in snapshot_progress_global.get("buckets", []):
                if bucket["bucket_name"] == bucket_name:
                    bucket["status"] = "error"
                    bucket["error"] = error_message
                    bucket["end_time"] = datetime.utcnow().isoformat()
                    break
                
            # Update processed count (errors also count as "processed")
            snapshot_progress_global["buckets_processed_count"] = sum(
                1 for b in snapshot_progress_global.get("buckets", []) 
                if b.get("status") in ["completed", "error"]
            )
            
            # Update overall percentage
            if snapshot_progress_global["total_buckets"] > 0:
                snapshot_progress_global["overall_percentage"] = int(
                    (snapshot_progress_global["buckets_processed_count"] / snapshot_progress_global["total_buckets"]) * 100
                )
                
            # Clear active bucket if it was the one with error
            if snapshot_progress_global.get("active_bucket", {}).get("bucket_name") == bucket_name:
                snapshot_progress_global["active_bucket"] = None
                
        elif event_type == "SNAPSHOT_COMPLETE":
            snapshot_progress_global["status_message"] = "Snapshot completed successfully"
            snapshot_progress_global["overall_percentage"] = 100
            snapshot_progress_global["end_time"] = datetime.utcnow().isoformat()
            snapshot_progress_global["active"] = False
            snapshot_progress_global["active_bucket"] = None
            snapshot_progress_global["snapshot_id"] = data.get("snapshot_id")
            
        elif event_type == "SNAPSHOT_ERROR":
            snapshot_progress_global["status_message"] = f"Snapshot failed: {data.get('error', 'Unknown error')}"
            snapshot_progress_global["error_message"] = data.get("error", "Unknown error")
            snapshot_progress_global["end_time"] = datetime.utcnow().isoformat()
            snapshot_progress_global["active"] = False
            snapshot_progress_global["active_bucket"] = None

        # Broadcast progress update via WebSocket if available
        if socketio:
            # Create a copy of the progress data to avoid race conditions
            progress_data = copy.deepcopy(snapshot_progress_global)
            
            # Log a condensed version of what we're emitting
            bucket_count = len(progress_data.get("buckets", []))
            active_bucket = progress_data.get("current_processing_bucket_name", "none")
            logger.info(f"Emitting snapshot_progress_update: {progress_data.get('overall_percentage')}% complete, {progress_data.get('buckets_processed_count')}/{progress_data.get('total_buckets')} buckets, active: {active_bucket}")
            
            socketio.emit('snapshot_progress_update', progress_data, namespace='/ws')


def initialize_backblaze_client(force_new_auth=False):
    global backblaze_client # This refers to the global native B2 client instance
    stored_creds = get_credentials()
    current_key_id = None

    if stored_creds and stored_creds.get('key_id'):
        current_key_id = stored_creds.get('key_id')
    else:
        env_key_id = os.environ.get('B2_APPLICATION_KEY_ID')
        if env_key_id:
            current_key_id = env_key_id
            # logger.info("Using B2_APPLICATION_KEY_ID from environment for global client initialization.")

    if not current_key_id:
        # logger.warning("No B2 API credentials for global client (env or stored). Global native client not initialized.")
        backblaze_client = None
        return False

    try:
        parallel_ops_config = current_app.config.get('PARALLEL_BUCKET_OPERATIONS', app_config.PARALLEL_BUCKET_OPERATIONS)
        # logger.info(f"Attempting to initialize global NativeBackblazeClient with parallel_operations = {parallel_ops_config}")

        if backblaze_client is None or force_new_auth or not isinstance(backblaze_client, NativeBackblazeClient):
            # logger.info(f"Creating new global NativeBackblazeClient instance. Force new auth: {force_new_auth}")
            # NativeBackblazeClient might take key_id, application_key in constructor or authorize later
            # Assuming it can be instantiated and then authorize if needed.
            backblaze_client = NativeBackblazeClient(parallel_operations=parallel_ops_config)
            if hasattr(backblaze_client, 'authorize'):
                if force_new_auth and hasattr(backblaze_client, 'clear_auth_cache'):
                    # logger.info("Forcing re-authorization for global native B2 client.")
                    backblaze_client.clear_auth_cache()
                backblaze_client.authorize() # Authorize B2 API
        # logger.info("Global NativeBackblazeClient initialization process completed.")
        return True
    except Exception as e:
        logger.error(f"Failed to initialize global NativeBackblazeClient: {str(e)}", exc_info=True)
        backblaze_client = None
        return False

def snapshot_worker(app_context, snapshot_type, snapshot_name, api_choice, clear_cache=False):
    with app_context.app_context(): # Use app_context
        current_app.logger.info(f"Snapshot worker started for type: {snapshot_type}, name: {snapshot_name}, API: {api_choice}, Clear Cache: {clear_cache}")
        
        client_instance = None 
        account_info = None 
        parallel_operations = current_app.config.get('PARALLEL_BUCKET_OPERATIONS', app_config.PARALLEL_BUCKET_OPERATIONS)
        
        # Resume logic - load previous failed snapshot data if this is a normal snapshot (not clearing cache)
        previous_snapshot_progress = None
        completed_buckets = {}
        if not clear_cache:
            try:
                # Load the previous snapshot progress data
                with snapshot_progress_lock:
                    if not snapshot_progress_global.get("active", False):
                        # Check if there's a previous failed snapshot
                        previous_snapshot_progress = copy.deepcopy(snapshot_progress_global)
                        if previous_snapshot_progress and previous_snapshot_progress.get("buckets"):
                            # Extract successfully completed buckets
                            for bucket in previous_snapshot_progress.get("buckets", []):
                                if bucket.get("status") == "completed":
                                    completed_buckets[bucket.get("bucket_name")] = True
                            
                            if completed_buckets:
                                current_app.logger.info(f"Found {len(completed_buckets)} completed buckets from previous snapshot. Will skip these when resuming.")
            except Exception as e:
                current_app.logger.warning(f"Error loading previous snapshot progress: {e}. Will not resume.")
                completed_buckets = {}

        if api_choice == 'b2':
            # Accept either stored credentials or environment variables
            creds = get_credentials()
            has_stored = creds and creds.get('key_id') and creds.get('application_key')
            has_env = os.environ.get('B2_APPLICATION_KEY_ID') and os.environ.get('B2_APPLICATION_KEY')
            if not (has_stored or has_env):
                current_app.logger.error("B2 credentials not found for snapshot worker (neither stored nor env vars).")
                with snapshot_progress_lock:
                    snapshot_progress_global.update({
                        "active": False, "status_message": "Error: B2 credentials not found.", 
                        "error_message": "B2 credentials not found.", "overall_percentage": 100,
                        "end_time": datetime.utcnow().isoformat()
                    })
                return
            
            try:
                client_instance = NativeBackblazeClient(parallel_operations=parallel_operations)
                
                # Clear cache if requested
                if clear_cache:
                    if hasattr(client_instance, 'clear_auth_cache'):
                        current_app.logger.info("Clearing B2 authentication cache as requested")
                        client_instance.clear_auth_cache()
                    
                    # Also clear the object metadata cache if directory exists
                    if hasattr(client_instance, 'object_cache_dir_abs') and client_instance.object_cache_dir_abs:
                        try:
                            import shutil
                            if os.path.exists(client_instance.object_cache_dir_abs):
                                current_app.logger.info(f"Clearing B2 object metadata cache at {client_instance.object_cache_dir_abs}")
                                for file in os.listdir(client_instance.object_cache_dir_abs):
                                    if file.startswith('b2_bucket_usage_'):
                                        file_path = os.path.join(client_instance.object_cache_dir_abs, file)
                                        os.remove(file_path)
                                        current_app.logger.debug(f"Removed cache file: {file_path}")
                        except Exception as cache_e:
                            current_app.logger.warning(f"Error clearing B2 object cache: {cache_e}")
                
                # Get account info
                if hasattr(client_instance, 'get_account_info'):
                     account_info = client_instance.get_account_info()
                     if account_info: # Log account ID if available
                         current_app.logger.info(f"Native B2 Client initialized for account: {account_info.get('accountId')}")
                     else: # This case means get_account_info failed or returned None
                         current_app.logger.warning("Native B2 client: get_account_info() did not return account information. Snapshot may lack account ID.")
                         # Proceed without account_info, take_snapshot should handle it being None
                else:
                    current_app.logger.warning("NativeBackblazeClient instance does not have get_account_info method.")
                    account_info = {} 
            except Exception as e:
                current_app.logger.error(f"Failed to initialize or get B2 account info: {e}", exc_info=True)
                with snapshot_progress_lock:
                     snapshot_progress_global.update({
                        "active": False, "status_message": f"Error: Failed to init/auth B2 client: {e}", 
                        "error_message": str(e), "overall_percentage": 100,
                        "end_time": datetime.utcnow().isoformat()
                    })
                return

        elif api_choice == 's3':
            if S3BackblazeClient is None: 
                current_app.logger.error("S3BackblazeClient class is not available (import failed). Cannot create S3 snapshot.")
                with snapshot_progress_lock: 
                    snapshot_progress_global.update({"active": False, "status_message": "Error: S3 client library not available.", "error_message": "S3 client library import failed.", "overall_percentage": 100, "end_time": datetime.utcnow().isoformat()})
                return

            s3_creds = get_s3_credentials() # Use the new function
            # Fallback to environment variables if not stored
            if (not s3_creds or not s3_creds.get('aws_access_key_id') or
                not s3_creds.get('aws_secret_access_key') or not s3_creds.get('endpoint_url')):
                env_key = os.environ.get('AWS_ACCESS_KEY_ID')
                env_secret = os.environ.get('AWS_SECRET_ACCESS_KEY')
                env_endpoint = os.environ.get('B2_S3_ENDPOINT_URL')
                env_region = os.environ.get('AWS_REGION') or os.environ.get('B2_S3_REGION_NAME')
                if env_key and env_secret and env_endpoint:
                    s3_creds = {
                        'aws_access_key_id': env_key,
                        'aws_secret_access_key': env_secret,
                        'endpoint_url': env_endpoint,
                        'region_name': env_region
                    }
                else:
                    current_app.logger.error("S3 credentials (aws_access_key_id, aws_secret_access_key, or endpoint_url) not found for snapshot worker.")
                    with snapshot_progress_lock:
                        snapshot_progress_global.update({
                            "active": False, "status_message": "Error: S3 credentials not found.", 
                            "error_message": "S3 credentials (key, secret, or endpoint) not found.", "overall_percentage": 100,
                            "end_time": datetime.utcnow().isoformat()
                        })
                    return
            
            try:
                # Instantiate S3BackblazeClient with S3-specific credentials
                client_instance = S3BackblazeClient(
                    aws_access_key_id=s3_creds['aws_access_key_id'],
                    aws_secret_access_key=s3_creds['aws_secret_access_key'],
                    endpoint_url=s3_creds['endpoint_url'],
                    region_name=s3_creds.get('region_name'), # Optional
                    parallel_operations=parallel_operations
                )
                
                # Clear cache if requested
                if clear_cache:
                    # Clear auth cache if the method exists
                    if hasattr(client_instance, 'clear_auth_cache'):
                        current_app.logger.info("Clearing S3 authentication cache as requested")
                        client_instance.clear_auth_cache()
                    
                    # Also clear object metadata cache if available
                    if hasattr(client_instance, 'object_cache_dir_abs') and client_instance.object_cache_dir_abs:
                        try:
                            if os.path.exists(client_instance.object_cache_dir_abs):
                                current_app.logger.info(f"Clearing S3 object metadata cache at {client_instance.object_cache_dir_abs}")
                                for file in os.listdir(client_instance.object_cache_dir_abs):
                                    if file.startswith('s3_bucket_usage_'):
                                        file_path = os.path.join(client_instance.object_cache_dir_abs, file)
                                        os.remove(file_path)
                                        current_app.logger.debug(f"Removed S3 cache file: {file_path}")
                        except Exception as cache_e:
                            current_app.logger.warning(f"Error clearing S3 object cache: {cache_e}")
                
                current_app.logger.info(f"S3BackblazeClient initialized with Key ID ending ...{s3_creds['aws_access_key_id'][-4:] if len(s3_creds['aws_access_key_id']) > 3 else s3_creds['aws_access_key_id']} and endpoint {s3_creds['endpoint_url']}.")
            except Exception as e:
                current_app.logger.error(f"Failed to initialize S3BackblazeClient: {e}", exc_info=True)
                # client_instance will remain None, handled below
        
        if not client_instance:
            current_app.logger.error(f"Failed to initialize API client for snapshot worker (API: {api_choice}).")
            with snapshot_progress_lock:
                 snapshot_progress_global.update({
                    "active": False, "status_message": "Error: Failed to initialize API client.", 
                    "error_message": f"Client initialization failed for {api_choice.upper()} API.", "overall_percentage": 100,
                    "end_time": datetime.utcnow().isoformat()
                })
            return

        # Store the client instance in the app context so it can be accessed for dynamic updates
        current_app.active_snapshot_client = client_instance
        
        # Pass the completed buckets to the client if it supports skipping them
        if completed_buckets and hasattr(client_instance, 'set_completed_buckets'):
            client_instance.set_completed_buckets(completed_buckets)
            current_app.logger.info(f"Passed {len(completed_buckets)} completed buckets to the client for skipping")

        with snapshot_progress_lock:
            # Only clear the progress data if not resuming, or if clearing cache
            if clear_cache or not previous_snapshot_progress or not completed_buckets:
                snapshot_progress_global.clear()
                
            snapshot_progress_global.update({
                "active": True, 
                "overall_percentage": 0, 
                "status_message": "Initializing snapshot..." if not completed_buckets else f"Resuming snapshot (skipping {len(completed_buckets)} completed buckets)",
                "error_message": None, 
                "current_snapshot_type": snapshot_type,
                "start_time": datetime.utcnow().isoformat(), 
                "end_time": None,
                "total_buckets": 0, 
                "buckets_processed_count": len(completed_buckets) if completed_buckets else 0,
                "current_processing_bucket_name": None, 
                "buckets": [],
                "parallel_operations": parallel_operations,
                "is_resumed": bool(completed_buckets)
            })
        
        try:
            current_app.logger.info(f"Calling {api_choice.upper()} client_instance.take_snapshot for '{snapshot_name}'")
            
            # Add the completed_buckets parameter if resuming
            snapshot_params = {
                "snapshot_name": snapshot_name,
                "progress_callback": update_snapshot_detailed_progress,
                "account_info": account_info
            }
            
            if completed_buckets:
                snapshot_params["completed_buckets"] = completed_buckets
                
            snapshot_results = client_instance.take_snapshot(**snapshot_params)
            
            if snapshot_results and isinstance(snapshot_results, dict) and 'total_storage_bytes' in snapshot_results:
                # Add snapshot_name and api_type to the results if not already there, for db.save_snapshot
                snapshot_results.setdefault('snapshot_name', snapshot_name)
                snapshot_results.setdefault('api_type', api_choice)
                snapshot_results.setdefault('account_id', account_info.get('accountId') if account_info else None)
                
                # Add information about resumed operation if applicable
                if completed_buckets:
                    snapshot_results.setdefault('resumed', True)
                    snapshot_results.setdefault('resumed_buckets_count', len(completed_buckets))

                db.save_snapshot(snapshot_results) 
                current_app.logger.info(f"Snapshot '{snapshot_name}' data stored in database.")
            else:
                current_app.logger.error(f"Snapshot '{snapshot_name}' did not return valid/complete results for saving. Results: {snapshot_results}")
                raise Exception("Snapshot client returned invalid or incomplete data.")

            with snapshot_progress_lock:
                snapshot_progress_global["active"] = False
                snapshot_progress_global["end_time"] = datetime.utcnow().isoformat()
                snapshot_progress_global["overall_percentage"] = 100
                snapshot_progress_global["current_processing_bucket_name"] = None
                final_status_message = "Snapshot completed successfully."
                if any(b.get('status') == 'error' for b in snapshot_progress_global.get('buckets', [])):
                    final_status_message = "Snapshot completed with errors."
                elif not snapshot_progress_global.get('buckets') and snapshot_progress_global.get('total_buckets',0) == 0 :
                     if "No buckets found" not in snapshot_progress_global.get("status_message",""):
                        final_status_message = "Snapshot completed: No buckets processed."
                        
                # Add resume information to the status message if applicable
                if completed_buckets:
                    final_status_message = f"{final_status_message} (Resumed from previous run, skipped {len(completed_buckets)} completed buckets)"
                    
                snapshot_progress_global["status_message"] = final_status_message
                current_app.logger.info(f"Snapshot worker finished for '{snapshot_name}'. Final status: {final_status_message}")

        except Exception as e:
            current_app.logger.error(f"Snapshot worker failed for '{snapshot_name}': {e}", exc_info=True)
            with snapshot_progress_lock:
                snapshot_progress_global["active"] = False
                snapshot_progress_global["status_message"] = f"Snapshot failed: {e}"
                snapshot_progress_global["error_message"] = str(e)
                snapshot_progress_global["end_time"] = datetime.utcnow().isoformat()
                if not (snapshot_progress_global.get("overall_percentage", 0) == 100 and not snapshot_progress_global.get("active")):
                     if snapshot_progress_global.get("total_buckets",0) == 0 and snapshot_progress_global.get("buckets_processed_count",0) == 0:
                        snapshot_progress_global["overall_percentage"] = 0 # Reset percentage if failed early
                snapshot_progress_global["current_processing_bucket_name"] = None
        finally:
            with snapshot_progress_lock:
                if snapshot_progress_global.get("active", False): 
                    snapshot_progress_global["active"] = False
                    current_app.logger.warning("Snapshot worker: 'active' was still true in finally block, setting to false.")
                if snapshot_progress_global.get("overall_percentage",0) != 100 and not snapshot_progress_global.get("active", False) :
                    snapshot_progress_global["overall_percentage"] = 100
            global snapshot_thread # Clear the global thread var if this was the one
            if snapshot_thread and snapshot_thread == threading.current_thread():
                snapshot_thread = None


@app.route('/')
# @login_required # Consider if home page needs login
def index():
    try:
        snapshots = db.get_latest_snapshots(limit=30)
        if not snapshots:
            # If no B2/S3 creds are set at all, this might be better            # For now, setup.html if no snapshots exist.
            b2_creds = get_credentials()
            s3_creds_info = get_s3_credentials() 
            if not (b2_creds and b2_creds.get('key_id')) and not (s3_creds_info and s3_creds_info.get('aws_access_key_id')):
                 return render_template('setup.html', page_title="Initial Setup Required")
            return render_template('index.html', page_title="Dashboard", no_snapshots_yet=True) # Special state for index if no snapshots
            
        latest_snapshot = snapshots[0]
        latest_snapshot_id = latest_snapshot['id']
        # The get_snapshot_by_id method in database.py already loads buckets
        detailed_snapshot = db.get_snapshot_by_id(latest_snapshot_id)
        
        cost_trends = db.get_cost_trends(days=30)
        changes = db.detect_significant_changes(app_config.COST_CHANGE_THRESHOLD) # Use app_config
        return render_template(
            'index.html',
            page_title="Dashboard",
            snapshot=detailed_snapshot,
            snapshots=snapshots, # for a dropdown or quick list
            cost_trends=cost_trends,
            significant_changes=changes,
            latest_snapshot_id=latest_snapshot_id
        )
    except Exception as e:
        logger.error(f"Error in index route: {str(e)}", exc_info=True)
        return render_template('error.html', error=str(e))

@app.route('/snapshots/<int:snapshot_id>')
@login_required
def view_snapshot(snapshot_id):
    try:
        snapshot = db.get_snapshot_by_id(snapshot_id)
        if not snapshot:
            flash('Snapshot not found', 'error')
            return redirect(url_for('index'))
        # For a consistent layout, maybe provide all snapshots for a sidebar/nav
        snapshots_list = db.get_latest_snapshots(limit=30) 
        return render_template(
            'snapshot.html', # Assuming you have a template for single snapshot view
            page_title=f"Snapshot Details - {snapshot.get('timestamp', snapshot_id)}",
            snapshot=snapshot,
            snapshots_list=snapshots_list
        )
    except Exception as e:
        logger.error(f"Error viewing snapshot {snapshot_id}: {str(e)}", exc_info=True)
        return render_template('error.html', error=str(e))

@app.route('/snapshots/new', methods=['POST'])
@login_required
def new_snapshot():
    global snapshot_thread # Manage the single global snapshot thread

    def _determine_api_choice():
        """Decide whether to use S3 or native B2 based on available credentials and config."""
        # Prefer S3 only when the feature flag is on AND credentials are available
        if app_config.USE_S3_API:
            # Check env-vars first
            has_env_s3 = all(
                [os.environ.get('AWS_ACCESS_KEY_ID'), os.environ.get('AWS_SECRET_ACCESS_KEY'), os.environ.get('B2_S3_ENDPOINT_URL')]
            )
            if has_env_s3:
                return 's3'

            # Fall back to stored creds on disk
            if get_s3_credentials():
                return 's3'

        # Default to native B2 when S3 is disabled or creds missing
        return 'b2'

    try:
        logger.info("Manual snapshot creation initiated by user.")
        
        # Check if clear_cache is set
        clear_cache = request.form.get('clear_cache') == 'true'
        
        with snapshot_progress_lock:
            if snapshot_progress_global.get("active", False) or (snapshot_thread and snapshot_thread.is_alive()):
                flash('A snapshot is already in progress. Please wait for it to complete.', 'warning')
                return redirect(url_for('snapshot_status_detail')) 

            snapshot_progress_global.clear()
            snapshot_progress_global.update({
                "active": True, "overall_percentage": 0, "status_message": "Initializing manual snapshot...",
                "error_message": None, "current_snapshot_type": "manual",
                "start_time": datetime.utcnow().isoformat(), "end_time": None,
                "total_buckets": 0, "buckets_processed_count": 0,
                "current_processing_bucket_name": None, "buckets": []
            })
        
        api_choice = _determine_api_choice()
        snapshot_name = f"Manual Snapshot - {datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"
        app_context_obj = current_app._get_current_object()

        logger.info(f"Starting manual snapshot thread: Name='{snapshot_name}', API='{api_choice}', Clear Cache={clear_cache}")
        thread = threading.Thread(target=snapshot_worker, args=(app_context_obj, "manual", snapshot_name, api_choice, clear_cache))
        thread.daemon = True 
        thread.start()
        snapshot_thread = thread # Store reference to the running thread

        if clear_cache:
            flash(f'New manual snapshot with CLEARED CACHE initiated ({api_choice.upper()}). View progress on the status page.', 'success')
        else:
            flash(f'New manual snapshot process initiated ({api_choice.upper()}). View progress on the status page.', 'success')
        return redirect(url_for('snapshot_status_detail'))
        
    except Exception as e:
        logger.error(f"Error initiating new manual snapshot: {str(e)}", exc_info=True)
        with snapshot_progress_lock:
            snapshot_progress_global.update({
                "active": False, "status_message": f"Error: {str(e)}", "error_message": str(e),
                "overall_percentage": 0, "end_time": datetime.utcnow().isoformat()
            })
        flash(f'Error initiating snapshot: {str(e)}', 'danger')
        return redirect(url_for('index'))

@app.route('/snapshot/progress') 
# @login_required # Public progress endpoint might be fine, or add login if sensitive
def get_snapshot_progress_route():
    with snapshot_progress_lock:
        # Make a copy to prevent race conditions
        progress_data = copy.deepcopy(snapshot_progress_global)
        
        # Ensure minimum data structure for clients
        if 'active' not in progress_data:
            progress_data['active'] = False
        if 'overall_percentage' not in progress_data:
            progress_data['overall_percentage'] = 0
        if 'status_message' not in progress_data:
            progress_data['status_message'] = 'No active snapshot'
        if 'buckets' not in progress_data:
            progress_data['buckets'] = []
        if 'buckets_processed_count' not in progress_data:
            progress_data['buckets_processed_count'] = 0
        if 'total_buckets' not in progress_data:
            progress_data['total_buckets'] = 0
            
        logger.debug(f"Returning snapshot progress data with {len(progress_data.get('buckets', []))} buckets")
        return jsonify(progress_data)

@app.route('/snapshot/kill', methods=['POST'])
@login_required
def kill_snapshot_route():
    """API endpoint to kill a running snapshot process"""
    global snapshot_thread, stop_snapshot_thread
    
    try:
        # Set the stop flag to signal the worker thread to exit
        stop_snapshot_thread = True
        
        # Update the snapshot progress to indicate it's being terminated
        with snapshot_progress_lock:
            snapshot_progress_global.update({
                "active": False,
                "status_message": "Snapshot terminated by user",
                "error_message": "Snapshot process was manually killed",
                "end_time": datetime.utcnow().isoformat()
            })
            
        # If socket.io is available, emit an update
        if socketio:
            socketio.emit('snapshot_progress_update', snapshot_progress_global, namespace='/ws')
        
        # Check if thread exists and is alive
        if snapshot_thread and snapshot_thread.is_alive():
            logger.info("Attempting to join snapshot thread...")
            # We don't want to block indefinitely, so use a timeout
            snapshot_thread.join(timeout=5)
            
            # Check if it's still alive after timeout
            if snapshot_thread.is_alive():
                logger.warning("Snapshot thread did not stop gracefully within timeout.")
                # Note: In Python we can't forcefully terminate a thread
                # The thread should check the stop_snapshot_thread flag regularly
            else:
                logger.info("Snapshot thread terminated successfully.")
                snapshot_thread = None
        else:
            logger.info("No active snapshot thread to terminate.")
        
        return jsonify({
            "success": True,
            "message": "Snapshot process termination signal sent."
        })
        
    except Exception as e:
        logger.error(f"Error killing snapshot: {str(e)}", exc_info=True)
        return jsonify({
            "success": False,
            "message": f"Error: {str(e)}"
        }), 500

@app.route('/snapshot/status')
@login_required
def snapshot_status_detail():
    return render_template('snapshot_status_detail.html', page_title="Snapshot Status")

@app.route('/api/snapshots', methods=['GET'])
def api_list_snapshots():
    """API endpoint to list snapshots"""
    try:
        limit = int(request.args.get('limit', 30))
        snapshots = db.get_latest_snapshots(limit=limit)
        return jsonify({'snapshots': snapshots})
    except Exception as e:
        logger.error(f"API error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/snapshots/<int:snapshot_id>', methods=['GET'])
def api_get_snapshot(snapshot_id):
    """API endpoint to get a specific snapshot"""
    try:
        snapshot = db.get_snapshot_by_id(snapshot_id)
        if not snapshot:
            return jsonify({'error': 'Snapshot not found'}), 404
        return jsonify({'snapshot': snapshot})
    except Exception as e:
        logger.error(f"API error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/snapshots/latest', methods=['GET'])
def api_latest_snapshot():
    """API endpoint to get the latest snapshot"""
    try:
        snapshots = db.get_latest_snapshots(limit=1)
        if not snapshots:
            return jsonify({'error': 'No snapshots available'}), 404
        latest_snapshot_id = snapshots[0]['id']
        snapshot = db.get_snapshot_by_id(latest_snapshot_id)
        return jsonify({'snapshot': snapshot})
    except Exception as e:
        logger.error(f"API error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/trends', methods=['GET'])
def api_cost_trends():
    """API endpoint to get cost trends"""
    try:
        days = int(request.args.get('days', 30))
        trends = db.get_cost_trends(days=days)
        return jsonify({'trends': trends})
    except Exception as e:
        logger.error(f"API error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/changes', methods=['GET'])
def api_significant_changes():
    """API endpoint to get significant changes"""
    try:
        threshold = float(request.args.get('threshold', COST_CHANGE_THRESHOLD))
        changes = db.detect_significant_changes(threshold)
        if not changes:
            return jsonify({'message': 'No significant changes detected'})
        return jsonify({'changes': changes})
    except Exception as e:
        logger.error(f"API error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/health')
def health_check():
    """Health check endpoint for container monitoring"""
    try:
        db_ok = False
        with db._get_connection() as conn: # Uses global db
            cursor = conn.cursor()
            cursor.execute('SELECT 1')
            db_ok = True
            
        # Check global native B2 client status (if it's supposed to be initialized)
        # This check is for the global `backblaze_client`, not necessarily S3 or worker clients.
        global_b2_client_status = backblaze_client is not None and (hasattr(backblaze_client, 'is_authorized') and backblaze_client.is_authorized())
        
        return jsonify({
            'status': 'healthy', 'timestamp': datetime.now().isoformat(),
            'database': db_ok,
            'global_b2_client_initialized_and_authorized': global_b2_client_status
        })
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        return jsonify({
            'status': 'unhealthy', 'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500

# --- Scheduler ---
# The old scheduler logic is problematic with the new snapshot_worker signature.
# A robust scheduler (APScheduler, cron) is recommended for production.
# For now, manual snapshots are the primary focus.
# `start_scheduler` and `stop_scheduler` are simplified/commented out.

def start_scheduler():
    logger.info("start_scheduler called. Automatic scheduled snapshots are currently disabled/need rework for new worker.")
    # global snapshot_thread, stop_snapshot_thread
    # if snapshot_thread is None or not snapshot_thread.is_alive():
    #     stop_snapshot_thread = False
    #     # To make this work, a wrapper function is needed for the target,
    #     # which then calls snapshot_worker with correct app_context, type, name, api_choice.
    #     # Example:
    #     # def scheduled_snapshot_job():
    #     #     with app.app_context(): # Create an app context for the job
    #     #         app_for_thread = current_app._get_current_object()
    #     #         api_choice = 's3' if app_config.USE_S3_API else 'b2'
    #     #         snap_name = f"Scheduled-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"
    #     #         snapshot_worker(app_for_thread, "scheduled", snap_name, api_choice)
    #     #     #
    #     # snapshot_thread = threading.Thread(target=scheduled_snapshot_job)
    #     # snapshot_thread.daemon = True
    #     # snapshot_thread.start()
    #     # logger.info("Basic snapshot scheduler thread started (if implemented).")

def stop_scheduler():
    logger.info("stop_scheduler called.")
    # global stop_snapshot_thread
    # stop_snapshot_thread = True
    # if snapshot_thread and snapshot_thread.is_alive():
    #     logger.info("Attempting to join snapshot scheduler thread...")
    #     snapshot_thread.join(timeout=10) # Wait for it to finish
    #     if snapshot_thread.is_alive():
    #         logger.warning("Snapshot scheduler thread did not stop in time.")
    # snapshot_thread = None


@app.before_first_request
def before_first_request_setup(): # Renamed to avoid conflict if Flask has internal 'before_first_request'
    initialize_backblaze_client() # Initialize global native B2 client if creds exist
    # start_scheduler() # Automatic scheduler start disabled for now

@app.teardown_appcontext
def teardown_appcontext(exception=None):
    if exception:
        logger.error(f"Application context teardown with error: {str(exception)}")

@app.route('/snapshots')
@login_required
def snapshots():
    """Redirect to the snapshots route in the schedule blueprint"""
    return redirect(url_for('schedule_routes.snapshots'))

def run_app():
    try:
        # db_path is global, os.makedirs uses it
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        # initialize_backblaze_client() # Called by before_first_request_setup
        # start_scheduler() # Scheduler start disabled for now
        
        if socketio:
            logger.info(f"Starting Flask app with WebSocket support on {HOST}:{PORT}")
            # Set debug=False for production to avoid socket reconnection issues
            socketio.run(app, host=HOST, port=PORT, debug=DEBUG, 
                        allow_unsafe_werkzeug=True,
                        log_output=True,
                        cors_allowed_origins="*")
        else:
            logger.info(f"Starting Flask app (without WebSocket support) on {HOST}:{PORT}")
            app.run(host=HOST, port=PORT, debug=DEBUG)
    except Exception as e:
        logger.error(f"Error starting application: {str(e)}", exc_info=True)
    finally:
        stop_scheduler() # Ensure scheduler is stopped if it was started

# --- Dummy Login/Logout Routes ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        user_id_from_form = request.form.get('username', 'testuser') 
        user = User(user_id_from_form)
        login_user(user) 
        session['_user_id'] = user.id 
        flash(f'Logged in as {user.id} (simulated).', 'success')
        next_page = request.args.get('next')
        return redirect(next_page or url_for('index'))
    return render_template('login.html', page_title="Login") # Assume login.html exists or use inline HTML

@app.route('/logout')
@login_required
def logout():
    logout_user() 
    session.pop('_user_id', None) 
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

# --- Settings Routes ---
# (Make sure these use global `db` and `app_config` where appropriate)
# Example: /settings/api
@app.route('/settings/api', methods=['GET', 'POST'])
@login_required 
def api_settings():
    has_env_b2_credentials = bool(os.environ.get('B2_APPLICATION_KEY_ID') and os.environ.get('B2_APPLICATION_KEY'))
    b2_credentials_stored = get_credentials() if not has_env_b2_credentials else None

    # S3 Credentials
    has_env_s3_credentials = bool(
        os.environ.get('AWS_ACCESS_KEY_ID') and 
        os.environ.get('AWS_SECRET_ACCESS_KEY') and
        os.environ.get('B2_S3_ENDPOINT_URL') # Assuming B2_S3_ENDPOINT_URL for env config of S3 endpoint
    )
    s3_credentials_stored = get_s3_credentials() if not has_env_s3_credentials else None

    if request.method == 'POST':
        form_type = request.form.get('form_type')

        if form_type == 'b2_native_creds':
            if has_env_b2_credentials:
                flash('Cannot save B2 native credentials when environment variables (B2_APPLICATION_KEY_ID/B2_APPLICATION_KEY) are set.', 'warning')
            else:
                key_id = request.form.get('b2_key_id')
                application_key = request.form.get('b2_application_key')
                if key_id and application_key:
                    if save_credentials(key_id, application_key): 
                        flash('B2 API credentials saved. Re-initializing global client.', 'success')
                        if not initialize_backblaze_client(force_new_auth=True): 
                            flash('Global Native B2 client re-initialization failed. Check logs.', 'danger')
                    else:
                        flash('Failed to save B2 API credentials.', 'danger')
                else:
                    flash('Both B2 Key ID and B2 Application Key are required.', 'warning')
        
        elif form_type == 's3_creds':
            if has_env_s3_credentials:
                flash('Cannot save S3 credentials when environment variables (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, B2_S3_ENDPOINT_URL) are set.', 'warning')
            else:
                s3_key_id = request.form.get('s3_key_id')
                s3_secret_key = request.form.get('s3_secret_key')
                s3_endpoint_url = request.form.get('s3_endpoint_url')
                s3_region_name = request.form.get('s3_region_name') # Optional

                if s3_key_id and s3_secret_key and s3_endpoint_url:
                    if save_s3_credentials(s3_key_id, s3_secret_key, s3_endpoint_url, s3_region_name if s3_region_name else None):
                        flash('S3 API credentials saved. S3 client will use these when selected.', 'success')
                        # Optionally, re-initialize S3 client if there's a global one, or notify user.
                        # For now, S3 client is instantiated per snapshot worker.
                    else:
                        flash('Failed to save S3 API credentials.', 'danger')
                else:
                    flash('S3 Key ID, S3 Secret Key, and S3 Endpoint URL are required.', 'warning')

        return redirect(url_for('api_settings'))

    current_parallel_ops = current_app.config.get('PARALLEL_BUCKET_OPERATIONS', app_config.PARALLEL_BUCKET_OPERATIONS)
    return render_template(
        'api_settings.html',
        page_title="API & Performance Settings",
        b2_credentials_stored=b2_credentials_stored,
        has_env_b2_credentials=has_env_b2_credentials,
        s3_credentials_stored=s3_credentials_stored, # Pass to template
        has_env_s3_credentials=has_env_s3_credentials, # Pass to template
        parallel_operations=current_parallel_ops,
        use_s3_api_globally=app_config.USE_S3_API
    )

@app.route('/settings/api/performance', methods=['POST'])
@login_required
def save_performance_settings():
    settings_file_path = os.path.join(app.instance_path, 'performance_settings.json')
    try:
        os.makedirs(app.instance_path, exist_ok=True)
    except OSError as e:
        logger.error(f"Could not create instance path {app.instance_path}: {e}")
        flash('Error saving settings: Could not create instance path.', 'danger')
        return redirect(url_for('api_settings'))

    parallel_ops_str = request.form.get('parallel_operations')
    if parallel_ops_str:
        try:
            parallel_ops_int = int(parallel_ops_str)
            if not (1 <= parallel_ops_int <= 100): # Increased max from 32 to 100
                flash('Parallel operations must be between 1 and 100.', 'danger')
            else:
                with open(settings_file_path, 'w') as f:
                    json.dump({'parallel_operations': parallel_ops_int}, f)
                current_app.config['PARALLEL_BUCKET_OPERATIONS'] = parallel_ops_int
                
                # Update active client's parallel_operations if a snapshot is running
                global snapshot_thread
                if snapshot_thread and snapshot_thread.is_alive() and hasattr(current_app, 'active_snapshot_client'):
                    active_client = getattr(current_app, 'active_snapshot_client', None)
                    if active_client and hasattr(active_client, 'parallel_operations'):
                        old_value = active_client.parallel_operations
                        active_client.parallel_operations = parallel_ops_int
                        logger.info(f"Updated active snapshot client's parallel operations from {old_value} to {parallel_ops_int}")
                        flash(f'Performance settings saved and applied to the active snapshot process.', 'success')
                    else:
                        flash('Performance settings saved. Will apply to future snapshot operations.', 'success')
                else:
                    flash('Performance settings saved. Will apply to future snapshot operations.', 'success')
        except (IOError, ValueError) as e:
            logger.error(f"Error saving performance settings: {e}")
            flash(f'Error saving performance settings: {e}', 'danger')
    else:
        flash('Parallel operations value not provided.', 'warning')
    return redirect(url_for('api_settings'))

@app.route('/settings/api/parallel_operations', methods=['POST'])
@login_required
def update_parallel_operations():
    """API endpoint to update parallel operations in real-time"""
    try:
        data = request.get_json()
        if not data or 'parallel_operations' not in data:
            return jsonify({
                'success': False,
                'message': 'Missing parallel_operations parameter'
            }), 400
            
        parallel_ops = int(data['parallel_operations'])
        if not (1 <= parallel_ops <= 100):
            return jsonify({
                'success': False,
                'message': 'Parallel operations must be between 1 and 100'
            }), 400
        
        # Update the application config
        current_app.config['PARALLEL_BUCKET_OPERATIONS'] = parallel_ops
        
        # Also save to settings file for persistence
        settings_file_path = os.path.join(app.instance_path, 'performance_settings.json')
        os.makedirs(app.instance_path, exist_ok=True)
        with open(settings_file_path, 'w') as f:
            json.dump({'parallel_operations': parallel_ops}, f)
        
        # Update active client's parallel_operations if a snapshot is running
        global snapshot_thread
        if snapshot_thread and snapshot_thread.is_alive():
            active_client = getattr(current_app, 'active_snapshot_client', None)
            if active_client and hasattr(active_client, 'parallel_operations'):
                old_value = active_client.parallel_operations
                active_client.parallel_operations = parallel_ops
                logger.info(f"Dynamically updated active snapshot client's parallel operations from {old_value} to {parallel_ops}")
                
                # Update the snapshot progress global with this information
                with snapshot_progress_lock:
                    snapshot_progress_global["parallel_operations"] = parallel_ops
                    snapshot_progress_global["status_message"] = f"Processing buckets (parallel operations updated to {parallel_ops})"
                    
                    # Broadcast update via WebSocket if available
                    if socketio:
                        progress_data = copy.deepcopy(snapshot_progress_global)
                        socketio.emit('snapshot_progress_update', progress_data, namespace='/ws')
                
                return jsonify({
                    'success': True,
                    'message': f'Parallel operations updated from {old_value} to {parallel_ops} and applied to active snapshot',
                    'applied_to_active_snapshot': True
                })
            else:
                return jsonify({
                    'success': True,
                    'message': 'Parallel operations updated but could not be applied to active snapshot',
                    'applied_to_active_snapshot': False
                })
        else:
            return jsonify({
                'success': True,
                'message': 'Parallel operations updated (no active snapshot)',
                'applied_to_active_snapshot': False
            })
            
    except ValueError as e:
        return jsonify({
            'success': False,
            'message': f'Invalid value: {str(e)}'
        }), 400
    except Exception as e:
        logger.error(f"Error updating parallel operations: {e}")
        return jsonify({
            'success': False,
            'message': f'Error: {str(e)}'
        }), 500

@app.route('/settings/api/delete', methods=['POST']) 
@login_required
def delete_api_credentials(): 
    credential_type_to_delete = request.form.get('credential_type')

    if credential_type_to_delete == 'b2_native':
        if delete_credentials(): 
            flash('Stored B2 API credentials deleted. Re-initializing global client.', 'success')
            if not initialize_backblaze_client(force_new_auth=True): 
                flash('Global Native B2 client re-initialization failed. Check logs.', 'warning')
        else:
            flash('Failed to delete stored B2 API credentials or no credentials to delete.', 'warning')
    elif credential_type_to_delete == 's3':
        if delete_s3_credentials():
            flash('Stored S3 API credentials deleted.', 'success')
        else:
            flash('Failed to delete stored S3 API credentials or no credentials to delete.', 'warning')
    else:
        flash('Invalid credential type specified for deletion.', 'danger')
        
    return redirect(url_for('api_settings'))

# Add other routes like /compare, /reports/generate, /settings (notifications), /settings/schedule, /snapshots (list)
# Ensure they use global `db` and `app_config` correctly.
# Example:
@app.route('/reports/generate', methods=['GET'])
@login_required
def generate_report():
    """Generate a report based on snapshot data with optional export formats"""
    try:
        snapshot_id = request.args.get('snapshot_id')
        report_type = request.args.get('type', 'standard')  # standard or detailed
        export_format = request.args.get('format', 'html')  # html, json, csv
        
        if not snapshot_id:
            flash('Snapshot ID is required for report generation', 'warning')
            return redirect(url_for('index'))
            
        snapshot = db.get_snapshot_by_id(int(snapshot_id))
        if not snapshot:
            flash('Snapshot not found', 'error')
            return redirect(url_for('index'))
            
        # Handle different export formats
        if export_format == 'json':
            return jsonify(snapshot)
        elif export_format == 'csv':
            # Implementation for CSV export would go here
            # For now, redirect to the HTML report with a message
            flash('CSV export is not yet implemented', 'info')
            return redirect(url_for('generate_report', snapshot_id=snapshot_id, type=report_type))
        else:  # Default to HTML
            # Render the report template with the snapshot data
            return render_template(
                'report.html',
                page_title=f"Cost Report - {snapshot.get('timestamp', 'Unknown')}",
                snapshot=snapshot,
                report_type=report_type,
                now=datetime.now()
            )
    except Exception as e:
        logger.error(f"Error generating report: {str(e)}")
        flash(f"Error generating report: {str(e)}", 'danger')
        return redirect(url_for('index'))

@app.route('/compare', methods=['GET'])
@login_required
def compare_snapshots():
    snapshot1_id = request.args.get('snapshot1')
    snapshot2_id = request.args.get('snapshot2')
    snapshots_list = db.get_latest_snapshots(limit=30) # For dropdowns

    if not snapshot1_id or not snapshot2_id:
        return render_template('compare.html', page_title="Compare Snapshots", snapshots=snapshots_list)
    
    try:
        snapshot1 = db.get_snapshot_by_id(int(snapshot1_id))
        snapshot2 = db.get_snapshot_by_id(int(snapshot2_id))

        if not snapshot1 or not snapshot2:
            flash('One or both snapshots not found for comparison.', 'error')
            return redirect(url_for('compare_snapshots'))
        
        # Calculate differences between snapshots
        differences = {
            'storage_bytes': snapshot2['total_storage_bytes'] - snapshot1['total_storage_bytes'],
            'storage_cost': snapshot2['total_storage_cost'] - snapshot1['total_storage_cost'],
            'download_bytes': snapshot2['total_download_bytes'] - snapshot1['total_download_bytes'],
            'download_cost': snapshot2['total_download_cost'] - snapshot1['total_download_cost'],
            'api_calls': snapshot2['total_api_calls'] - snapshot1['total_api_calls'],
            'api_cost': snapshot2['total_api_cost'] - snapshot1['total_api_cost'],
            'total_cost': snapshot2['total_cost'] - snapshot1['total_cost']
        }
        
        # Calculate percentage changes
        def calc_percent_change(old, new):
            if old == 0:
                return 100 if new > 0 else 0
            return ((new - old) / old) * 100
        
        percent_changes = {
            'storage_bytes': calc_percent_change(snapshot1['total_storage_bytes'], snapshot2['total_storage_bytes']),
            'storage_cost': calc_percent_change(snapshot1['total_storage_cost'], snapshot2['total_storage_cost']),
            'download_bytes': calc_percent_change(snapshot1['total_download_bytes'], snapshot2['total_download_bytes']),
            'download_cost': calc_percent_change(snapshot1['total_download_cost'], snapshot2['total_download_cost']),
            'api_calls': calc_percent_change(snapshot1['total_api_calls'], snapshot2['total_api_calls']),
            'api_cost': calc_percent_change(snapshot1['total_api_cost'], snapshot2['total_api_cost']),
            'total_cost': calc_percent_change(snapshot1['total_cost'], snapshot2['total_cost'])
        }
        
        # Get bucket comparisons
        bucket_comparisons = []
        bucket1_dict = {b['bucket_name']: b for b in snapshot1['buckets']}
        bucket2_dict = {b['bucket_name']: b for b in snapshot2['buckets']}
        
        # All bucket names from both snapshots
        all_bucket_names = set(bucket1_dict.keys()) | set(bucket2_dict.keys())
        
        for bucket_name in all_bucket_names:
            bucket1 = bucket1_dict.get(bucket_name, {
                'storage_bytes': 0,
                'storage_cost': 0,
                'download_bytes': 0,
                'download_cost': 0,
                'api_calls': 0,
                'api_cost': 0,
                'total_cost': 0
            })
            
            bucket2 = bucket2_dict.get(bucket_name, {
                'storage_bytes': 0,
                'storage_cost': 0,
                'download_bytes': 0,
                'download_cost': 0,
                'api_calls': 0,
                'api_cost': 0,
                'total_cost': 0
            })
            
            # Only include buckets with changes if they exist in both snapshots
            if bucket_name in bucket1_dict and bucket_name in bucket2_dict:
                storage_diff = bucket2['storage_bytes'] - bucket1['storage_bytes']
                cost_diff = bucket2['total_cost'] - bucket1['total_cost']
                
                # Calculate percent change
                if bucket1['storage_bytes'] == 0:
                    storage_percent = 100 if storage_diff > 0 else 0
                else:
                    storage_percent = (storage_diff / bucket1['storage_bytes']) * 100
                    
                if bucket1['total_cost'] == 0:
                    cost_percent = 100 if cost_diff > 0 else 0
                else:
                    cost_percent = (cost_diff / bucket1['total_cost']) * 100
                
                bucket_comparisons.append({
                    'name': bucket_name,
                    'storage_bytes1': bucket1['storage_bytes'],
                    'storage_bytes2': bucket2['storage_bytes'],
                    'storage_diff': storage_diff,
                    'storage_percent': storage_percent,
                    'total_cost1': bucket1['total_cost'],
                    'total_cost2': bucket2['total_cost'],
                    'cost_diff': cost_diff,
                    'cost_percent': cost_percent
                })
        
        # Sort by absolute cost difference
        bucket_comparisons.sort(key=lambda x: abs(x['cost_diff']), reverse=True)
        
        return render_template(
            'compare.html', page_title="Snapshot Comparison",
            snapshot1=snapshot1, snapshot2=snapshot2,
            differences=differences, percent_changes=percent_changes, bucket_comparisons=bucket_comparisons,
            snapshots=snapshots_list # For dropdowns
        )
    except Exception as e:
        logger.error(f"Error in compare route: {e}", exc_info=True)
        flash(f"Error comparing snapshots: {e}", "danger")
        return redirect(url_for('index'))

# WebSocket routes
if socketio_available:
    @socketio.on('connect', namespace='/ws')
    def ws_connect():
        logger.info(f"WebSocket client connected: {request.sid}")
        emit('connection_response', {'status': 'connected', 'sid': request.sid})
        
        # Send initial snapshot progress state
        with snapshot_progress_lock:
            progress_data = copy.deepcopy(snapshot_progress_global)
            emit('snapshot_progress_update', progress_data)
    
    @socketio.on('disconnect', namespace='/ws')
    def ws_disconnect():
        logger.info(f"WebSocket client disconnected: {request.sid}")

    @socketio.on('ping_server', namespace='/ws')
    def handle_ping():
        """Handle manual ping from client to keep the connection alive"""
        logger.debug(f"Received ping from client {request.sid}, sending pong")
        emit('pong_response', {'timestamp': datetime.now().isoformat(), 'sid': request.sid})
        
        # Send current status as well to ensure client has latest data
        with snapshot_progress_lock:
            progress_data = copy.deepcopy(snapshot_progress_global)
            emit('snapshot_progress_update', progress_data)
    
    # Add explicit handler for the built-in Engine.IO ping event
    @socketio.on('ping', namespace='/ws')
    def handle_engineio_ping():
        logger.debug(f"Received Engine.IO ping from {request.sid}")
        # No need to respond, Engine.IO handles the pong automatically
    
    # Add error handler
    @socketio.on_error(namespace='/ws')
    def handle_error(e):
        logger.error(f"SocketIO error occurred: {str(e)}")
        # Do not disconnect, let the client reconnect if needed

if __name__ == '__main__':
    run_app()
