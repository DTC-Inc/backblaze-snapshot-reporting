from flask import Blueprint, jsonify, request, current_app, render_template
from datetime import datetime, timedelta

dashboard_bp = Blueprint('dashboard_routes', __name__, url_prefix='/api/dashboard')

def get_date_range_from_request(args):
    time_frame = args.get('time_frame', 'last_7_days') # Change default to match dashboard template
    custom_start = args.get('start_date')
    custom_end = args.get('end_date')

    # Default to last 7 days (from start of day to end of day in UTC for consistency with B2 eventTimestamps)
    # B2 eventTimestamp is milliseconds since epoch (UTC)
    # We will store event_timestamp as ISO string in DB, queries should handle this. 
    # For daily, weekly, etc., we usually care about full days. 

    now_utc = datetime.utcnow()
    start_date_dt = (now_utc - timedelta(days=6)).replace(hour=0, minute=0, second=0, microsecond=0)
    end_date_dt = now_utc.replace(hour=23, minute=59, second=59, microsecond=999999)

    if custom_start and custom_end:
        try:
            start_date_dt = datetime.fromisoformat(custom_start.replace('Z', '+00:00'))
            end_date_dt = datetime.fromisoformat(custom_end.replace('Z', '+00:00'))
        except ValueError:
            # Try parsing just date YYYY-MM-DD
            try:
                start_date_dt = datetime.strptime(custom_start, '%Y-%m-%d').replace(hour=0, minute=0, second=0, microsecond=0)
                end_date_dt = datetime.strptime(custom_end, '%Y-%m-%d').replace(hour=23, minute=59, second=59, microsecond=999999)
            except ValueError:
                 # Fallback to last 7 days if custom dates are invalid
                pass # Keep default 'last_7_days'
    elif time_frame == 'today':
        start_date_dt = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
        end_date_dt = now_utc.replace(hour=23, minute=59, second=59, microsecond=999999)
    elif time_frame == 'yesterday':
        yesterday = now_utc - timedelta(days=1)
        start_date_dt = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
        end_date_dt = yesterday.replace(hour=23, minute=59, second=59, microsecond=999999)
    elif time_frame == 'this_week':
        start_date_dt = (now_utc - timedelta(days=now_utc.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        # end_date_dt is already end of today
    elif time_frame == 'last_7_days':
        start_date_dt = (now_utc - timedelta(days=6)).replace(hour=0, minute=0, second=0, microsecond=0)
        # end_date_dt is already end of today
    elif time_frame == 'this_month':
        start_date_dt = now_utc.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        # end_date_dt is already end of today
    elif time_frame == 'last_30_days':
        start_date_dt = (now_utc - timedelta(days=29)).replace(hour=0, minute=0, second=0, microsecond=0)
        # end_date_dt is already end of today
    elif time_frame == 'this_quarter':
        current_quarter = (now_utc.month - 1) // 3 + 1
        start_month = (current_quarter - 1) * 3 + 1
        start_date_dt = now_utc.replace(month=start_month, day=1, hour=0, minute=0, second=0, microsecond=0)
        # end_date_dt is already end of today
    elif time_frame == 'this_year':
        start_date_dt = now_utc.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        # end_date_dt is already end of today
    # Add more time frames as needed: 'last_week', 'last_month', 'last_quarter', 'last_year'

    # Format as ISO strings for database queries, assuming DB stores event_timestamp as ISO string compatible.
    # The get_object_operation_stats_for_period expects ISO format strings (YYYY-MM-DDTHH:MM:SS)
    return start_date_dt.isoformat(), end_date_dt.isoformat()

@dashboard_bp.route('/stats/summary', methods=['GET'])
def get_dashboard_summary_stats():
    db = current_app.config['DATABASE_INSTANCE']
    bucket_name = request.args.get('bucket_name') if request.args.get('bucket_name') != 'all' else None
    start_date_str, end_date_str = get_date_range_from_request(request.args)
    
    try:
        current_app.logger.info(f"Dashboard summary stats request: bucket={bucket_name}, date_range={start_date_str} to {end_date_str}")
        summary_data = db.get_object_operation_stats_for_period(start_date_str, end_date_str, bucket_name)
        
        # Calculate net change today specifically for one of the cards
        today_start, today_end = get_date_range_from_request({'time_frame': 'today'})
        today_summary = db.get_object_operation_stats_for_period(today_start, today_end, bucket_name)
        summary_data['net_size_change_today'] = today_summary['net_size_change']

        current_app.logger.info(f"Dashboard summary stats result: {summary_data}")
        return jsonify(summary_data)
    except Exception as e:
        current_app.logger.error(f"Error fetching dashboard summary stats: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@dashboard_bp.route('/stats/daily_breakdown', methods=['GET'])
def get_dashboard_daily_stats():
    db = current_app.config['DATABASE_INSTANCE']
    bucket_name = request.args.get('bucket_name') if request.args.get('bucket_name') != 'all' else None
    start_date_str, end_date_str = get_date_range_from_request(request.args)

    try:
        current_app.logger.info(f"Dashboard daily breakdown request: bucket={bucket_name}, date_range={start_date_str} to {end_date_str}")
        daily_data = db.get_daily_object_operation_breakdown(start_date_str, end_date_str, bucket_name)
        current_app.logger.info(f"Dashboard daily breakdown result: {len(daily_data)} days of data")
        return jsonify({'daily_data': daily_data, 'start_date': start_date_str, 'end_date': end_date_str})
    except Exception as e:
        current_app.logger.error(f"Error fetching dashboard daily breakdown stats: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@dashboard_bp.route('/buckets', methods=['GET'])
def get_dashboard_buckets():
    db = current_app.config['DATABASE_INSTANCE']
    try:
        # Get bucket names that have actual webhook events for meaningful filtering
        bucket_names = db.get_all_bucket_names_from_webhooks()
        return jsonify({'buckets': bucket_names})
    except Exception as e:
        current_app.logger.error(f"Error fetching bucket names for dashboard: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

# --- Top 10 List Endpoints ---

@dashboard_bp.route('/top_buckets/size_added', methods=['GET'])
def get_top_size_added():
    db = current_app.config['DATABASE_INSTANCE']
    start_date, end_date = get_date_range_from_request(request.args)
    limit = int(request.args.get('limit', 10))
    try:
        data = db.get_top_buckets_by_size(operation_type='added', limit=limit, start_date_str=start_date, end_date_str=end_date)
        return jsonify(data)
    except Exception as e:
        current_app.logger.error(f"Error fetching top buckets by size added: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@dashboard_bp.route('/top_buckets/size_removed', methods=['GET'])
def get_top_size_removed():
    db = current_app.config['DATABASE_INSTANCE']
    start_date, end_date = get_date_range_from_request(request.args)
    limit = int(request.args.get('limit', 10))
    try:
        data = db.get_top_buckets_by_size(operation_type='removed', limit=limit, start_date_str=start_date, end_date_str=end_date)
        return jsonify(data)
    except Exception as e:
        current_app.logger.error(f"Error fetching top buckets by size removed: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@dashboard_bp.route('/top_buckets/objects_added', methods=['GET'])
def get_top_objects_added():
    db = current_app.config['DATABASE_INSTANCE']
    start_date, end_date = get_date_range_from_request(request.args)
    limit = int(request.args.get('limit', 10))
    try:
        data = db.get_top_buckets_by_object_count(operation_type='added', limit=limit, start_date_str=start_date, end_date_str=end_date)
        return jsonify(data)
    except Exception as e:
        current_app.logger.error(f"Error fetching top buckets by objects added: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@dashboard_bp.route('/top_buckets/objects_removed', methods=['GET'])
def get_top_objects_removed():
    db = current_app.config['DATABASE_INSTANCE']
    start_date, end_date = get_date_range_from_request(request.args)
    limit = int(request.args.get('limit', 10))
    try:
        data = db.get_top_buckets_by_object_count(operation_type='removed', limit=limit, start_date_str=start_date, end_date_str=end_date)
        return jsonify(data)
    except Exception as e:
        current_app.logger.error(f"Error fetching top buckets by objects removed: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@dashboard_bp.route('/top_buckets/stale', methods=['GET'])
def get_top_stale_buckets():
    db = current_app.config['DATABASE_INSTANCE']
    limit = int(request.args.get('limit', 10))
    active_threshold_days = int(request.args.get('active_threshold_days', 90))
    try:
        data = db.get_stale_buckets(limit=limit, active_threshold_days=active_threshold_days)
        return jsonify(data)
    except Exception as e:
        current_app.logger.error(f"Error fetching stale buckets: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500 