#!/usr/bin/env python3
"""
Database initialization script
Creates the initial database and tables if they don't exist

Usage:
    python -m scripts.init_db [database_path]
"""

import os
import sys
import logging

# Add the app directory to the path so we can import our modules
sys.path.insert(0, '/app')

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def init_database(db_path=None):
    """Initialize the database with required tables"""
    try:
        # Import our database class
        from app.models.database import Database
        
        # Use provided path or default
        if not db_path:
            db_path = os.getenv('SQLITE_PATH', '/data/backblaze_snapshots.db')
        
        logger.info(f"Initializing database at: {db_path}")
        
        # Ensure the directory exists
        db_dir = os.path.dirname(db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)
            logger.info(f"Created directory: {db_dir}")
        
        # Check if we can write to the directory
        if not os.access(db_dir, os.W_OK):
            logger.error(f"Cannot write to directory: {db_dir}")
            return False
        
        # Initialize the database (this will create tables if they don't exist)
        db = Database(db_path)
        
        # Test basic functionality
        with db._get_connection() as conn:
            cursor = conn.cursor()
            
            # Check that tables were created
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]
            
            logger.info(f"Database initialized with tables: {tables}")
            
            if not tables:
                logger.warning("No tables found in database - this may indicate an issue")
                return False
            
            # Basic connectivity test
            cursor.execute("SELECT 1")
            result = cursor.fetchone()
            if result and result[0] == 1:
                logger.info("✓ Database connectivity test passed")
            else:
                logger.error("✗ Database connectivity test failed")
                return False
        
        logger.info(f"✓ Database successfully initialized at {db_path}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        return False

def main():
    """Main function for command line usage"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Initialize the BBSSR database")
    parser.add_argument('database_path', nargs='?', 
                       help='Path to the database file (default: from environment or /data/backblaze_snapshots.db)')
    
    args = parser.parse_args()
    
    success = init_database(args.database_path)
    
    if success:
        logger.info("Database initialization completed successfully")
        sys.exit(0)
    else:
        logger.error("Database initialization failed")
        sys.exit(1)

if __name__ == '__main__':
    main()
