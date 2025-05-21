#!/usr/bin/env python3
"""
Script to validate Python syntax in the application files
"""

import os
import sys
import py_compile
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def check_file_syntax(file_path):
    """
    Check a Python file for syntax errors
    
    Returns True if no errors found, False otherwise
    """
    try:
        py_compile.compile(file_path, doraise=True)
        return True
    except py_compile.PyCompileError as e:
        logger.error(f"Syntax error in {file_path}:")
        logger.error(f"  {e}")
        return False
    except Exception as e:
        logger.error(f"Error checking {file_path}: {e}")
        return False

def validate_python_files(directory):
    """
    Check all Python files in a directory for syntax errors
    
    Returns the count of files with errors
    """
    error_count = 0
    file_count = 0
    
    for root, dirs, files in os.walk(directory):
        for file in files:
            if file.endswith('.py'):
                file_path = os.path.join(root, file)
                file_count += 1
                
                if not check_file_syntax(file_path):
                    error_count += 1
    
    return file_count, error_count

if __name__ == "__main__":
    # Get the base directory (parent of script directory)
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    app_dir = os.path.join(base_dir, "app")
    
    logger.info(f"Checking Python files in {app_dir}")
    
    file_count, error_count = validate_python_files(app_dir)
    
    logger.info(f"Checked {file_count} Python files")
    
    if error_count == 0:
        logger.info("No syntax errors found!")
        sys.exit(0)
    else:
        logger.error(f"Found {error_count} files with syntax errors")
        sys.exit(1)
