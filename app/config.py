import os
import tempfile
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Backblaze B2 API credentials
B2_APPLICATION_KEY_ID = os.getenv('B2_APPLICATION_KEY_ID')
B2_APPLICATION_KEY = os.getenv('B2_APPLICATION_KEY')

# Database settings
DATABASE_URI = os.getenv('DATABASE_URI', 'sqlite:////data/backblaze_snapshots.db')

# Snapshot settings
SNAPSHOT_INTERVAL_HOURS = int(os.getenv('SNAPSHOT_INTERVAL_HOURS', '24'))
SNAPSHOT_SCHEDULE_TYPE = os.getenv('SNAPSHOT_SCHEDULE_TYPE', 'weekly')  # 'interval', 'daily', 'weekly', 'monthly'
SNAPSHOT_HOUR = int(os.getenv('SNAPSHOT_HOUR', '0'))  # Hour of day for scheduled snapshots (0-23)
SNAPSHOT_MINUTE = int(os.getenv('SNAPSHOT_MINUTE', '0'))  # Minute of hour for scheduled snapshots (0-59)
SNAPSHOT_DAY_OF_WEEK = int(os.getenv('SNAPSHOT_DAY_OF_WEEK', '6'))  # Day of week for weekly snapshots (0=Monday, 6=Sunday)
SNAPSHOT_DAY_OF_MONTH = int(os.getenv('SNAPSHOT_DAY_OF_MONTH', '1'))  # Day of month for monthly snapshots (1-31)
SNAPSHOT_RETAIN_DAYS = int(os.getenv('SNAPSHOT_RETAIN_DAYS', '90'))  # Days to keep snapshot data

# Alert threshold for cost changes (percentage)
COST_CHANGE_THRESHOLD = float(os.getenv('COST_CHANGE_THRESHOLD', '10.0'))

# Email notification settings
EMAIL_ENABLED = os.getenv('EMAIL_ENABLED', 'False').lower() in ('true', '1', 't')
EMAIL_SENDER = os.getenv('EMAIL_SENDER', '')
EMAIL_RECIPIENTS = os.getenv('EMAIL_RECIPIENTS', '').split(',') if os.getenv('EMAIL_RECIPIENTS') else []
EMAIL_SERVER = os.getenv('EMAIL_SERVER', '')
EMAIL_PORT = int(os.getenv('EMAIL_PORT', '587'))
EMAIL_USERNAME = os.getenv('EMAIL_USERNAME', '')
EMAIL_PASSWORD = os.getenv('EMAIL_PASSWORD', '')
EMAIL_USE_TLS = os.getenv('EMAIL_USE_TLS', 'True').lower() in ('true', '1', 't')
EMAIL_USE_SSL = os.getenv('EMAIL_USE_SSL', 'False').lower() in ('true', '1', 't')

# Backblaze B2 pricing settings (can be overridden through environment variables)
STORAGE_COST_PER_GB = float(os.getenv('STORAGE_COST_PER_GB', '0.005'))  # $0.005 per GB per month
DOWNLOAD_COST_PER_GB = float(os.getenv('DOWNLOAD_COST_PER_GB', '0.01'))  # $0.01 per GB
CLASS_A_TRANSACTION_COST = float(os.getenv('CLASS_A_TRANSACTION_COST', '0.004')) # Cost per 1,000 Class A transactions
CLASS_B_TRANSACTION_COST = float(os.getenv('CLASS_B_TRANSACTION_COST', '0.004')) # Cost per 1,000 Class B transactions
CLASS_C_TRANSACTION_COST = float(os.getenv('CLASS_C_TRANSACTION_COST', '0.004')) # Cost per 1,000 Class C transactions (typically free, but good to have)

# Number of parallel operations for processing buckets during snapshot
PARALLEL_BUCKET_OPERATIONS = int(os.getenv('PARALLEL_BUCKET_OPERATIONS', '32'))

# API Caching
API_CACHE_TTL = int(os.getenv('API_CACHE_TTL', '3600'))  # Cache API responses for 1 hour by default
SNAPSHOT_CACHE_DIR = os.getenv('SNAPSHOT_CACHE_DIR', os.path.join(tempfile.gettempdir(), 'backblaze_snapshots'))
MAX_FILES_PER_BUCKET = int(os.getenv('MAX_FILES_PER_BUCKET', '10000'))  # Limit file listing to save API calls
BUCKET_STATS_CACHE_HOURS = int(os.getenv('BUCKET_STATS_CACHE_HOURS', '24'))  # Cache bucket stats for 24 hours
USE_ACCURATE_BUCKET_SIZE = os.getenv('USE_ACCURATE_BUCKET_SIZE', 'True').lower() in ('true', '1', 't')  # Use accurate but slower bucket size calculation
USE_S3_API = os.getenv('USE_S3_API', 'True').lower() in ('true', '1', 't')  # Use S3 API for even more accurate bucket statistics

# Object Metadata Cache Configuration
CACHE_ENABLED = True
CACHE_DIR = 'instance/cache/object_metadata'  # Relative to the Flask instance path
CACHE_TTL_SECONDS = 86400  # 1 day

# Web application settings
DEBUG = os.getenv('DEBUG', 'False').lower() in ('true', '1', 't')
SECRET_KEY = os.getenv('SECRET_KEY', 'default-dev-key-change-in-production')
HOST = os.getenv('HOST', '0.0.0.0')
PORT = int(os.getenv('PORT', '5000'))
APP_PUBLIC_URL = os.getenv('APP_PUBLIC_URL', '') # The public base URL of this application

# Webhook settings
WEBHOOK_ENABLED = os.getenv('WEBHOOK_ENABLED', 'True').lower() in ('true', '1', 't')
WEBHOOK_SECRET_AUTO_GENERATE = os.getenv('WEBHOOK_SECRET_AUTO_GENERATE', 'True').lower() in ('true', '1', 't')
WEBHOOK_DEFAULT_EVENTS = os.getenv('WEBHOOK_DEFAULT_EVENTS', 'b2:ObjectCreated:*,b2:ObjectDeleted:*').split(',')

# Redis Settings for Event Buffering
REDIS_URL = os.getenv('REDIS_URL', 'redis://redis:6379/0')  # Default to Docker service name
REDIS_FLUSH_INTERVAL = int(os.getenv('REDIS_FLUSH_INTERVAL', '10'))  # seconds
REDIS_ENABLED = os.getenv('REDIS_ENABLED', 'true').lower() == 'true'

# Create cache directory if it doesn't exist
os.makedirs(SNAPSHOT_CACHE_DIR, exist_ok=True)
