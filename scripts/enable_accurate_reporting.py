#!/usr/bin/env python3
"""
This script enables the improved bucket size reporting functionality by:
1. Copying the improved files to the appropriate locations
2. Adding the necessary configuration settings
3. Setting up environment variables
"""

import os
import shutil
import logging
import argparse
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Define paths
APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKUP_DIR = os.path.join(APP_DIR, 'backups', f'backup_{datetime.now().strftime("%Y%m%d%H%M%S")}')

def create_backup(files_to_backup):
    """Create backup of files before modifying them"""
    if not os.path.exists(BACKUP_DIR):
        os.makedirs(BACKUP_DIR)
        logger.info(f"Created backup directory: {BACKUP_DIR}")
    
    for file_path in files_to_backup:
        if os.path.exists(file_path):
            backup_path = os.path.join(BACKUP_DIR, os.path.basename(file_path))
            shutil.copy2(file_path, backup_path)
            logger.info(f"Backed up {file_path} to {backup_path}")

def enable_improved_reporting(use_improved=True):
    """Enable or disable the improved bucket size reporting"""
    app_dir = os.path.join(APP_DIR, 'app')
    
    # Files to modify
    app_py = os.path.join(app_dir, 'app.py')
    backblaze_api_py = os.path.join(app_dir, 'backblaze_api.py')
    app_improved_py = os.path.join(app_dir, 'app_improved.py')
    backblaze_api_improved_py = os.path.join(app_dir, 'backblaze_api_improved.py')
    
    # Create backups
    create_backup([app_py, backblaze_api_py])
    
    if use_improved:
        # Check if improved files exist
        if not os.path.exists(app_improved_py) or not os.path.exists(backblaze_api_improved_py):
            logger.error("Improved files not found. Make sure app_improved.py and backblaze_api_improved.py exist.")
            return False
            
        # Copy improved files over the existing ones
        shutil.copy2(app_improved_py, app_py)
        shutil.copy2(backblaze_api_improved_py, backblaze_api_py)
        logger.info("Installed improved bucket size reporting code")
        
        # Update .env file if it exists, otherwise create it
        env_file = os.path.join(APP_DIR, '.env')
        env_content = ""
        
        if os.path.exists(env_file):
            with open(env_file, 'r') as f:
                env_content = f.read()
                
            # Check if USE_ACCURATE_BUCKET_SIZE is already in the .env file
            if 'USE_ACCURATE_BUCKET_SIZE' not in env_content:
                with open(env_file, 'a') as f:
                    f.write("\n# Use accurate but potentially slower bucket size calculation\n")
                    f.write("USE_ACCURATE_BUCKET_SIZE=True\n")
                logger.info("Added USE_ACCURATE_BUCKET_SIZE=True to .env file")
            else:
                # Update the existing value
                lines = env_content.splitlines()
                updated = False
                with open(env_file, 'w') as f:
                    for line in lines:
                        if line.startswith('USE_ACCURATE_BUCKET_SIZE='):
                            f.write("USE_ACCURATE_BUCKET_SIZE=True\n")
                            updated = True
                        else:
                            f.write(f"{line}\n")
                if updated:
                    logger.info("Updated USE_ACCURATE_BUCKET_SIZE=True in .env file")
        else:
            # Create new .env file with just this setting
            with open(env_file, 'w') as f:
                f.write("# Use accurate but potentially slower bucket size calculation\n")
                f.write("USE_ACCURATE_BUCKET_SIZE=True\n")
            logger.info("Created new .env file with USE_ACCURATE_BUCKET_SIZE=True")
        
        logger.info("Improved bucket size reporting has been successfully enabled")
    else:
        # Restore from backups if they exist
        app_backup = os.path.join(BACKUP_DIR, 'app.py')
        api_backup = os.path.join(BACKUP_DIR, 'backblaze_api.py')
        
        if os.path.exists(app_backup) and os.path.exists(api_backup):
            shutil.copy2(app_backup, app_py)
            shutil.copy2(api_backup, backblaze_api_py)
            logger.info("Restored original files from backup")
            
            # Update .env file to disable accurate calculation
            env_file = os.path.join(APP_DIR, '.env')
            if os.path.exists(env_file):
                with open(env_file, 'r') as f:
                    env_content = f.read()
                
                lines = env_content.splitlines()
                with open(env_file, 'w') as f:
                    for line in lines:
                        if line.startswith('USE_ACCURATE_BUCKET_SIZE='):
                            f.write("USE_ACCURATE_BUCKET_SIZE=False\n")
                        else:
                            f.write(f"{line}\n")
                logger.info("Updated USE_ACCURATE_BUCKET_SIZE=False in .env file")
                
            logger.info("Improved bucket size reporting has been successfully disabled")
        else:
            logger.error("Backup files not found. Cannot restore original implementation.")
            return False
            
    return True

def main():
    parser = argparse.ArgumentParser(description="Enable or disable improved bucket size reporting")
    parser.add_argument('--disable', action='store_true', help='Disable improved reporting and restore original files')
    args = parser.parse_args()
    
    if args.disable:
        enable_improved_reporting(use_improved=False)
    else:
        enable_improved_reporting(use_improved=True)

if __name__ == "__main__":
    main()
