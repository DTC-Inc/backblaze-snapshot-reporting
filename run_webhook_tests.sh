#!/bin/bash

# Webhook Events Test Runner
# =========================

set -e

echo "🧪 Webhook Events Test Runner"
echo "=============================="

# Check if Python virtual environment is active
if [[ -z "$VIRTUAL_ENV" ]]; then
    echo "⚠️  Warning: No virtual environment detected. Consider activating one first."
fi

# Install test dependencies if not present (for host-side execution if any)
echo "📦 Installing test dependencies..."
pip install -q -r test_requirements.txt

# Default values
EVENTS=50
CLEAR_DATA=false
SEND_WEBHOOKS=false
TEST_DELETION=false
WEBHOOK_URL="http://localhost:5000"
CONTAINER_NAME="bbssr_web" # Default container name
APP_PATH_IN_CONTAINER="/app" # Assumed path to app in container

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --clear-data)
            CLEAR_DATA=true
            shift
            ;;
        --send-webhooks)
            SEND_WEBHOOKS=true
            shift
            ;;
        --test-deletion)
            TEST_DELETION=true
            shift
            ;;
        --events)
            EVENTS="$2"
            shift 2
            ;;
        --webhook-url)
            WEBHOOK_URL="$2"
            shift 2
            ;;
        --container-name)
            CONTAINER_NAME="$2"
            shift 2
            ;;
        --app-path)
            APP_PATH_IN_CONTAINER="$2"
            shift 2
            ;;
        --help)
            echo "Usage: $0 [options]"
            echo ""
            echo "Options:"
            echo "  --clear-data         Clear existing test data first (runs on host or container based on --send-webhooks)"
            echo "  --send-webhooks      Send actual HTTP webhook requests (runs test script IN CONTAINER)"
            echo "  --test-deletion      Test deletion API endpoints (runs test script IN CONTAINER)"
            echo "  --events N           Number of events to generate (default: 50)"
            echo "  --webhook-url URL    Base URL for webhook testing (default: http://localhost:5000)"
            echo "  --container-name NAME Container name for podman exec (default: bbssr_web)"
            echo "  --app-path PATH      Path to application within container (default: /app)"
            echo "  --help               Show this help message"
            echo ""
            echo "Examples:"
            echo "  $0                                    # Generate 50 test events (host DB)"
            echo "  $0 --clear-data --events 100         # Clear data and generate 100 events (host DB)"
            echo "  $0 --send-webhooks --webhook-url https://bbssr.bierlysmith.com # Send webhooks via container to public URL"
            echo "  $0 --clear-data --send-webhooks --webhook-url https://bbssr.bierlysmith.com # Full test with HTTP requests via container"
            echo "  $0 --test-deletion --webhook-url https://bbssr.bierlysmith.com # Test deletion via container"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# Build command arguments for test_webhook_events.py
PYTHON_SCRIPT_ARGS="--events $EVENTS --webhook-url $WEBHOOK_URL"

if [ "$CLEAR_DATA" = true ]; then
    PYTHON_SCRIPT_ARGS="$PYTHON_SCRIPT_ARGS --clear-data"
fi

if [ "$SEND_WEBHOOKS" = true ]; then
    PYTHON_SCRIPT_ARGS="$PYTHON_SCRIPT_ARGS --send-webhooks"
fi

if [ "$TEST_DELETION" = true ]; then
    # Ensure --test-deletion is passed to the python script, not just a flag for this shell script
    PYTHON_SCRIPT_ARGS="--test-deletion --webhook-url $WEBHOOK_URL"
    # If only testing deletion, other flags like --events, --clear-data might not be relevant for the python script itself
    # but let current PYHON_SCRIPT_ARGS pass them if they were set.
fi

echo "🚀 Running webhook test with arguments for python script: $PYTHON_SCRIPT_ARGS"
echo ""

# Determine how to run the test script
if [ "$SEND_WEBHOOKS" = true ] || [ "$TEST_DELETION" = true ] ; then
    echo "🔩 Executing test_webhook_events.py inside container '$CONTAINER_NAME'..."
    echo "   Targeting webhook URL: $WEBHOOK_URL"
    # Ensure the script path inside the container is correct.
    # Assuming test_webhook_events.py is at the root of APP_PATH_IN_CONTAINER
    SCRIPT_IN_CONTAINER="${APP_PATH_IN_CONTAINER}/test_webhook_events.py"
    
    # DATABASE_URI for the container's perspective, pointing to the DB in /data
    CONTAINER_DB_URI="sqlite:////data/backblaze_snapshots.db"

    podman exec -e DATABASE_URI="$CONTAINER_DB_URI" "$CONTAINER_NAME" python "$SCRIPT_IN_CONTAINER" $PYTHON_SCRIPT_ARGS
else
    echo "💻 Executing test_webhook_events.py on the host..."
    echo "   (This will likely use the local ./backblaze_snapshots.db unless DATABASE_URI env var is set for host)"
    python test_webhook_events.py $PYTHON_SCRIPT_ARGS
fi

echo ""
echo "🎉 Test completed!"
if [ "$SEND_WEBHOOKS" = false ] && [ "$TEST_DELETION" = false ]; then
    echo "   (Data generated in host's database)"
else
    echo "   (Operations performed using/against container's database at /data/backblaze_snapshots.db)"
fi
echo "   If webhooks were sent, check your webhook events page, e.g., ${WEBHOOK_URL}/webhook_events" 