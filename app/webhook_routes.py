from flask import Blueprint, request, jsonify, render_template, current_app
from flask_login import login_required
from datetime import datetime, timezone, timedelta
import logging
import json
import hmac
import hashlib

webhook_bp = Blueprint('webhook', __name__)
logger = logging.getLogger('webhook')

def get_database():
    """Get database instance from current app"""
    return current_app.config.get('DATABASE_INSTANCE')

@webhook_bp.route('/webhook_events')
@login_required
def webhook_events_page():
    """Webhook events monitoring page"""
    return render_template('webhook_events.html', page_title='Webhook Events Monitor')

@webhook_bp.route('/api/webhook_events/list')
@login_required
def get_webhook_events():
    """Get webhook events with optional filtering"""
    try:
        db = get_database()
        if not db:
            return jsonify({'success': False, 'error': 'Database not available'}), 500
        
        # Get query parameters
        limit = request.args.get('limit', 100, type=int)
        bucket_name = request.args.get('bucket', None)
        event_type = request.args.get('event_type', None)
        time_range = request.args.get('time_range', 'all')
        
        # Use the existing database method
        events = db.get_webhook_events(
            limit=limit,
            bucket_name=bucket_name,
            event_type=event_type
        )
        
        # Apply time range filter
        if time_range != 'all':
            now = datetime.now(timezone.utc)
            cutoff = None
            
            if time_range == '1h':
                cutoff = now - timedelta(hours=1)
            elif time_range == '24h':
                cutoff = now - timedelta(hours=24)
            elif time_range == '7d':
                cutoff = now - timedelta(days=7)
            
            if cutoff:
                events = [event for event in events 
                         if datetime.fromisoformat(event['timestamp'].replace('Z', '+00:00')) >= cutoff]
        
        # Convert to proper format for frontend
        events_data = []
        for event in events:
            # Parse raw payload if it's a string
            raw_payload = event.get('raw_payload', '{}')
            if isinstance(raw_payload, str):
                try:
                    payload_data = json.loads(raw_payload)
                except:
                    payload_data = {}
            else:
                payload_data = raw_payload
            
            events_data.append({
                'id': event['id'],
                'request_id': event.get('request_id', event['id']),
                'event_type': event['event_type'],
                'bucket_name': event['bucket_name'],
                'object_key': event.get('object_key', 'Unknown'),
                'object_size': event.get('object_size', 0),
                'timestamp': event['created_at'],
                'b2_event_timestamp': event['event_timestamp'],
                'raw_payload': payload_data
            })
        
        return jsonify({
            'success': True,
            'events': events_data,
            'total': len(events_data)
        })
    
    except Exception as e:
        logger.error(f"Error fetching webhook events: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@webhook_bp.route('/api/webhook_events/stats')
@login_required
def get_webhook_events_stats():
    """Get webhook events statistics"""
    try:
        db = get_database()
        if not db:
            return jsonify({'success': False, 'error': 'Database not available'}), 500
        
        time_range = request.args.get('time_range', '24h')
        
        # Get days value for the database method
        days = 1
        if time_range == '1h':
            days = 1  # Still use 1 day and filter in memory
        elif time_range == '24h':
            days = 1
        elif time_range == '7d':
            days = 7
        
        # Use existing database method
        stats = db.get_webhook_statistics(days=days)
        
        # Calculate totals from the stats
        total_events = sum(stat['event_count'] for stat in stats)
        created_events = sum(stat['event_count'] for stat in stats 
                           if 'Created' in stat['event_type'])
        deleted_events = sum(stat['event_count'] for stat in stats 
                           if 'Deleted' in stat['event_type'])
        unique_buckets = len(set(stat['bucket_name'] for stat in stats))
        
        return jsonify({
            'success': True,
            'stats': {
                'total_events': total_events,
                'created_events': created_events,
                'deleted_events': deleted_events,
                'unique_buckets': unique_buckets
            }
        })
    
    except Exception as e:
        logger.error(f"Error fetching webhook events stats: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@webhook_bp.route('/api/webhook_events/bucket/<bucket_name>')
@login_required  
def get_bucket_events(bucket_name):
    """Get events for a specific bucket"""
    try:
        db = get_database()
        if not db:
            return jsonify({'success': False, 'error': 'Database not available'}), 500
        
        limit = request.args.get('limit', 50, type=int)
        
        events = db.get_webhook_events(
            limit=limit,
            bucket_name=bucket_name
        )
        
        # Convert to proper format for frontend
        events_data = []
        for event in events:
            # Parse raw payload if it's a string
            raw_payload = event.get('raw_payload', '{}')
            if isinstance(raw_payload, str):
                try:
                    payload_data = json.loads(raw_payload)
                except:
                    payload_data = {}
            else:
                payload_data = raw_payload
            
            events_data.append({
                'id': event['id'],
                'request_id': event.get('request_id', event['id']),
                'event_type': event['event_type'],
                'bucket_name': event['bucket_name'],
                'object_key': event.get('object_key', 'Unknown'),
                'object_size': event.get('object_size', 0),
                'timestamp': event['created_at'],
                'b2_event_timestamp': event['event_timestamp'],
                'raw_payload': payload_data
            })
        
        return jsonify({
            'success': True,
            'bucket_name': bucket_name,
            'events': events_data,
            'total': len(events_data)
        })
    
    except Exception as e:
        logger.error(f"Error fetching events for bucket {bucket_name}: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@webhook_bp.route('/api/webhook_events/delete', methods=['DELETE'])
@login_required
def delete_webhook_events():
    """Delete webhook events with various filtering options"""
    try:
        db = get_database()
        if not db:
            return jsonify({'success': False, 'error': 'Database not available'}), 500
        
        data = request.get_json() or {}
        
        # Get deletion criteria from request
        event_ids = data.get('event_ids', [])  # List of specific event IDs
        bucket_name = data.get('bucket_name')
        event_type = data.get('event_type') 
        before_date = data.get('before_date')  # ISO format date
        after_date = data.get('after_date')   # ISO format date
        delete_all = data.get('delete_all', False)
        
        if not any([event_ids, bucket_name, event_type, before_date, after_date, delete_all]):
            return jsonify({
                'success': False,
                'error': 'No deletion criteria specified'
            }), 400
        
        with db._get_connection() as conn:
            cursor = conn.cursor()
            
            # Build DELETE query with WHERE conditions
            conditions = []
            params = []
            
            if event_ids:
                placeholders = ','.join(['?' for _ in event_ids])
                conditions.append(f'id IN ({placeholders})')
                params.extend(event_ids)
            
            if bucket_name:
                conditions.append('bucket_name = ?')
                params.append(bucket_name)
            
            if event_type:
                conditions.append('event_type = ?')
                params.append(event_type)
            
            if before_date:
                conditions.append('timestamp < ?')
                params.append(before_date)
                
            if after_date:
                conditions.append('timestamp > ?')
                params.append(after_date)
            
            if delete_all and not conditions:
                # Only allow delete all if explicitly requested and no other conditions
                query = 'DELETE FROM webhook_events'
                cursor.execute(query)
            elif conditions:
                where_clause = ' AND '.join(conditions)
                query = f'DELETE FROM webhook_events WHERE {where_clause}'
                cursor.execute(query, params)
            else:
                return jsonify({
                    'success': False,
                    'error': 'Invalid deletion criteria'
                }), 400
            
            deleted_count = cursor.rowcount
            conn.commit()
            
            # Also clean up related statistics if needed
            if deleted_count > 0:
                # Recalculate webhook statistics
                cursor.execute('DELETE FROM webhook_statistics')
                
                # Rebuild statistics from remaining events
                cursor.execute('''
                    INSERT OR REPLACE INTO webhook_statistics (date, bucket_name, event_type, event_count)
                    SELECT 
                        DATE(timestamp) as date,
                        bucket_name,
                        event_type,
                        COUNT(*) as event_count
                    FROM webhook_events
                    GROUP BY DATE(timestamp), bucket_name, event_type
                ''')
                conn.commit()
        
        return jsonify({
            'success': True,
            'message': f'Successfully deleted {deleted_count} events',
            'deleted_count': deleted_count
        })
    
    except Exception as e:
        logger.error(f"Error deleting webhook events: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@webhook_bp.route('/api/webhook_events/delete/bucket/<bucket_name>', methods=['DELETE'])
@login_required
def delete_bucket_events(bucket_name):
    """Delete all events for a specific bucket"""
    try:
        db = get_database()
        if not db:
            return jsonify({'success': False, 'error': 'Database not available'}), 500
        
        with db._get_connection() as conn:
            cursor = conn.cursor()
            
            # Delete events for the bucket
            cursor.execute('DELETE FROM webhook_events WHERE bucket_name = ?', (bucket_name,))
            deleted_count = cursor.rowcount
            
            # Clean up statistics for this bucket
            cursor.execute('DELETE FROM webhook_statistics WHERE bucket_name = ?', (bucket_name,))
            
            conn.commit()
        
        return jsonify({
            'success': True,
            'message': f'Successfully deleted {deleted_count} events for bucket {bucket_name}',
            'deleted_count': deleted_count,
            'bucket_name': bucket_name
        })
    
    except Exception as e:
        logger.error(f"Error deleting events for bucket {bucket_name}: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@webhook_bp.route('/api/webhook_events/delete/old', methods=['DELETE'])
@login_required
def delete_old_events():
    """Delete events older than specified days"""
    try:
        db = get_database()
        if not db:
            return jsonify({'success': False, 'error': 'Database not available'}), 500
        
        data = request.get_json() or {}
        days = data.get('days', 30)  # Default to 30 days
        
        if days <= 0:
            return jsonify({
                'success': False,
                'error': 'Days must be a positive number'
            }), 400
        
        cutoff_date = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        
        with db._get_connection() as conn:
            cursor = conn.cursor()
            
            # Delete old events
            cursor.execute('DELETE FROM webhook_events WHERE timestamp < ?', (cutoff_date,))
            deleted_count = cursor.rowcount
            
            # Clean up old statistics
            cutoff_date_str = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
            cursor.execute('DELETE FROM webhook_statistics WHERE date < ?', (cutoff_date_str,))
            
            conn.commit()
        
        return jsonify({
            'success': True,
            'message': f'Successfully deleted {deleted_count} events older than {days} days',
            'deleted_count': deleted_count,
            'cutoff_date': cutoff_date
        })
    
    except Exception as e:
        logger.error(f"Error deleting old events: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@webhook_bp.route('/api/webhook_events/delete/all', methods=['DELETE'])
@login_required  
def delete_all_events():
    """Delete ALL webhook events (use with caution)"""
    try:
        db = get_database()
        if not db:
            return jsonify({'success': False, 'error': 'Database not available'}), 500
        
        # Require confirmation parameter to prevent accidental deletion
        data = request.get_json() or {}
        confirm = data.get('confirm', False)
        
        if not confirm:
            return jsonify({
                'success': False,
                'error': 'Confirmation required. Send {"confirm": true} to delete all events.'
            }), 400
        
        with db._get_connection() as conn:
            cursor = conn.cursor()
            
            # Count events before deletion
            cursor.execute('SELECT COUNT(*) FROM webhook_events')
            total_events = cursor.fetchone()[0]
            
            # Delete all events
            cursor.execute('DELETE FROM webhook_events')
            cursor.execute('DELETE FROM webhook_statistics')
            
            conn.commit()
        
        return jsonify({
            'success': True,
            'message': f'Successfully deleted all {total_events} webhook events',
            'deleted_count': total_events
        })
    
    except Exception as e:
        logger.error(f"Error deleting all events: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500 