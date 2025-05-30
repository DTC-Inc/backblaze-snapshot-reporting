#!/bin/sh
set -e

# Initialize database
echo "Initializing database..."
python -m scripts.init_db /data/backblaze_snapshots.db

# Check required packages
echo "Checking required packages..."
python -c "import sys; print('Python:', sys.version); 
import flask; print('Flask:', flask.__version__); 
import flask_wtf; print('Flask-WTF available'); 
import flask_login; print('Flask-Login available'); 
import boto3; print('boto3:', boto3.__version__)" || echo "Warning: Some required packages may be missing"

# Test S3 client availability
echo "Testing S3 client availability..."
python -c "
import sys
sys.path.append('/app')
try:
    import boto3
    print('boto3 available: ' + boto3.__version__)
    from app.backblaze_s3_api_new import S3BackblazeClient
    print('S3 client available from backblaze_s3_api_new')
except ImportError:
    try:
        from app.backblaze_s3_api import S3BackblazeClient
        print('S3 client available from backblaze_s3_api')
    except ImportError:
        print('S3 client not available - some features may be limited')
except Exception as e:
    print('Error loading S3 client: ' + str(e))
"

# Execute the provided command (like gunicorn)
echo "Starting application..."
exec "$@"
