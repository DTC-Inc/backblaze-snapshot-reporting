import sys
import os

# When running inside the container, assume the app is at /app
# and modules can be imported directly if /app is the working directory or in PYTHONPATH.

try:
    from app.models.database import Database
except ImportError as e:
    print(f"Failed to import Database from app.models.database: {e}")
    print("Please ensure that when running this script inside the container, ")
    print("the Python interpreter can find the 'app' module (e.g., /app is in PYTHONPATH or is the CWD).")
    sys.exit(1)

import secrets
import json

# --- Configuration ---
# Path to the database file INSIDE THE CONTAINER
DB_FILENAME = "backblaze_snapshots.db"
CONTAINER_DATA_ROOT = "/data" # As per user confirmation
DB_PATH = os.path.join(CONTAINER_DATA_ROOT, DB_FILENAME)

# Bucket names from the test script log that need webhook configuration
BUCKET_NAMES = [
    "user-uploads-staging",
    "analytics-data-warehouse",
    "production-logs",
    "development-assets",
    "test-photos-backup"
]

# Default events to set if enabling a webhook and current events are empty or not set.
# This matches the default in Database.save_bucket_configuration if events_to_track is None.
DESIRED_DEFAULT_EVENTS = ["b2:ObjectCreated", "b2:ObjectDeleted"]


def ensure_bucket_webhook_configs():
    """
    Ensures that specified buckets have an active webhook configuration
    in the database. If a configuration exists but is disabled, it will be enabled.
    If it doesn't exist, it will be created.
    Secrets are preserved. If enabling and events_to_track is empty or missing, DESIRED_DEFAULT_EVENTS are set.
    """
    print(f"Attempting to connect to database at: {DB_PATH}")
    if not os.path.exists(os.path.dirname(DB_PATH)) and not os.path.exists(DB_PATH):
        print(f"Warning: Database file '{DB_FILENAME}' or its directory ('{os.path.dirname(DB_PATH)}') does not exist. "
              "The Database class will attempt to create the file if it's missing, along with necessary tables.")

    try:
        db = Database(db_path=DB_PATH)
        print("Database object initialized.")
    except Exception as e:
        print(f"Failed to initialize Database object: {e}")
        print("Ensure the database path is correct and permissions are set.")
        import traceback
        traceback.print_exc()
        return

    for bucket_name in BUCKET_NAMES:
        print(f"\nProcessing bucket: {bucket_name}")

        existing_config = db.get_bucket_configuration(bucket_name)
        
        if existing_config and existing_config.get('webhook_enabled'):
            current_events = existing_config.get('events_to_track')
            # Check if already enabled but events are empty, and fix it.
            if isinstance(current_events, list) and not current_events:
                print(f"  Webhook is ENABLED for {bucket_name}, but 'events_to_track' is EMPTY. Updating to default events.")
                secret_to_use = existing_config.get('webhook_secret') or secrets.token_hex(16)
                events_to_use = list(DESIRED_DEFAULT_EVENTS) # Ensure it's a mutable copy
            else:
                print(f"  Webhook is already ENABLED for {bucket_name}.")
                existing_secret = existing_config.get('webhook_secret')
                print(f"    Secret: {existing_secret if existing_secret else 'Not Set (PROBLEM!)'}")
                print(f"    Events: {json.dumps(current_events) if current_events is not None else 'Not Set (but should have default from DB)'}")
                if not current_events: # If None or other non-list falsy, good to check
                     print(f"    (Note: if events show as 'Not Set' here, the DB's get_bucket_configuration should ideally return the JSON default as a list)")
                continue # Already enabled and events are not an empty list, skip further processing by this script.
        else: # Not enabled or no config exists
            secret_to_use = None
            events_to_use = list(DESIRED_DEFAULT_EVENTS) # Default for new or enabling

            if existing_config: # Exists but not enabled
                print(f"  Found existing configuration for {bucket_name}, but webhook is DISABLED. Enabling it.")
                secret_to_use = existing_config.get('webhook_secret')
                
                # Preserve existing events if they are non-empty, otherwise use DESIRED_DEFAULT_EVENTS
                existing_events_list = existing_config.get('events_to_track')
                if isinstance(existing_events_list, list) and existing_events_list: # Check if it's a non-empty list
                    events_to_use = existing_events_list
                else:
                    print(f"    Existing events_to_track is missing or empty. Will set to: {json.dumps(DESIRED_DEFAULT_EVENTS)}")
                    events_to_use = list(DESIRED_DEFAULT_EVENTS)


                if not secret_to_use:
                    print("    No existing secret found; generating a new one.")
                    secret_to_use = secrets.token_hex(16)
                else:
                    print("    Using existing secret.")
            else: # No config exists at all
                print(f"  No existing configuration found for {bucket_name}. Creating a new one.")
                secret_to_use = secrets.token_hex(16)
                print("  Generated new secret.")
                events_to_use = list(DESIRED_DEFAULT_EVENTS) # Use default events
                print(f"    Will set events_to_track to: {json.dumps(events_to_use)}")


        try:
            print(f"  Saving configuration: webhook_enabled=True")
            # Ensure we print the actual secret value that will be used for saving
            if secret_to_use:
                print(f"    Secret to be saved: {secret_to_use}")
            else:
                print(f"    Secret to be saved: Not Set (PROBLEM! This should have been generated if missing)")
            
            print(f"    Events to Track: {json.dumps(events_to_use) if events_to_use is not None else 'Error: events_to_use is None!'}")
            
            if events_to_use is None: # Should not happen with new logic but as a safeguard
                print("  ERROR: events_to_use is None before saving. This is unexpected. Skipping save for this bucket.")
                continue

            success = db.save_bucket_configuration(
                bucket_name=bucket_name,
                webhook_enabled=True,
                webhook_secret=secret_to_use,
                events_to_track=events_to_use 
            )

            if success:
                print(f"  Successfully saved configuration for bucket: {bucket_name}")
                # Verification
                updated_config = db.get_bucket_configuration(bucket_name)
                if updated_config and updated_config.get('webhook_enabled'):
                    print(f"  VERIFIED: Webhook is ENABLED for {bucket_name}.")
                    actual_secret = updated_config.get('webhook_secret')
                    print(f"    Actual Secret: {actual_secret if actual_secret else 'Not Set (PROBLEM!)'}")
                    updated_events = updated_config.get('events_to_track')
                    print(f"    Actual Events Configured: {json.dumps(updated_events) if updated_events is not None else 'Not Set'}")
                else:
                    print(f"  VERIFICATION FAILED for {bucket_name}. Config returned: {updated_config}")
            else:
                print(f"  FAILED to save configuration for bucket: {bucket_name} (save_bucket_configuration returned False)")
        except Exception as e:
            print(f"  ERROR configuring bucket {bucket_name}: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    print("Starting script to ensure test bucket webhook configurations...")
    ensure_bucket_webhook_configs()
    print("\nScript finished.")
    print(f"Please check the output above and your database file '{DB_FILENAME}' (expected at '{DB_PATH}') to confirm the changes.") 