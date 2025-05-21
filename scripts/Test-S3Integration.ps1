<#
.SYNOPSIS
    Tests Backblaze B2 S3 API integration for the monitoring application.
.DESCRIPTION
    This script verifies that the S3 API integration is working properly by:
    1. Checking boto3 installation
    2. Verifying environment variables
    3. Testing connection to the Backblaze B2 S3 API endpoint
.PARAMETER EndpointUrl
    Optional custom S3 endpoint URL for Backblaze B2
.EXAMPLE
    .\Test-S3Integration.ps1
    Tests S3 API integration using default endpoint
.EXAMPLE
    .\Test-S3Integration.ps1 -EndpointUrl "https://s3.eu-central-003.backblazeb2.com"
    Tests S3 API integration using a specific endpoint
#>

param (
    [string]$EndpointUrl = "https://s3.us-west-002.backblazeb2.com"
)

# Ensure Python and required packages are installed
function Test-PythonAndBoto3 {
    Write-Host "Checking Python and boto3 installation..." -ForegroundColor Cyan
    
    try {
        $pythonVersion = python --version
        Write-Host "Python detected: $pythonVersion" -ForegroundColor Green
        
        $boto3Check = python -c "import boto3; print(f'boto3 version: {boto3.__version__}')"
        Write-Host $boto3Check -ForegroundColor Green
        return $true
    }
    catch {
        Write-Host "Error: Python or boto3 not properly installed" -ForegroundColor Red
        Write-Host "Please install boto3 with: pip install boto3" -ForegroundColor Yellow
        return $false
    }
}

# Check if required environment variables exist
function Test-EnvironmentVariables {
    Write-Host "Checking environment variables..." -ForegroundColor Cyan
    
    $keyId = $env:B2_APPLICATION_KEY_ID
    $appKey = $env:B2_APPLICATION_KEY
    
    if (-not $keyId -or -not $appKey) {
        Write-Host "Error: Missing required environment variables" -ForegroundColor Red
        Write-Host "Please set B2_APPLICATION_KEY_ID and B2_APPLICATION_KEY environment variables" -ForegroundColor Yellow
        return $false
    }
    
    Write-Host "Environment variables for Backblaze B2 credentials are set" -ForegroundColor Green
    return $true
}

# Test S3 API connectivity with a Python script
function Test-S3Connection {
    param (
        [string]$Endpoint
    )
    
    Write-Host "Testing connection to $Endpoint..." -ForegroundColor Cyan
    
    $testScript = @"
import boto3
import sys

try:
    # Initialize S3 client
    s3_client = boto3.client(
        service_name='s3',
        endpoint_url='$Endpoint',
        aws_access_key_id='$env:B2_APPLICATION_KEY_ID',
        aws_secret_access_key='$env:B2_APPLICATION_KEY'
    )
    
    # List buckets to verify connectivity
    response = s3_client.list_buckets()
    
    # Check if we can access buckets
    if 'Buckets' in response:
        print(f"Successfully connected to Backblaze B2 S3 API")
        print(f"Found {len(response['Buckets'])} bucket(s)")
        
        for bucket in response['Buckets']:
            print(f"Bucket: {bucket['Name']}")
            
        sys.exit(0)
    else:
        print("Failed to retrieve bucket list")
        sys.exit(1)
        
except Exception as e:
    print(f"Failed to connect to S3 API: {str(e)}")
    sys.exit(1)
"@

    # Save the test script to a temporary file
    $tempFile = [System.IO.Path]::GetTempFileName() + ".py"
    $testScript | Out-File -FilePath $tempFile -Encoding UTF8
    
    try {
        # Execute the test script
        $result = python $tempFile
        
        foreach ($line in $result) {
            if ($line -match "Successfully connected") {
                Write-Host $line -ForegroundColor Green
            } 
            elseif ($line -match "Bucket:") {
                Write-Host $line -ForegroundColor Cyan
            }
            elseif ($line -match "Found") {
                Write-Host $line -ForegroundColor Green
            }
            else {
                Write-Host $line
            }
        }
        
        return $LASTEXITCODE -eq 0
    }
    catch {
        Write-Host "Error executing S3 API test: $_" -ForegroundColor Red
        return $false
    }
    finally {
        # Clean up temporary file
        if (Test-Path $tempFile) {
            Remove-Item $tempFile -Force
        }
    }
}

# Main script execution
Write-Host "=== Backblaze B2 S3 API Integration Test ===" -ForegroundColor Magenta

# Test Python and boto3
if (-not (Test-PythonAndBoto3)) {
    exit 1
}

# Test environment variables
if (-not (Test-EnvironmentVariables)) {
    exit 1
}

# Test S3 connection
if (-not (Test-S3Connection -Endpoint $EndpointUrl)) {
    Write-Host "S3 API connection test failed" -ForegroundColor Red
    exit 1
}

Write-Host "All tests passed! S3 API integration is working correctly" -ForegroundColor Green
