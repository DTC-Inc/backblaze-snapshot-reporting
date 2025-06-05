#!/usr/bin/env python3
"""
Script to fix existing webhook events with incorrect timestamp formats.
This converts any timestamp that looks like milliseconds-since-epoch to ISO format.
"""

import sqlite3
import json
from datetime import datetime

def fix_webhook_timestamps(db_path='./backblaze_snapshots.db'):
    """Fix timestamp formats in existing webhook events"""
    
    print("🔧 Fixing webhook event timestamps...")
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Get all webhook events
    cursor.execute('SELECT id, timestamp, event_timestamp, raw_payload FROM webhook_events')
    events = cursor.fetchall()
    
    print(f"Found {len(events)} webhook events to check")
    
    fixed_count = 0
    for event in events:
        event_id = event['id']
        timestamp = event['timestamp']
        event_timestamp = event['event_timestamp']
        
        # Check if timestamps look like milliseconds (numeric and > year 2000 in milliseconds)
        timestamp_needs_fix = False
        event_timestamp_needs_fix = False
        
        try:
            # If it's a number > 1000000000000 (roughly year 2001 in milliseconds)
            timestamp_num = int(float(timestamp))
            if timestamp_num > 1000000000000:
                timestamp_needs_fix = True
                new_timestamp = datetime.fromtimestamp(timestamp_num / 1000.0).isoformat()
            else:
                new_timestamp = timestamp
        except (ValueError, TypeError):
            # Already a string, probably ISO format
            new_timestamp = timestamp
            
        try:
            event_timestamp_num = int(float(event_timestamp))
            if event_timestamp_num > 1000000000000:
                event_timestamp_needs_fix = True
                new_event_timestamp = datetime.fromtimestamp(event_timestamp_num / 1000.0).isoformat()
            else:
                new_event_timestamp = event_timestamp
        except (ValueError, TypeError):
            new_event_timestamp = event_timestamp
        
        if timestamp_needs_fix or event_timestamp_needs_fix:
            print(f"  Fixing event {event_id}: {timestamp} -> {new_timestamp}, {event_timestamp} -> {new_event_timestamp}")
            cursor.execute(
                'UPDATE webhook_events SET timestamp = ?, event_timestamp = ? WHERE id = ?',
                (new_timestamp, new_event_timestamp, event_id)
            )
            fixed_count += 1
    
    conn.commit()
    conn.close()
    
    print(f"✅ Fixed {fixed_count} webhook events")
    return fixed_count

def check_database_status(db_path='./backblaze_snapshots.db'):
    """Check the current state of the database"""
    
    print("📊 Database Status Check")
    print("=" * 40)
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Check webhook_events table
    cursor.execute('SELECT COUNT(*) as count FROM webhook_events')
    total_events = cursor.fetchone()['count']
    print(f"Total webhook events: {total_events}")
    
    if total_events > 0:
        # Check recent events (last 7 days)
        cursor.execute('''
            SELECT COUNT(*) as count 
            FROM webhook_events 
            WHERE event_timestamp >= date('now', '-7 days')
        ''')
        recent_count = cursor.fetchone()['count']
        print(f"Events in last 7 days: {recent_count}")
        
        # Sample a few events to see their structure
        cursor.execute('''
            SELECT bucket_name, event_type, event_timestamp, object_size 
            FROM webhook_events 
            ORDER BY id DESC 
            LIMIT 5
        ''')
        samples = cursor.fetchall()
        print("\nSample recent events:")
        for sample in samples:
            print(f"  {dict(sample)}")
    
    # Check bucket configurations
    cursor.execute('SELECT COUNT(*) as count FROM bucket_configurations')
    config_count = cursor.fetchone()['count']
    print(f"\nBucket configurations: {config_count}")
    
    if config_count > 0:
        cursor.execute('SELECT bucket_name, webhook_enabled FROM bucket_configurations')
        configs = cursor.fetchall()
        print("Configured buckets:")
        for config in configs:
            status = "enabled" if config['webhook_enabled'] else "disabled"
            print(f"  {config['bucket_name']}: {status}")
    
    conn.close()

if __name__ == "__main__":
    print("Backblaze Webhook Timestamp Fix Tool")
    print("=" * 50)
    
    # Check current status
    check_database_status()
    
    print("\n" + "=" * 50)
    
    # Fix timestamps
    fixed = fix_webhook_timestamps()
    
    print("\n" + "=" * 50)
    
    # Check status again
    check_database_status()
    
    print(f"\n🎉 Complete! Fixed {fixed} events.")
    print("\nNext steps:")
    print("1. Restart your Flask application")
    print("2. Go to the dashboard and check if data is now displaying")
    print("3. If still no data, check the Flask logs for any API errors") 