"""
Database factory for choosing between SQLite and MongoDB
"""
import os
import logging
from typing import Union

logger = logging.getLogger(__name__)

def create_database(database_uri: str = None, use_mongodb: bool = False) -> Union['Database', 'MongoDatabase']:
    """
    Create database instance based on configuration
    
    Args:
        database_uri (str): Database connection URI
        use_mongodb (bool): Whether to use MongoDB instead of SQLite
        
    Returns:
        Database instance (either SQLite Database or MongoDatabase)
    """
    
    if use_mongodb or (database_uri and database_uri.startswith('mongodb://')):
        # Use MongoDB
        try:
            from app.models.mongodb_database import MongoDatabase
            logger.info("Initializing MongoDB database for high-volume webhook events")
            return MongoDatabase(database_uri)
        except ImportError as e:
            logger.error(f"MongoDB not available: {e}")
            logger.info("Install pymongo with: pip install pymongo")
            raise ImportError("MongoDB support requires pymongo. Install with: pip install pymongo")
        except Exception as e:
            logger.error(f"Failed to initialize MongoDB: {e}")
            raise
    else:
        # Use SQLite (default)
        from app.models.database import Database
        if database_uri and database_uri.startswith('sqlite:///'):
            db_path = database_uri.replace('sqlite:///', '')
        else:
            db_path = database_uri or '/data/backblaze_snapshots.db'
        
        logger.info(f"Initializing SQLite database at: {db_path}")
        return Database(db_path)

def get_database_from_config():
    """
    Create database instance from environment configuration
    
    Returns:
        Database instance based on environment variables
    """
    
    # Get configuration from environment
    database_uri = os.getenv('DATABASE_URI', 'sqlite:////data/backblaze_snapshots.db')
    use_mongodb = os.getenv('USE_MONGODB', '0').lower() in ('1', 'true', 'yes')
    
    # If using MongoDB, try to construct URI from individual environment variables
    if use_mongodb or (database_uri and database_uri.startswith('mongodb://')):
        # Check if we have individual MongoDB environment variables
        mongodb_user = os.getenv('MONGODB_USER')
        mongodb_password = os.getenv('MONGODB_PASSWORD')
        mongodb_host = os.getenv('MONGODB_HOST', 'localhost')
        mongodb_port = os.getenv('MONGODB_PORT', '27017')
        mongodb_db = os.getenv('MONGODB_DB', 'bbssr_db')
        
        # If individual variables are provided, construct the URI
        if mongodb_user and mongodb_password:
            constructed_uri = f"mongodb://{mongodb_user}:{mongodb_password}@{mongodb_host}:{mongodb_port}/{mongodb_db}?authSource=admin"
            logger.info(f"Constructed MongoDB URI from environment variables: mongodb://{mongodb_user}:***@{mongodb_host}:{mongodb_port}/{mongodb_db}?authSource=admin")
            database_uri = constructed_uri
        elif database_uri.startswith('mongodb://') and not ('?' in database_uri or '@' in database_uri):
            # DATABASE_URI is just a basic mongodb:// URI without auth, add auth from env vars
            if mongodb_user and mongodb_password:
                # Replace the basic URI with authenticated version
                basic_host_db = database_uri.replace('mongodb://', '')
                constructed_uri = f"mongodb://{mongodb_user}:{mongodb_password}@{basic_host_db}?authSource=admin"
                logger.info(f"Enhanced basic MongoDB URI with authentication from environment variables")
                database_uri = constructed_uri
    
    logger.info(f"Database configuration: URI={database_uri.replace(mongodb_password, '***') if 'mongodb_password' in locals() and mongodb_password and mongodb_password in database_uri else database_uri}, USE_MONGODB={use_mongodb}")
    
    return create_database(database_uri, use_mongodb) 