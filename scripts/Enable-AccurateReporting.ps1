<#
.SYNOPSIS
    Enables or disables accurate bucket size reporting for Backblaze Snapshot Reporting tool.
.DESCRIPTION
    This script toggles between the standard and accurate bucket size calculation methods.
    The accurate method provides more comprehensive size reporting at the cost of potentially 
    more API calls and processing time.
.PARAMETER Disable
    Switch to disable accurate reporting and restore standard reporting method.
.EXAMPLE
    .\Enable-AccurateReporting.ps1
    Enables the accurate bucket size reporting feature.
.EXAMPLE
    .\Enable-AccurateReporting.ps1 -Disable
    Disables accurate reporting and restores the standard method.
#>

param (
    [switch]$Disable
)

# Get the directory where the script is located
$scriptPath = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptPath
$appDir = Join-Path $projectRoot "app"

# Define paths
$appPy = Join-Path $appDir "app.py"
$backblazeApiPy = Join-Path $appDir "backblaze_api.py"
$appImprovedPy = Join-Path $appDir "app_improved.py"
$backblazeApiImprovedPy = Join-Path $appDir "backblaze_api_improved.py"
$envFile = Join-Path $projectRoot ".env"

# Create backup directory with timestamp
$backupDir = Join-Path $projectRoot "backups"
$timestamp = Get-Date -Format "yyyyMMddHHmmss"
$backupTimestampDir = Join-Path $backupDir "backup_$timestamp"

function Create-Backup {
    param (
        [string[]]$FilesToBackup
    )
    
    # Create backup directory if it doesn't exist
    if (-not (Test-Path $backupTimestampDir)) {
        New-Item -Path $backupTimestampDir -ItemType Directory -Force | Out-Null
        Write-Host "Created backup directory: $backupTimestampDir"
    }
    
    # Backup each file
    foreach ($file in $FilesToBackup) {
        if (Test-Path $file) {
            $backupFile = Join-Path $backupTimestampDir (Split-Path -Leaf $file)
            Copy-Item -Path $file -Destination $backupFile -Force
            Write-Host "Backed up $file to $backupFile"
        }
    }
}

function Update-EnvFile {
    param (
        [bool]$EnableAccurate
    )
    
    $value = if ($EnableAccurate) { "True" } else { "False" }
    
    if (Test-Path $envFile) {
        $content = Get-Content $envFile -Raw
        
        # Check if setting already exists
        if ($content -match "USE_ACCURATE_BUCKET_SIZE=") {
            # Update existing setting
            $content = $content -replace "USE_ACCURATE_BUCKET_SIZE=.*", "USE_ACCURATE_BUCKET_SIZE=$value"
            $content | Set-Content $envFile
            Write-Host "Updated USE_ACCURATE_BUCKET_SIZE=$value in .env file"
        } else {
            # Add new setting
            "`n# Use accurate but potentially slower bucket size calculation" | Add-Content $envFile
            "USE_ACCURATE_BUCKET_SIZE=$value" | Add-Content $envFile
            Write-Host "Added USE_ACCURATE_BUCKET_SIZE=$value to .env file"
        }
    } else {
        # Create new .env file with this setting
        "# Use accurate but potentially slower bucket size calculation" | Set-Content $envFile
        "USE_ACCURATE_BUCKET_SIZE=$value" | Add-Content $envFile
        Write-Host "Created new .env file with USE_ACCURATE_BUCKET_SIZE=$value"
    }
}

# Main script execution
Write-Host "Backblaze Snapshot Reporting - Accurate Bucket Size Configuration"
Write-Host "=============================================================="

# Create backups
Create-Backup -FilesToBackup @($appPy, $backblazeApiPy)

if ($Disable) {
    # Disable accurate reporting
    Write-Host "Disabling accurate bucket size reporting..."
    
    # Check for backups to restore
    $backupDirs = Get-ChildItem -Path $backupDir -Directory | Sort-Object LastWriteTime -Descending
    
    if ($backupDirs.Count -gt 0) {
        $latestBackup = $backupDirs[0].FullName
        $appBackup = Join-Path $latestBackup "app.py"
        $apiBackup = Join-Path $latestBackup "backblaze_api.py"
        
        if ((Test-Path $appBackup) -and (Test-Path $apiBackup)) {
            Copy-Item -Path $appBackup -Destination $appPy -Force
            Copy-Item -Path $apiBackup -Destination $backblazeApiPy -Force
            Write-Host "Restored original files from backup"
            
            # Update .env file
            Update-EnvFile -EnableAccurate $false
            
            Write-Host "Accurate bucket size reporting has been successfully disabled"
        } else {
            Write-Host "Warning: Backup files not found. Cannot restore original implementation." -ForegroundColor Yellow
        }
    } else {
        Write-Host "Warning: No backup directories found. Cannot restore original implementation." -ForegroundColor Yellow
    }
} else {
    # Enable accurate reporting
    Write-Host "Enabling accurate bucket size reporting..."
    
    # Check if improved files exist
    if (-not (Test-Path $appImprovedPy) -or -not (Test-Path $backblazeApiImprovedPy)) {
        Write-Host "Error: Improved files not found. Make sure app_improved.py and backblaze_api_improved.py exist." -ForegroundColor Red
        exit 1
    }
    
    # Copy improved files over the existing ones
    Copy-Item -Path $appImprovedPy -Destination $appPy -Force
    Copy-Item -Path $backblazeApiImprovedPy -Destination $backblazeApiPy -Force
    
    # Update .env file
    Update-EnvFile -EnableAccurate $true
    
    Write-Host "Improved bucket size reporting has been successfully enabled"
}

Write-Host "`nCompleted! Remember to restart your application for changes to take effect."
if (-not $Disable) {
    Write-Host "For more details on accurate bucket size reporting, see: docs/ACCURATE_BUCKET_SIZE_REPORTING.md"
}
