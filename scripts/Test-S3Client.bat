::
:: Test script for Backblaze S3 API integration
::

@echo off
echo === Backblaze S3 API Integration Test ===

:: Check if credentials are set
if "%B2_APPLICATION_KEY_ID%"=="" (
    echo ERROR: B2_APPLICATION_KEY_ID environment variable is not set.
    echo Please set it to your Backblaze B2 Application Key ID.
    exit /b 1
)

if "%B2_APPLICATION_KEY%"=="" (
    echo ERROR: B2_APPLICATION_KEY environment variable is not set.
    echo Please set it to your Backblaze B2 Application Key.
    exit /b 1
)

:: Run the test
echo Running S3 API integration test...
python scripts/test_s3_client.py

:: Check the result
if %ERRORLEVEL% EQU 0 (
    echo Test completed successfully
    exit /b 0
) else (
    echo Test failed with error level %ERRORLEVEL%
    exit /b %ERRORLEVEL%
)
