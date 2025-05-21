#!/usr/bin/env python
"""
Database initialization script for Backblaze Snapshot Reporting.

This script ensures the database exists and has the required tables.
"""

import os
import sys
import sqlite3
import logging
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

def init_db(db_path):
    """Initialize the database with required tables"""
    logger.info(f"Initializing database at {db_path}")
    
    # Create directory if it doesn't exist
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    
    # Create database connection
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Create snapshots table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            total_storage_bytes INTEGER NOT NULL,
            total_storage_cost REAL NOT NULL,
            total_download_bytes INTEGER NOT NULL,
            total_download_cost REAL NOT NULL,
            total_api_calls INTEGER NOT NULL,
            total_api_cost REAL NOT NULL,
            total_cost REAL NOT NULL,
            raw_data TEXT NOT NULL
        )
        ''')
        
        # Create bucket snapshots table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS bucket_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_id INTEGER NOT NULL,
            bucket_name TEXT NOT NULL,
            storage_bytes INTEGER NOT NULL,
            storage_cost REAL NOT NULL,
            download_bytes INTEGER NOT NULL,
            download_cost REAL NOT NULL,
            api_calls INTEGER NOT NULL,
            api_cost REAL NOT NULL,
            total_cost REAL NOT NULL,
            FOREIGN KEY (snapshot_id) REFERENCES snapshots (id)
        )
        ''')
        
        conn.commit()
        logger.info("Database initialized successfully")
        
    except Exception as e:
        conn.rollback()
        logger.error(f"Error initializing database: {e}")
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    if len(sys.argv) > 1:
        db_path = sys.argv[1]
    else:
        # Default path
        db_path = os.environ.get('DATABASE_URI', 'sqlite:///backblaze_snapshots.db')
        if db_path.startswith('sqlite:///'):
            db_path = db_path.replace('sqlite:///', '')
    
    init_db(db_path)
    logger.info("Database initialization complete")
