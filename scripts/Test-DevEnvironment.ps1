# This script helps verify that your development environment is set up correctly for Windows/WSL2

Write-Host "===== Backblaze Snapshot Reporting Development Environment Test ====="

# Check if WSL is installed and enabled
$wslStatus = (wsl --status) 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ WSL is not installed or not enabled"
    Write-Host "   Please install WSL2: https://docs.microsoft.com/en-us/windows/wsl/install"
} else {
    Write-Host "✅ WSL is installed and enabled"
    
    # Check default WSL distribution
    $defaultDistro = (wsl -l -v | Select-String -Pattern '\*') -Replace '\s+\*\s+', ''
    if ($defaultDistro) {
        Write-Host "✅ Default WSL distribution: $defaultDistro"
    } else {
        Write-Host "❌ No default WSL distribution found"
        Write-Host "   Please install Ubuntu or another Linux distribution through WSL"
    }
}

# Check if Docker Desktop is installed
try {
    $dockerVersion = (docker --version) 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✅ Docker is installed: $dockerVersion"
        
        # Check if Docker is running
        $dockerInfo = (docker info) 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Host "✅ Docker is running"
        } else {
            Write-Host "❌ Docker is installed but not running"
            Write-Host "   Please start Docker Desktop"
        }
    } else {
        Write-Host "❌ Docker is not installed or not in PATH"
        Write-Host "   Please install Docker Desktop: https://docs.docker.com/desktop/windows/install/"
    }
} catch {
    Write-Host "❌ Docker is not installed or not in PATH"
    Write-Host "   Please install Docker Desktop: https://docs.docker.com/desktop/windows/install/"
}

# Check if Docker Compose is available
try {
    $composeVersion = (docker-compose --version) 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✅ Docker Compose is available: $composeVersion"
    } else {
        Write-Host "❌ Docker Compose is not available"
        Write-Host "   It should be included with Docker Desktop"
    }
} catch {
    Write-Host "❌ Docker Compose is not available"
    Write-Host "   It should be included with Docker Desktop"
}

# Check if .env file exists
if (Test-Path -Path ".\.env") {
    Write-Host "✅ .env file exists"
    
    # Check if B2 credentials are configured
    $envContent = Get-Content -Path ".\.env" -Raw
    if ($envContent -match "B2_APPLICATION_KEY_ID=your_key_id_here") {
        Write-Host "⚠️ Backblaze B2 credentials not configured in .env file"
        Write-Host "   Please update your B2 credentials in the .env file"
    } else {
        Write-Host "✅ Backblaze B2 credentials appear to be configured"
    }
} else {
    Write-Host "❌ .env file not found"
    Write-Host "   Please create a .env file based on .env.example"
    Write-Host "   Example: Copy-Item .env.example .env"
}

# Check if development Docker Compose file exists
if (Test-Path -Path ".\docker-compose.dev.yml") {
    Write-Host "✅ docker-compose.dev.yml exists"
} else {
    Write-Host "❌ docker-compose.dev.yml not found"
    Write-Host "   This file is required for development"
}

# Check if VS Code is installed
$vscodePath = "$env:LOCALAPPDATA\Programs\Microsoft VS Code\Code.exe"
if (Test-Path -Path $vscodePath) {
    Write-Host "✅ Visual Studio Code is installed"
} else {
    Write-Host "⚠️ Visual Studio Code not found in standard location"
    Write-Host "   VS Code is recommended for development"
    Write-Host "   https://code.visualstudio.com/"
}

# Check if port 5000 is available
$portInUse = Get-NetTCPConnection -LocalPort 5000 -ErrorAction SilentlyContinue
if ($portInUse) {
    Write-Host "⚠️ Port 5000 is already in use"
    Write-Host "   This might cause conflicts when starting the application"
} else {
    Write-Host "✅ Port 5000 is available"
}

Write-Host ""
Write-Host "Testing Docker configuration..."

# Try to build the Docker image
Write-Host "Building Docker image (this might take a minute)..."
try {
    $buildOutput = (docker-compose build) 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✅ Docker image built successfully"
    } else {
        Write-Host "❌ Failed to build Docker image"
        Write-Host "   Run 'docker-compose build' for detailed error messages"
    }
} catch {
    Write-Host "❌ Failed to build Docker image"
    Write-Host "   Run 'docker-compose build' for detailed error messages"
}

Write-Host ""
Write-Host "===== Test Complete ====="
Write-Host ""
Write-Host "To start the development environment:"
Write-Host "1. docker-compose -f docker-compose.yml -f docker-compose.dev.yml up"
Write-Host "2. Visit http://localhost:5000 in your browser"
Write-Host ""
Write-Host "See DEVELOPMENT.md for more detailed instructions"
