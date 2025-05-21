# Test the S3 API integration in Docker
# This script sets up credentials and runs the test_docker_s3_api.py script
#
# IMPORTANT: For S3 API compatibility, you need to use appropriate Backblaze B2 application keys
# See: https://www.backblaze.com/docs/cloud-storage-s3-compatible-app-keys
#
# Your application key should:
# 1. Have appropriate bucket access permissions
# 2. Not be restricted to specific paths within buckets
# 3. Allow both read and write operations if you want full functionality

# Check if credentials are present in .env file
if (Test-Path -Path ".\.env") {
    $envContent = Get-Content ".\.env" -ErrorAction SilentlyContinue
    $hasKeyId = $envContent -match "B2_APPLICATION_KEY_ID="
    $hasAppKey = $envContent -match "B2_APPLICATION_KEY="
    
    if (!$hasKeyId -or !$hasAppKey) {
        Write-Host "⚠️ Credentials not found in .env file" -ForegroundColor Yellow
        Write-Host "Please enter your Backblaze B2 credentials:"
        
        $KeyId = Read-Host -Prompt "B2 Application Key ID"
        $AppKey = Read-Host -Prompt "B2 Application Key" -AsSecureString
        
        # Convert secure string to plain text (only for environment variable)
        $BSTR = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($AppKey)
        $AppKeyPlaintext = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($BSTR)
        
        # Set environment variables for the current process
        $env:B2_APPLICATION_KEY_ID = $KeyId
        $env:B2_APPLICATION_KEY = $AppKeyPlaintext
        
        # Clean up the plain text version
        [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($BSTR)
    }
    else {
        Write-Host "✅ Loading credentials from .env file" -ForegroundColor Green
        # Parse the .env file manually and set environment variables
        foreach ($line in $envContent) {
            if ($line.Trim().StartsWith("#")) { continue } # Skip comments
            if ($line.Trim() -eq "") { continue } # Skip empty lines
            
            $keyValue = $line -split "=", 2
            if ($keyValue.Length -eq 2) {
                $key = $keyValue[0].Trim()
                $value = $keyValue[1].Trim()
                
                # Remove quotes if present
                $value = $value -replace '^"(.*)"$', '$1'
                $value = $value -replace "^'(.*)'$", '$1'
                
                # Set environment variable if it's one of the B2 credentials
                if ($key -eq "B2_APPLICATION_KEY_ID" -or $key -eq "B2_APPLICATION_KEY") {
                    [Environment]::SetEnvironmentVariable($key, $value, "Process")
                    Write-Host "  - Set $key environment variable" -ForegroundColor Gray
                }
            }
        }
    }
}
else {
    Write-Host "⚠️ .env file not found" -ForegroundColor Yellow
    Write-Host "Please enter your Backblaze B2 credentials:"
    
    $KeyId = Read-Host -Prompt "B2 Application Key ID"
    $AppKey = Read-Host -Prompt "B2 Application Key" -AsSecureString
    
    # Convert secure string to plain text (only for environment variable)
    $BSTR = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($AppKey)
    $AppKeyPlaintext = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($BSTR)
    
    # Set environment variables for the current process
    $env:B2_APPLICATION_KEY_ID = $KeyId
    $env:B2_APPLICATION_KEY = $AppKeyPlaintext
    
    # Clean up the plain text version
    [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($BSTR)
}

# Run the test script
Write-Host "🚀 Starting S3 API integration test in Docker" -ForegroundColor Cyan
python .\scripts\test_docker_s3_api.py

# Check the result
if ($LASTEXITCODE -eq 0) {
    Write-Host "✅ Test completed successfully" -ForegroundColor Green
}
else {
    Write-Host "❌ Test failed" -ForegroundColor Red
}
