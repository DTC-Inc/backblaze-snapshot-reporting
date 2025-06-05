import os
import json
import logging
import threading # Import threading
from threading import Lock
import time
from datetime import datetime, timedelta, timezone
import copy
import secrets, re

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
from app.models.redis_buffer import RedisEventBuffer
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

# Webhook imports
from app.webhooks import WebhookProcessor

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

# Initialize Redis buffer for webhook events
redis_buffer = None
try:
    from app.config import REDIS_URL, REDIS_FLUSH_INTERVAL, REDIS_ENABLED
    if REDIS_ENABLED:
        redis_buffer = RedisEventBuffer(
            redis_url=REDIS_URL,
            flush_interval=REDIS_FLUSH_INTERVAL
        )
        redis_buffer.set_database(db)
        redis_buffer.start_flush_worker()
        logger.info(f"Redis event buffering enabled (flush every {REDIS_FLUSH_INTERVAL}s)")
    else:
        logger.info("Redis buffering disabled - using direct SQLite writes")
except Exception as e:
    logger.error(f"Failed to initialize Redis buffer: {e}")
    logger.info("Falling back to direct SQLite writes")
    redis_buffer = None

# Initialize webhook processor
webhook_processor = WebhookProcessor(db)
if redis_buffer:
    webhook_processor.set_redis_buffer(redis_buffer)

# Initialize CSRF Protection
csrf = CSRFProtect(app)

# Flask-Login setup
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Import routes from other modules AFTER app and extensions are initialized
from .schedule_routes import schedule_bp # Import the blueprint
app.register_blueprint(schedule_bp) # Register the blueprint

from .webhook_routes import webhook_bp # Import the webhook blueprint
app.register_blueprint(webhook_bp) # Register the webhook blueprint

from .dashboard_routes import dashboard_bp # Import the new dashboard blueprint
app.register_blueprint(dashboard_bp) # Register the new dashboard blueprint

# Make database instance available to routes
app.config['DATABASE_INSTANCE'] = db

# Make Socket.IO instance available to routes
app.config['SOCKETIO_INSTANCE'] = socketio

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
stop_snapshot_event = threading.Event() # Add a threading event

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

def snapshot_worker(app_context, snapshot_type, snapshot_name, api_choice, clear_cache=False, stop_event_ref=None):
    with app_context.app_context(): # Use app_context
        current_app.logger.info(f"Snapshot worker started for type: {snapshot_type}, name: {snapshot_name}, API: {api_choice}, Clear Cache: {clear_cache}")
        
        # Check stop event at the beginning
        if stop_event_ref and stop_event_ref.is_set():
            current_app.logger.info("Snapshot worker received stop signal before starting processing.")
            # Ensure global state reflects it was stopped early
            with snapshot_progress_lock:
                snapshot_progress_global.update({
                    "active": False, 
                    "status_message": "Snapshot cancelled before start.",
                    "error_message": "Cancelled by user.",
                    "overall_percentage": 0, 
                    "end_time": datetime.utcnow().isoformat()
                })
            return

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
            
            # Periodically check stop_event_ref if client_instance.take_snapshot is very long and not cooperative
            # For now, we check before and assume take_snapshot will eventually return or client handles its own interrupt
            if stop_event_ref and stop_event_ref.is_set():
                current_app.logger.info(f"Stop signal received for '{snapshot_name}' before calling client's take_snapshot.")
                raise Exception("Snapshot cancelled by user during setup")

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
                if stop_event_ref and stop_event_ref.is_set():
                    status_msg = f"Snapshot cancelled by user: {e}"
                    error_msg = str(e) + " (Cancelled by user)"
                else:
                    status_msg = f"Snapshot failed: {e}"
                    error_msg = str(e)
                
                snapshot_progress_global["active"] = False
                snapshot_progress_global["status_message"] = status_msg
                snapshot_progress_global["error_message"] = error_msg
                snapshot_progress_global["end_time"] = datetime.utcnow().isoformat()
                if not (snapshot_progress_global.get("overall_percentage", 0) == 100 and not snapshot_progress_global.get("active")):
                     if snapshot_progress_global.get("total_buckets",0) == 0 and snapshot_progress_global.get("buckets_processed_count",0) == 0:
                        snapshot_progress_global["overall_percentage"] = 0 # Reset percentage if failed early
                snapshot_progress_global["current_processing_bucket_name"] = None
        finally:
            if stop_event_ref and stop_event_ref.is_set():
                current_app.logger.info(f"Snapshot worker for '{snapshot_name}' acknowledges stop signal in finally block.")
                with snapshot_progress_lock:
                    if snapshot_progress_global.get("active", True): # If it was still marked active
                        snapshot_progress_global["active"] = False
                        snapshot_progress_global["status_message"] = snapshot_progress_global.get("status_message", "") + " (Interrupted)"
                        snapshot_progress_global["error_message"] = snapshot_progress_global.get("error_message", "Interrupted by user.")
                        snapshot_progress_global["end_time"] = datetime.utcnow().isoformat()
                        if snapshot_progress_global.get("overall_percentage", 0) != 100:
                            # Don't mark 100% if interrupted before completion, unless it naturally finished.
                            pass # Percentage will be as it was

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
# @login_required # Consider if home page needs login - for now, let dashboard be accessible
def index(): # Will now serve the new dashboard
    try:
        bucket_names = db.get_all_bucket_names_from_webhooks() # Fetch bucket names for filter
        return render_template(
            'dashboard.html', 
            page_title="Operations Dashboard", 
            bucket_names=bucket_names
        )
    except Exception as e:
        logger.error(f"Error in dashboard index route: {str(e)}", exc_info=True)
        # You might want a more specific error template for the dashboard
        return render_template('error.html', error=str(e))

@app.route('/old_dashboard') # Keep old dashboard accessible at a different route for now
@login_required
def old_dashboard():
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
    # global stop_snapshot_thread # Remove usage of old boolean flag
    global stop_snapshot_event # Use the threading.Event

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
        
        clear_cache = request.form.get('clear_cache') == 'true'
        
        with snapshot_progress_lock:
            if snapshot_progress_global.get("active", False) or (snapshot_thread and snapshot_thread.is_alive()):
                flash('A snapshot is already in progress. Please wait for it to complete.', 'warning')
                return redirect(url_for('snapshot_status_detail')) 
            
            stop_snapshot_event.clear() # Clear event flag for new snapshot

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
        # Pass the stop_snapshot_event to the worker
        thread = threading.Thread(target=snapshot_worker, args=(app_context_obj, "manual", snapshot_name, api_choice, clear_cache, stop_snapshot_event))
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
    global snapshot_thread 
    global stop_snapshot_event # Use the event
    
    try:
        logger.info("Attempting to send stop signal to snapshot worker...")
        stop_snapshot_event.set() # Signal the event
        
        # Update the snapshot progress to indicate it's being terminated
        with snapshot_progress_lock:
            snapshot_progress_global.update({
                # "active": False, # Let the worker thread update this when it acknowledges
                "status_message": "Termination signal sent. Waiting for worker to stop...",
                "error_message": snapshot_progress_global.get("error_message"), # Keep existing error if any
                # "end_time": datetime.utcnow().isoformat() # Worker will set its end time
            })
            
        if socketio:
            socketio.emit('snapshot_progress_update', snapshot_progress_global, namespace='/ws')
        
        # Check if thread exists and is alive - join with timeout
        if snapshot_thread and snapshot_thread.is_alive():
            logger.info("Waiting for snapshot thread to join (max 5s)...")
            snapshot_thread.join(timeout=5.0) 
            
            if snapshot_thread.is_alive():
                logger.warning("Snapshot thread did not stop gracefully within timeout after signal.")
                # UI should eventually reflect the worker's final state via its own reporting
                flash_msg = "Snapshot process was signaled to stop, but may still be running. Check status page."
                success_flag = False
            else:
                logger.info("Snapshot thread terminated or finished after signal.")
                snapshot_thread = None # Clear the global ref
                flash_msg = "Snapshot process termination signal acknowledged by worker or process finished."
                success_flag = True
        else:
            logger.info("No active snapshot thread found, or already stopped.")
            flash_msg = "No active snapshot process to terminate, or it has already stopped."
            success_flag = True # Considered success as there's nothing to kill
            if snapshot_thread: # If thread object exists but not alive
                snapshot_thread = None
        
        return jsonify({
            "success": success_flag,
            "message": flash_msg
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

# --- Webhook API Routes ---

@app.route('/api/webhooks/backblaze', methods=['POST'])
@csrf.exempt  # Webhook endpoints need to be exempt from CSRF
def receive_backblaze_webhook():
    """Receive webhook events from Backblaze"""
    try:
        # Get raw payload for signature verification and logging
        raw_payload = request.get_data(as_text=True)
        # logger.info(f"Received raw Backblaze webhook payload: {raw_payload}") # Removed for cleaner logs
        
        # Parse JSON payload
        payload_data = None # Initialize
        try:
            payload_data = request.get_json()
            if not payload_data:
                logger.warning("Webhook request contained no JSON payload or result of get_json() was None/empty.")
                return jsonify({'error': 'Invalid or empty JSON payload'}), 400
            logger.info(f"Successfully parsed webhook JSON. Payload keys: {list(payload_data.keys()) if isinstance(payload_data, dict) else 'Not a dict'}")
        except Exception as e:
            logger.error(f"Error parsing JSON payload from webhook: {e}", exc_info=True)
            return jsonify({'error': 'Failed to parse JSON payload'}), 400
        
        # Get request metadata
        source_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
        user_agent = request.headers.get('User-Agent', '')
        
        # Get signature header - prioritize official Backblaze header
        signature = request.headers.get('X-Bz-Event-Notification-Signature')
        signature_source = 'X-Bz-Event-Notification-Signature'
        
        if not signature:
            # Fallback to alternative header (for testing or legacy)
            signature = request.headers.get('X-Hub-Signature-256')
            if signature:
                signature_source = 'X-Hub-Signature-256'
                logger.info("Using fallback 'X-Hub-Signature-256' for webhook signature.")
        
        if not signature:
            logger.warning("Webhook signature missing from headers (checked X-Bz-Event-Notification-Signature and X-Hub-Signature-256).")
            logger.debug(f"Available headers: {list(request.headers.keys())}")
            # Depending on policy, might allow if no secret, or reject. For now, log and proceed.
        
        if signature:
            logger.debug(f"Found webhook signature in header '{signature_source}': {signature}")

        # Get bucket name from the event payload
        bucket_name = None
        if payload_data and isinstance(payload_data, dict) and payload_data.get('events') and isinstance(payload_data['events'], list) and len(payload_data['events']) > 0:
            # Assuming the first event in the list is representative for the bucket name
            first_event = payload_data['events'][0]
            if isinstance(first_event, dict):
                bucket_name = first_event.get('bucketName')
        
        if not bucket_name: # Fallback to query param if not found in payload structure
             logger.info(f"Could not find 'bucketName' in payload_data.events[0]. Trying request.args. Payload: {payload_data}")
             bucket_name = request.args.get('bucket')

        if not bucket_name:
            logger.error(f"Webhook payload and query parameters missing 'bucketName'. Could not extract from events structure or query. Payload checked: {payload_data}")
            return jsonify({'error': 'Missing bucket name in payload and query parameters'}), 400
        logger.info(f"Webhook identified for bucket: {bucket_name}")

        # Verify webhook signature if secret is configured
        bucket_config = db.get_bucket_configuration(bucket_name)
        if bucket_config and bucket_config.get('webhook_secret'):
            webhook_secret = bucket_config['webhook_secret']
            if not raw_payload: # Should not happen if we logged raw_payload earlier
                logger.error(f"Cannot verify signature for bucket {bucket_name}: raw_payload is empty despite earlier log.")
                return jsonify({'error': 'Cannot verify signature due to empty payload'}), 500
            
            logger.debug(f"Attempting signature verification for bucket {bucket_name} with stored secret.")
            if not webhook_processor.verify_webhook_signature(raw_payload, signature, webhook_secret):
                logger.warning(f"Invalid webhook signature for bucket {bucket_name}. Signature received: '{signature}'. Expected based on secret for {bucket_name}. If secret recently changed, this might be normal for a short period.")
                return jsonify({'error': 'Invalid signature'}), 401
            logger.info(f"Webhook signature VERIFIED for bucket {bucket_name}.")
        elif bucket_config and not bucket_config.get('webhook_secret'):
            logger.info(f"Webhook for bucket {bucket_name} received. No webhook_secret is configured for this bucket locally. Proceeding without signature verification.")
        elif not bucket_config:
             logger.warning(f"Received webhook for bucket '{bucket_name}' but no local configuration (and thus no secret) found. This event will likely be rejected by process_webhook_event if it requires enabled status.")
             # Allow to proceed to process_webhook_event, which will then check webhook_enabled flag.

        # Process the webhook event
        first_event_type = None
        if payload_data and payload_data.get('events') and isinstance(payload_data['events'], list) and len(payload_data['events']) > 0:
            if isinstance(payload_data['events'][0], dict):
                first_event_type = payload_data['events'][0].get('eventType')

        logger.info(f"Calling webhook_processor.process_webhook_event for bucket: {bucket_name} (First event type: {first_event_type if first_event_type else 'N/A'})")
        
        actual_event_data = None
        if payload_data and isinstance(payload_data, dict) and payload_data.get('events') and isinstance(payload_data['events'], list) and len(payload_data['events']) > 0:
            if isinstance(payload_data['events'][0], dict):
                actual_event_data = payload_data['events'][0]
        
        if not actual_event_data:
            logger.error(f"Could not extract actual event data from webhook payload for bucket {bucket_name}. Original payload structure: {payload_data}")
            return jsonify({'error': 'Malformed event data in webhook payload'}), 400

        logger.info(f"Passing event data to processor. Keys: {list(actual_event_data.keys())}. For bucket: {bucket_name} (derived from event data: {actual_event_data.get('bucketName')})")

        result = webhook_processor.process_webhook_event(
            actual_event_data, 
            source_ip=source_ip, 
            user_agent=user_agent
        )
        
        if result['success']:
            # Emit real-time update via Socket.IO if available
            if socketio:
                try:
                    b2_event_actual = {} # Default to empty dict
                    if payload_data and isinstance(payload_data, dict) and \
                       payload_data.get('events') and isinstance(payload_data['events'], list) and \
                       len(payload_data['events']) > 0 and isinstance(payload_data['events'][0], dict):
                        b2_event_actual = payload_data['events'][0]

                    # Data to be sent over WebSocket for a new event
                    # This structure should align with what loadInitialData() provides for historical events,
                    # and what renderEventCard() expects.
                    event_data_for_socket = {
                        'id': result['event_id'],  # DB auto-increment ID
                        'request_id': b2_event_actual.get('eventId'),       # B2's original eventId
                        'event_type': b2_event_actual.get('eventType'),
                        'bucket_name': b2_event_actual.get('bucketName'),
                        'object_key': b2_event_actual.get('objectName'),    # B2's objectName
                        'object_size': b2_event_actual.get('objectSize'),
                        'object_version_id': b2_event_actual.get('objectVersionId'),
                        'event_timestamp': b2_event_actual.get('eventTimestamp'), # B2's timestamp (ms)
                        'created_at': datetime.now(timezone.utc).isoformat(), # App's processing timestamp (ISO string)
                        # raw_payload is not sent to save bandwidth; modal can fetch full if needed or use DB data
                    }
                    
                    socketio.emit('webhook_event', event_data_for_socket, namespace='/ws')
                    logger.debug(f"Emitted real-time update. DB ID: {result['event_id']}, B2 Event ID: {b2_event_actual.get('eventId')}")
                except Exception as e:
                    logger.error(f"Error emitting real-time webhook update: {e}", exc_info=True)
            
            return jsonify({
                'status': 'success',
                'message': result['message'],
                'event_id': result['event_id']
            }), 200
        else:
            return jsonify({
                'status': 'error',
                'error': result['error']
            }), 400
            
    except Exception as e:
        logger.error(f"Error processing webhook: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/api/webhooks/info')
@login_required
def webhook_info():
    """Get webhook configuration information"""
    try:
        bucket_name = request.args.get('bucket')
        return jsonify(webhook_processor.get_webhook_url(bucket_name, include_secret=True))
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/webhooks/events', methods=['GET'])
@login_required
def get_webhook_events():
    """Get webhook events with optional filtering"""
    try:
        limit = int(request.args.get('limit', 100))
        bucket_name = request.args.get('bucket')
        event_type = request.args.get('event_type')
        
        events = db.get_webhook_events(limit=limit, bucket_name=bucket_name, event_type=event_type)
        return jsonify({'events': events})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/webhooks/statistics', methods=['GET'])
@login_required
def get_webhook_statistics():
    """Get webhook statistics"""
    try:
        days = int(request.args.get('days', 30))
        summary = webhook_processor.get_event_summary(days=days)
        return jsonify(summary)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/webhooks/buckets', methods=['GET'])
@login_required
def get_bucket_configurations():
    """Get all bucket webhook configurations"""
    try:
        configs = db.get_all_bucket_configurations()
        return jsonify({'configurations': configs})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/webhooks/buckets/<bucket_name>', methods=['GET', 'POST', 'DELETE'])
@login_required
def manage_bucket_configuration(bucket_name):
    """Manage webhook configuration for a specific bucket"""
    try:
        if request.method == 'GET':
            config = db.get_bucket_configuration(bucket_name)
            if config:
                return jsonify(config)
            else:
                return jsonify({'error': 'Configuration not found'}), 404
                
        elif request.method == 'POST':
            data = request.get_json()
            webhook_enabled = data.get('webhook_enabled', False)
            events_to_track = data.get('events_to_track', ['b2:ObjectCreated', 'b2:ObjectDeleted'])
            
            # Generate secret if enabling webhooks and no secret exists
            webhook_secret = data.get('webhook_secret')
            if webhook_enabled and not webhook_secret:
                webhook_secret = secrets.token_hex(16)  # 32 lowercase hex chars
            
            success = db.save_bucket_configuration(
                bucket_name=bucket_name,
                webhook_enabled=webhook_enabled,
                webhook_secret=webhook_secret,
                events_to_track=events_to_track
            )
            
            if success:
                config = db.get_bucket_configuration(bucket_name)
                return jsonify({
                    'message': 'Configuration saved successfully',
                    'configuration': config
                })
            else:
                return jsonify({'error': 'Failed to save configuration'}), 500
                
        elif request.method == 'DELETE':
            success = db.delete_bucket_configuration(bucket_name)
            if success:
                return jsonify({'message': 'Configuration deleted successfully'})
            else:
                return jsonify({'error': 'Configuration not found'}), 404
                
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# --- B2 Bucket Information Routes ---
@app.route('/api/b2_buckets', methods=['GET'])
@login_required
def api_get_b2_buckets():
    """API endpoint to list all B2 buckets from the local database."""
    try:
        buckets = db.get_all_b2_buckets()
        return jsonify({'b2_buckets': buckets})
    except Exception as e:
        logger.error(f"API error getting B2 buckets: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@app.route('/api/b2_buckets/sync', methods=['POST'])
@login_required
def api_sync_b2_buckets():
    """API endpoint to sync B2 bucket information from Backblaze to the local database."""
    try:
        logger.info("Initiating B2 bucket sync from Backblaze API...")
        # Initialize the appropriate client (Native B2 or S3)
        # For full bucket details including eventNotificationRules, Native B2 API is preferred.
        # S3 ListBuckets doesn't return eventNotificationRules directly.
        
        # Prioritize native B2 client for this detailed information.
        b2_native_client = NativeBackblazeClient() # Assumes client handles its own auth
        if not (b2_native_client.account_id and b2_native_client.auth_token):
            logger.error("B2 Native Client not authorized. Cannot sync bucket details.")
            return jsonify({'error': 'B2 Native Client not authorized'}), 500

        # Fetch detailed bucket list using the native client
        # list_buckets() when called with accountId (which it does internally after auth)
        # should return all details according to B2 docs.
        bucket_list_response = b2_native_client.list_buckets()
        
        # try:
        #     logger.info(f"Raw initial bucket list response from B2: {json.dumps(bucket_list_response, indent=2)}")
        # except Exception as log_e:
        #     logger.error(f"Error logging raw B2 bucket list response: {log_e}")

        if bucket_list_response and 'buckets' in bucket_list_response:
            fetched_buckets_initial = bucket_list_response['buckets']
            processed_buckets_for_db = []
            successful_rule_fetches = 0
            failed_rule_fetches = 0

            for bkt_initial_data in fetched_buckets_initial:
                bucket_id = bkt_initial_data.get('bucketId')
                bucket_name = bkt_initial_data.get('bucketName')
                if not bucket_id or not bucket_name:
                    logger.warning(f"Skipping bucket with missing ID or Name in initial list: {bkt_initial_data}")
                    continue

                current_bucket_data = bkt_initial_data.copy() # Start with data from list_buckets

                try:
                    logger.info(f"Sync: Fetching event notification rules explicitly for bucket: {bucket_name} ({bucket_id})")
                    rules_response = b2_native_client.get_bucket_notification_rules(bucket_id)
                    
                    # Log the raw response from B2 for debugging
                    try:
                        logger.info(f"Raw get_bucket_notification_rules response for {bucket_name}: {json.dumps(rules_response, indent=2)}")
                    except Exception as log_e:
                        logger.error(f"Error logging raw notification rules response for {bucket_name}: {log_e}")

                    if rules_response and 'eventNotificationRules' in rules_response:
                        logger.info(f"Sync: Successfully fetched rules for {bucket_name}: {len(rules_response['eventNotificationRules'])} rules found.")
                        current_bucket_data['eventNotificationRules'] = rules_response['eventNotificationRules']
                        successful_rule_fetches += 1
                        
                        # Check if any of the rules is our 'bbssr-webhook' rule
                        app_webhook_rule_found = False
                        tracked_events_from_rule = []
                        for rule in rules_response['eventNotificationRules']:
                            if rule.get('name') == 'bbssr-webhook' and rule.get('isEnabled') == True:
                                app_webhook_rule_found = True
                                tracked_events_from_rule = rule.get('eventTypes', [])
                                logger.info(f"Sync: Found active 'bbssr-webhook' rule for {bucket_name} on B2. Events: {tracked_events_from_rule}")
                                break
                         
                        existing_local_config = db.get_bucket_configuration(bucket_name)

                        if app_webhook_rule_found:
                            db.save_bucket_configuration(
                                bucket_name=bucket_name,
                                webhook_enabled=True,
                                webhook_secret=existing_local_config.get('webhook_secret') if existing_local_config else None, # Preserve existing secret
                                events_to_track=tracked_events_from_rule
                            )
                            logger.info(f"Sync: Local config for {bucket_name} updated/confirmed as ENABLED based on B2 rule.")
                        else: # No active 'bbssr-webhook' rule found on B2
                            if not existing_local_config or not existing_local_config.get('webhook_enabled'):
                                # If no local config, or it was already disabled, ensure it's disabled.
                                db.save_bucket_configuration(bucket_name=bucket_name, webhook_enabled=False, webhook_secret=None, events_to_track=[])
                                logger.info(f"Sync: No active 'bbssr-webhook' rule on B2 for {bucket_name}. Local config set/confirmed as DISABLED.")
                            else:
                                # Local config was enabled, but B2 now reports no rule. Log this, but DON'T change local processing state.
                                logger.warning(f"Sync: Bucket '{bucket_name}' is locally configured as webhook_enabled=True, "
                                               f"but B2 currently reports no active 'bbssr-webhook' rule. "
                                               f"UI will reflect B2's report (likely 'Disabled'). "
                                               f"Local processing status in 'bucket_configurations' REMAINS ENABLED based on prior user action.")

                    else:
                        logger.warning(f"Sync: Failed to fetch or parse rules for {bucket_name}. Response: {rules_response}")
                        current_bucket_data['eventNotificationRules'] = [] # Default to empty if fetch fails
                        failed_rule_fetches += 1
                        db.save_bucket_configuration(bucket_name=bucket_name, webhook_enabled=False, webhook_secret=None, events_to_track=[])
                        logger.info(f"Sync: Due to rule fetch failure for {bucket_name}, local config set to DISABLED.")

                except Exception as e_rules:
                    logger.error(f"Sync: Error fetching/processing rules for bucket {bucket_name} ({bucket_id}): {e_rules}", exc_info=True)
                    current_bucket_data['eventNotificationRules'] = [] # Default to empty on error
                    failed_rule_fetches += 1
                    # On exception, preserve existing local config for webhook_enabled if it exists and was true
                    existing_local_config_on_error = db.get_bucket_configuration(bucket_name)
                    if not existing_local_config_on_error or not existing_local_config_on_error.get('webhook_enabled'):
                        db.save_bucket_configuration(bucket_name=bucket_name, webhook_enabled=False, webhook_secret=None, events_to_track=[])
                        logger.info(f"Sync: Due to exception during rule processing for {bucket_name}, and no prior enabled config, local config set to DISABLED.")
                    else:
                        logger.warning(f"Sync: Exception during rule processing for {bucket_name}. UI will show 'Disabled'. Local processing status REMAINS ENABLED.")
                
                processed_buckets_for_db.append(current_bucket_data)
                time.sleep(0.2) # Add a small delay (e.g., 200ms) between processing each bucket

            logger.info(f"Sync: Rule fetching complete. Successful: {successful_rule_fetches}, Failed: {failed_rule_fetches}")
            db.save_b2_bucket_details(processed_buckets_for_db) 
            logger.info(f"Successfully synced {len(processed_buckets_for_db)} B2 buckets to local database with explicit rule fetching.")
            return jsonify({'message': f"Successfully synced {len(processed_buckets_for_db)} B2 buckets with detailed rule check.", 'synced_count': len(processed_buckets_for_db)})
        else:
            logger.error(f"Failed to fetch initial bucket list from B2. Response: {bucket_list_response}")
            return jsonify({'error': 'Failed to fetch initial bucket list from B2'}), 500
            
    except Exception as e:
        logger.error(f"API error syncing B2 buckets: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@app.route('/api/b2_buckets/<bucket_b2_id>/configure_notifications', methods=['POST'])
@login_required
def api_configure_bucket_notifications(bucket_b2_id):
    """Configure Backblaze B2 event notifications for a specific bucket."""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Invalid JSON payload'}), 400

    enable = data.get('enable') # Should be True or False
    event_types_to_monitor = data.get('event_types', app_config.WEBHOOK_DEFAULT_EVENTS) # Default if not provided
    webhook_url_override = data.get('webhook_url')

    if enable is None:
        return jsonify({'error': "'enable' field (true/false) is required."}), 400
    
    logger.info(f"[PRE-CONFIG] Raw data from request for bucket {bucket_b2_id}: {data}") # Log raw data
    logger.info(f"[PRE-CONFIG] app_config.WEBHOOK_DEFAULT_EVENTS is: {app_config.WEBHOOK_DEFAULT_EVENTS}")

    try:
        # Get bucket details from our local DB to find its name
        b2_bucket_info = db.get_b2_bucket_by_id(bucket_b2_id) # We need a method for this, or get_all and filter
        # Let's assume we add get_b2_bucket_by_id(b2_id) to database.py
        # For now, let's try to find it from all buckets (less efficient but works for now)
        all_b2_buckets = db.get_all_b2_buckets()
        target_bucket_info = next((b for b in all_b2_buckets if b.get('bucket_b2_id') == bucket_b2_id), None)

        if not target_bucket_info:
            return jsonify({'error': f'Bucket with B2 ID {bucket_b2_id} not found in local database. Sync buckets first.'}), 404
        
        bucket_name = target_bucket_info.get('bucket_name')
        
        client = NativeBackblazeClient()
        if not client.account_id: # Ensure client is authorized
            return jsonify({'error': 'B2 Native Client not authorized'}), 500

        # Build eventNotificationRules according to B2 docs
        new_webhook_secret = None
        if enable:
            if not app_config.APP_PUBLIC_URL and not webhook_url_override:
                return jsonify({'error': 'APP_PUBLIC_URL not configured and no webhook_url provided.'}), 500

            new_webhook_secret = secrets.token_hex(16)  # 32 lowercase hex chars
            if webhook_url_override:
                webhook_url_for_b2 = webhook_url_override.rstrip('/')
            else:
                base_url = app_config.APP_PUBLIC_URL.rstrip('/')
                webhook_path = url_for('receive_backblaze_webhook')  # Should be /api/webhooks/backblaze
                
                # Check if APP_PUBLIC_URL already contains the webhook path or similar
                if '/api/webhook' in base_url:
                    # APP_PUBLIC_URL already contains webhook path, use as-is but fix any typos
                    webhook_url_for_b2 = base_url.replace('/webooks/', '/webhooks/')
                else:
                    # APP_PUBLIC_URL is just the domain, append the webhook path
                    webhook_url_for_b2 = f"{base_url}{webhook_path}"
            
            logger.info(f"[PRE-CONFIG] event_types_to_monitor before rule_obj creation: {event_types_to_monitor}") # Log the chosen event types

            rule_obj = {
                "eventTypes": event_types_to_monitor,
                "isEnabled": True,
                "name": "bbssr-webhook",
                "objectNamePrefix": "",
                "targetConfiguration": {
                    "targetType": "webhook",
                    "url": webhook_url_for_b2,
                    "customHeaders": [],  # Required field according to B2 docs
                    "hmacSha256SigningSecret": new_webhook_secret  # B2 API expects this format
                }
            }
            event_rules = [rule_obj]
        else:
            event_rules = []  # Disable

        logger.info(f"Attempting to configure notifications for bucket {bucket_name} ({bucket_b2_id}). Enable: {enable}")
        logger.debug(f"Target rules for B2: {json.dumps(event_rules)}")

        b2_set_rules_response = client.set_bucket_notification_rules(bucket_b2_id, event_rules)
        logger.info(f"B2 set_bucket_notification_rules response for {bucket_name}: {json.dumps(b2_set_rules_response)}")

        # Update our local bucket_configurations table immediately
        db.save_bucket_configuration(
            bucket_name=bucket_name,
            webhook_enabled=enable,
            webhook_secret=new_webhook_secret if enable else None,
            events_to_track=event_types_to_monitor if enable else []
        )
        
        # Re-sync this specific bucket's details from B2 to update our b2_buckets table immediately
        # Optimistically update with what we intended to set if the B2 set call was successful (didn't raise HTTPError)
        # because get_bucket_notification_rules can be slow to reflect changes.
        try:
            local_bucket_info = db.get_b2_bucket_by_id(bucket_b2_id)
            if local_bucket_info:
                logger.info(f"[POST-CONFIG] Optimistically updating local eventNotificationRules for {bucket_name} based on successful set operation.")
                local_bucket_info['eventNotificationRules'] = event_rules # Use the rules we just tried to set
                
                # Ensure keys for save_b2_bucket_details are correct
                if 'bucket_b2_id' in local_bucket_info and 'bucketId' not in local_bucket_info:
                    local_bucket_info['bucketId'] = local_bucket_info['bucket_b2_id']
                if 'bucket_name' in local_bucket_info and 'bucketName' not in local_bucket_info:
                    local_bucket_info['bucketName'] = local_bucket_info['bucket_name']
                
                db.save_b2_bucket_details([local_bucket_info])
                logger.info(f"[POST-CONFIG] Successfully updated local_bucket_info for {bucket_name} with intended rules.")

                # Optionally, still attempt to log what B2 reports immediately after for diagnostics, but don't use it for immediate update
                try:
                    b2_get_rules_response_diagnostic = client.get_bucket_notification_rules(bucket_b2_id)
                    logger.info(f"[DIAGNOSTIC] Response from get_bucket_notification_rules for {bucket_name} (after optimistic update): {json.dumps(b2_get_rules_response_diagnostic)}")
                except Exception as diag_e:
                    logger.warning(f"[DIAGNOSTIC] Error fetching rules for {bucket_name} for diagnostic purposes: {diag_e}")
            else:
                logger.warning(f"Could not find bucket {bucket_name} ({bucket_b2_id}) in local DB for optimistic re-sync.")
        except Exception as sync_err:
            logger.error(f"Error during optimistic re-sync for bucket {bucket_name} ({bucket_b2_id}): {sync_err}", exc_info=True)

        # Log the raw response from B2 for debugging
        try:
            logger.info(f"Raw get_bucket_notification_rules response for {bucket_name}: {json.dumps(rules_response, indent=2)}")
        except Exception as log_e:
            logger.error(f"Error logging raw notification rules response for {bucket_name}: {log_e}")

        return jsonify({
            'message': f'Successfully {"enabled" if enable else "disabled"} event notifications for bucket {bucket_name}.',
            'bucket_name': bucket_name,
            'b2_id': bucket_b2_id,
            'webhook_enabled': enable,
            'configured_event_types': event_types_to_monitor if enable else [],
            'b2_response': b2_set_rules_response # Include B2's response for diagnostics
        })

    except Exception as e:
        logger.error(f"API error configuring notifications for bucket {bucket_b2_id}: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@app.route('/api/b2_buckets/bulk_configure_notifications', methods=['POST'])
@login_required
def api_bulk_configure_bucket_notifications():
    """Bulk configure Backblaze B2 event notifications for selected buckets."""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Invalid JSON payload'}), 400

    bucket_b2_ids = data.get('bucket_b2_ids')
    enable = data.get('enable')
    event_types_to_monitor = data.get('event_types', app_config.WEBHOOK_DEFAULT_EVENTS)
    webhook_url_override = data.get('webhook_url')

    if not bucket_b2_ids or not isinstance(bucket_b2_ids, list):
        return jsonify({'error': "'bucket_b2_ids' (list) is required."}), 400
    if enable is None:
        return jsonify({'error': "'enable' field (true/false) is required."}), 400
    if enable and not event_types_to_monitor: # Must have event types if enabling
        return jsonify({'error': "'event_types' (list) is required when enabling webhooks."}), 400

    if enable and not app_config.APP_PUBLIC_URL:
        logger.error("APP_PUBLIC_URL is not configured. Cannot set webhook URL for B2 in bulk.")
        return jsonify({'error': 'Application public URL is not configured. Cannot enable webhooks.'}), 500

    results = {'success': [], 'failed': []}
    client = NativeBackblazeClient()
    if not client.account_id: # Ensure client is authorized
        return jsonify({'error': 'B2 Native Client not authorized'}), 500

    all_b2_buckets_from_db = {b.get('bucket_b2_id'): b for b in db.get_all_b2_buckets()} 

    for b2_id in bucket_b2_ids:
        target_bucket_info = all_b2_buckets_from_db.get(b2_id)
        if not target_bucket_info:
            results['failed'].append({'b2_id': b2_id, 'error': 'Bucket not found in local database. Sync first.'})
            continue
        
        bucket_name = target_bucket_info.get('bucket_name')
        current_op_result = {'bucket_name': bucket_name, 'b2_id': b2_id}

        try:
            # Build eventNotificationRules according to B2 docs
            new_webhook_secret = None
            if enable:
                new_webhook_secret = secrets.token_hex(16)  # 32 lowercase hex chars
                if webhook_url_override:
                    webhook_url_for_b2 = webhook_url_override.rstrip('/')
                else:
                    base_url = app_config.APP_PUBLIC_URL.rstrip('/')
                    webhook_path = url_for('receive_backblaze_webhook')  # Should be /api/webhooks/backblaze
                    
                    # Check if APP_PUBLIC_URL already contains the webhook path or similar
                    if '/api/webhook' in base_url:
                        # APP_PUBLIC_URL already contains webhook path, use as-is but fix any typos
                        webhook_url_for_b2 = base_url.replace('/webooks/', '/webhooks/')
                    else:
                        # APP_PUBLIC_URL is just the domain, append the webhook path
                        webhook_url_for_b2 = f"{base_url}{webhook_path}"
                rule_obj = {
                    "eventTypes": event_types_to_monitor,
                    "isEnabled": True,
                    "name": "bbssr-webhook",
                    "objectNamePrefix": "",
                    "targetConfiguration": {
                        "targetType": "webhook",
                        "url": webhook_url_for_b2,
                        "customHeaders": [],  # Required field according to B2 docs
                        "hmacSha256SigningSecret": new_webhook_secret  # B2 API expects this format
                    }
                }
                event_rules = [rule_obj]
            else:
                event_rules = []  # Disable

            logger.info(f"Bulk op: Updating notifications for bucket {bucket_name} ({b2_id}) - Enable: {enable}")
            b2_response = client.set_bucket_notification_rules(b2_id, event_rules)
            logger.debug(f"Bulk op B2 response for {bucket_name}: {b2_response}")
            
            db.save_bucket_configuration(
                bucket_name=bucket_name,
                webhook_enabled=enable,
                webhook_secret=new_webhook_secret if enable else None,
                events_to_track=event_types_to_monitor if enable else []
            )
            current_op_result['status'] = 'success'
            current_op_result['b2_response'] = b2_response
            results['success'].append(current_op_result)
        except Exception as e:
            logger.error(f"Bulk op: Error configuring notifications for bucket {bucket_name} ({b2_id}): {str(e)}")
            current_op_result['status'] = 'error'
            current_op_result['error'] = str(e)
            results['failed'].append(current_op_result)
    
    # Optionally, trigger a full re-sync of all B2 buckets if many were changed.
    # For now, individual syncs are done in the single endpoint, let's see if that's enough.

    return jsonify(results)

@app.route('/api/b2_buckets/capabilities', methods=['GET'])
@login_required
def api_check_b2_capabilities():
    """Check the current B2 auth token's capabilities for troubleshooting."""
    try:
        client = NativeBackblazeClient()
        if not client.account_id:
            return jsonify({'error': 'B2 Native Client not authorized'}), 500
        
        capabilities_info = client.get_auth_capabilities()
        
        # Add some helpful interpretation
        interpretation = {
            'can_configure_webhooks': capabilities_info.get('has_webhook_caps', False),
            'webhook_status': 'ready' if capabilities_info.get('has_webhook_caps', False) else 'missing_permissions',
            'missing_capabilities': capabilities_info.get('missing_for_webhooks', []),
            'recommendations': []
        }
        
        if not capabilities_info.get('has_webhook_caps', False):
            interpretation['recommendations'].append(
                "Create a new application key with 'writeBucketNotifications' and 'readBucketNotifications' capabilities"
            )
            interpretation['recommendations'].append(
                "Also ensure you have basic capabilities: listBuckets, listFiles, readFiles"
            )
            
        return jsonify({
            'capabilities': capabilities_info,
            'interpretation': interpretation,
            'timestamp': datetime.utcnow().isoformat()
        })
        
    except Exception as e:
        logger.error(f"Error checking B2 capabilities: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500

# --- Scheduler ---

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


def before_first_request_setup(): # Initialize function (no longer a decorator)
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
        
        # Initialize the app components (replaces @app.before_first_request)
        with app.app_context():
            before_first_request_setup()
        
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
    logger.info(f"DEBUG: B2_APPLICATION_KEY_ID from env: {os.environ.get('B2_APPLICATION_KEY_ID')}")
    logger.info(f"DEBUG: B2_APPLICATION_KEY from env: {os.environ.get('B2_APPLICATION_KEY')}")
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
        current_parallel_ops=current_parallel_ops,
        use_s3_api_setting=app_config.USE_S3_API
    )

@app.route('/b2_buckets') # Changed from /webhooks to avoid confusion
@login_required
def manage_b2_buckets_page(): # Renamed function for clarity
    """Page for managing B2 bucket settings, including syncing and webhook configurations."""
    try:
        # Data for this page will primarily be loaded by JavaScript via API calls
        # but we can pass initial data or config if needed.
        return render_template(
            'buckets_manage.html',
            page_title="B2 Bucket Management",
            app_config=app_config # Pass the app_config module to the template
        )
    except Exception as e:
        logger.error(f"Error loading B2 bucket management page: {str(e)}", exc_info=True)
        flash(f'Error loading page: {str(e)}', 'danger')
        return redirect(url_for('index'))

@app.route('/webhooks')
@login_required
def webhooks():
    """Webhook management page"""
    try:
        # Get existing bucket configurations
        bucket_configs = db.get_all_bucket_configurations()
        
        # Get webhook statistics
        webhook_stats = webhook_processor.get_event_summary(days=30)
        
        return render_template(
            'webhooks.html',
            page_title="Webhook Management",
            bucket_configurations=bucket_configs,
            webhook_stats=webhook_stats,
            webhook_url_info=webhook_processor.get_webhook_url()
        )
    except Exception as e:
        logger.error(f"Error loading webhooks page: {str(e)}")
        flash(f'Error loading webhook data: {str(e)}', 'danger')
        return redirect(url_for('index'))

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
    def ws_disconnect(reason=None):
        logger.info(f"WebSocket client disconnected: {request.sid}, reason: {reason}")

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

@app.route('/api/webhooks/buffer/status', methods=['GET'])
@login_required  
def get_buffer_status():
    """Get Redis buffer status and statistics"""
    try:
        if not redis_buffer:
            return jsonify({
                'redis_enabled': False,
                'message': 'Redis buffering is disabled or unavailable'
            })
        
        stats = redis_buffer.get_buffer_stats()
        return jsonify({
            'redis_enabled': True,
            'buffer_stats': stats
        })
    except Exception as e:
        logger.error(f"Error getting buffer status: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/webhooks/buffer/flush', methods=['POST'])
@login_required
def manual_flush_buffer():
    """Manually trigger immediate flush of Redis buffer to SQLite"""
    try:
        if not redis_buffer:
            return jsonify({
                'success': False,
                'message': 'Redis buffering is disabled or unavailable'
            }), 400
        
        flushed_count = redis_buffer.flush_now()
        return jsonify({
            'success': True,
            'message': f'Manually flushed {flushed_count} events to SQLite'
        })
    except Exception as e:
        logger.error(f"Error during manual flush: {e}")
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    run_app()
