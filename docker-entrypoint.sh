#!/bin/sh
set -e

# Debug: Print current user and initial /data permissions
echo "Entrypoint script running as: $(id)"
echo "Initial permissions of /data:"
ls -ld /data || echo "/data does not exist or cannot be listed initially"

# Try to ensure /data is writable by appuser, but don't fail if we can't change ownership
echo "Attempting to set ownership of /data to appuser..."
if chown appuser:appuser /data 2>/dev/null; then
    echo "✓ Successfully changed ownership of /data"
else
    echo "⚠ Cannot change ownership of /data (this is normal for rootless containers)"
    echo "Checking if /data is writable..."
    if [ -w /data ]; then
        echo "✓ /data is writable"
    else
        echo "✗ /data is not writable - this may cause issues"
        echo "Please ensure the host directory has correct permissions:"
        echo "  sudo chown -R $(id -u):$(id -g) ./data"
        echo "  or"
        echo "  chmod 777 ./data"
    fi
fi

echo "Final permissions of /data:"
ls -ld /data

# Create necessary subdirectories if they don't exist
echo "Creating necessary subdirectories..."
mkdir -p /data/backups || echo "Could not create /data/backups (may already exist or lack permissions)"
mkdir -p /data/cache || echo "Could not create /data/cache (may already exist or lack permissions)"

# Initialize database if it doesn't exist
if [ ! -f /data/backblaze_snapshots.db ]; then
    echo "Database not found, initializing..."
    if python -m scripts.init_db /data/backblaze_snapshots.db 2>/dev/null; then
        echo "✓ Database initialized successfully"
    else
        echo "⚠ Could not initialize database (may be permissions issue)"
        echo "Will attempt to create database when application starts"
    fi
else
    echo "✓ Database already exists"
fi

echo "Contents and permissions of /data:"
ls -al /data || echo "Cannot list /data contents"

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
