#!/bin/bash
# This script helps verify that your development environment is set up correctly

echo "===== Backblaze Snapshot Reporting Development Environment Test ====="

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo "❌ Docker is not installed or not in PATH"
    echo "   Please install Docker: https://docs.docker.com/get-docker/"
    exit 1
else
    docker_version=$(docker --version)
    echo "✅ Docker is installed: $docker_version"
fi

# Check if Docker Compose is installed
if ! command -v docker-compose &> /dev/null; then
    echo "❌ Docker Compose is not installed or not in PATH"
    echo "   Please install Docker Compose: https://docs.docker.com/compose/install/"
    exit 1
else
    compose_version=$(docker-compose --version)
    echo "✅ Docker Compose is installed: $compose_version"
fi

# Check if .env file exists
if [ ! -f ./.env ]; then
    echo "❌ .env file not found"
    echo "   Please create a .env file based on .env.example"
    echo "   Example: cp .env.example .env"
else
    echo "✅ .env file exists"
    
    # Check if B2 credentials are configured
    if grep -q "B2_APPLICATION_KEY_ID=your_key_id_here" ./.env; then
        echo "⚠️ Backblaze B2 credentials not configured in .env file"
        echo "   Please update your B2 credentials in the .env file"
    else
        echo "✅ Backblaze B2 credentials appear to be configured"
    fi
fi

# Check if development Docker Compose file exists
if [ ! -f ./docker-compose.dev.yml ]; then
    echo "❌ docker-compose.dev.yml not found"
    echo "   This file is required for development"
else
    echo "✅ docker-compose.dev.yml exists"
fi

echo ""
echo "Testing Docker configuration..."

# Try to build the Docker image
echo "Building Docker image (this might take a minute)..."
if ! docker-compose build --quiet > /dev/null 2>&1; then
    echo "❌ Failed to build Docker image"
    echo "   Run 'docker-compose build' for detailed error messages"
else
    echo "✅ Docker image built successfully"

    # Check if port 5000 is available
    if command -v nc &> /dev/null; then
        if nc -z localhost 5000 > /dev/null 2>&1; then
            echo "⚠️ Port 5000 is already in use"
            echo "   This might cause conflicts when starting the application"
        else
            echo "✅ Port 5000 is available"
        fi
    fi
fi

echo ""
echo "===== Test Complete ====="
echo ""
echo "To start the development environment:"
echo "1. docker-compose -f docker-compose.yml -f docker-compose.dev.yml up"
echo "2. Visit http://localhost:5000 in your browser"
echo ""
echo "See DEVELOPMENT.md for more detailed instructions"
