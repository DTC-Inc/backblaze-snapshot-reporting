from flask import Blueprint, jsonify, request, current_app, render_template
from datetime import datetime, timedelta
import math
from .models.redis_cache import cache
from .models.hybrid_cache import simple_cache

dashboard_bp = Blueprint('dashboard_routes', __name__, url_prefix='/api/dashboard')

def get_date_range_from_request(args):
    time_frame = args.get('time_frame', 'last_1_hour') # Default to last_1_hour for recent data
    custom_start = args.get('start_date')
    custom_end = args.get('end_date')

    # Default to last 1 hour (for recent webhook activity)
    now_utc = datetime.utcnow()
    start_date_dt = (now_utc - timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    end_date_dt = now_utc.replace(second=59, microsecond=999999)

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
                 # Fallback to last 1 hour if custom dates are invalid
                pass # Keep default 'last_1_hour'
    elif time_frame == 'last_1_hour':
        start_date_dt = now_utc - timedelta(hours=1)
        end_date_dt = now_utc
    elif time_frame == 'last_6_hours':
        start_date_dt = now_utc - timedelta(hours=6)
        end_date_dt = now_utc
    elif time_frame == 'last_12_hours':
        start_date_dt = now_utc - timedelta(hours=12)
        end_date_dt = now_utc
    elif time_frame == 'last_24_hours':
        start_date_dt = now_utc - timedelta(hours=24)
        end_date_dt = now_utc
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
        end_date_dt = now_utc.replace(hour=23, minute=59, second=59, microsecond=999999)
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
    
    # Generate cache key based on parameters
    cache_key = cache._generate_cache_key(
        "summary_stats",
        bucket=bucket_name,
        start=start_date_str,
        end=end_date_str
    )
    
    # Check cache first (30 second TTL for frequently changing data)
    cached_result = cache.get(cache_key)
    if cached_result:
        current_app.logger.info(f"Cache HIT for dashboard summary stats (key: {cache_key[-16:]}...)")
        return jsonify(cached_result)
    
    try:
        current_app.logger.info(f"Cache MISS for dashboard summary stats - executing query")
        current_app.logger.info(f"Dashboard summary stats request: bucket={bucket_name}, date_range={start_date_str} to {end_date_str}")
        summary_data = db.get_object_operation_stats_for_period(start_date_str, end_date_str, bucket_name)
        
        # Calculate net change today specifically for one of the cards
        today_start, today_end = get_date_range_from_request({'time_frame': 'today'})
        today_summary = db.get_object_operation_stats_for_period(today_start, today_end, bucket_name)
        summary_data['net_size_change_today'] = today_summary['net_size_change']

        # Cache the result for 30 seconds
        cache.set(cache_key, summary_data, ttl=30)
        current_app.logger.info(f"Cache STORED for dashboard summary stats (TTL: 30s)")
        
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

    # Generate cache key for daily breakdown
    cache_key = cache._generate_cache_key(
        "daily_breakdown",
        bucket=bucket_name,
        start=start_date_str,
        end=end_date_str
    )
    
    # Check cache first (5 minute TTL for daily breakdown)
    cached_result = cache.get(cache_key)
    if cached_result:
        current_app.logger.info(f"Cache HIT for dashboard daily breakdown (key: {cache_key[-16:]}...)")
        return jsonify(cached_result)

    try:
        current_app.logger.info(f"Cache MISS for daily breakdown - executing query")
        current_app.logger.info(f"Dashboard daily breakdown request: bucket={bucket_name}, date_range={start_date_str} to {end_date_str}")
        daily_data = db.get_daily_object_operation_breakdown(start_date_str, end_date_str, bucket_name)
        current_app.logger.info(f"Dashboard daily breakdown result: {len(daily_data)} days of data")
        
        # Calculate trends for predictions
        trend_analysis = {}
        if len(daily_data) >= 2:
            # Calculate trends for different metrics
            objects_added_data = [day['objects_added'] for day in daily_data]
            size_added_data = [day['size_added'] for day in daily_data]
            objects_deleted_data = [day['objects_deleted'] for day in daily_data]
            size_deleted_data = [day['size_deleted'] for day in daily_data]
            
            # Calculate net changes for overall growth trend
            net_objects_data = [day['objects_added'] - day['objects_deleted'] for day in daily_data]
            net_size_data = [day['size_added'] - day['size_deleted'] for day in daily_data]
            
            trend_analysis = {
                'objects_added_trend': calculate_linear_regression(objects_added_data),
                'size_added_trend': calculate_linear_regression(size_added_data),
                'objects_deleted_trend': calculate_linear_regression(objects_deleted_data),
                'size_deleted_trend': calculate_linear_regression(size_deleted_data),
                'net_objects_trend': calculate_linear_regression(net_objects_data),
                'net_size_trend': calculate_linear_regression(net_size_data)
            }
            
            # Generate predictions for the next 5 periods
            prediction_periods = 5
            current_app.logger.info(f"Generating trend predictions for {prediction_periods} future periods")
            
            # Add future predictions to daily_data
            future_predictions = []
            for i in range(prediction_periods):
                future_date = datetime.fromisoformat(end_date_str.split('T')[0]) + timedelta(days=i+1)
                
                prediction = {
                    'date': future_date.strftime('%Y-%m-%d'),
                    'is_prediction': True,
                    'objects_added': generate_trend_predictions(trend_analysis['objects_added_trend'], len(daily_data), 1)[0] if trend_analysis['objects_added_trend'] else 0,
                    'size_added': generate_trend_predictions(trend_analysis['size_added_trend'], len(daily_data), 1)[0] if trend_analysis['size_added_trend'] else 0,
                    'objects_deleted': generate_trend_predictions(trend_analysis['objects_deleted_trend'], len(daily_data), 1)[0] if trend_analysis['objects_deleted_trend'] else 0,
                    'size_deleted': generate_trend_predictions(trend_analysis['size_deleted_trend'], len(daily_data), 1)[0] if trend_analysis['size_deleted_trend'] else 0
                }
                future_predictions.append(prediction)
        
        # Combine historical data with predictions
        combined_data = daily_data + (future_predictions if 'future_predictions' in locals() else [])
        
        result = {
            'daily_data': combined_data,
            'trend_analysis': trend_analysis,
            'start_date': start_date_str,
            'end_date': end_date_str,
            'has_predictions': len(trend_analysis) > 0
        }
        
        # Cache the result for 5 minutes (longer TTL for complex analysis)
        cache.set(cache_key, result, ttl=300)
        current_app.logger.info(f"Cache STORED for daily breakdown (TTL: 5m)")
        
        return jsonify(result)
    except Exception as e:
        current_app.logger.error(f"Error fetching dashboard daily breakdown stats: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@dashboard_bp.route('/buckets', methods=['GET'])
def get_dashboard_buckets():
    db = current_app.config['DATABASE_INSTANCE']
    
    # Cache bucket list for 10 minutes since it doesn't change frequently
    cache_key = "dashboard_cache:bucket_list"
    cached_result = cache.get(cache_key)
    if cached_result:
        current_app.logger.info(f"Cache HIT for dashboard buckets")
        return jsonify(cached_result)
    
    try:
        current_app.logger.info(f"Cache MISS for buckets - executing query")
        # Get bucket names that have actual webhook events for meaningful filtering
        bucket_names = db.get_all_bucket_names_from_webhooks()
        result = {'buckets': bucket_names}
        
        # Cache for 10 minutes
        cache.set(cache_key, result, ttl=600)
        current_app.logger.info(f"Cache STORED for buckets (TTL: 10m)")
        
        return jsonify(result)
    except Exception as e:
        current_app.logger.error(f"Error fetching bucket names for dashboard: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

# --- Top 10 List Endpoints ---

@dashboard_bp.route('/top_buckets/size_added', methods=['GET'])
def get_top_size_added():
    db = current_app.config['DATABASE_INSTANCE']
    start_date, end_date = get_date_range_from_request(request.args)
    limit = int(request.args.get('limit', 10))
    
    # Cache key for top buckets by size added
    cache_key = cache._generate_cache_key(
        "top_size_added",
        start=start_date,
        end=end_date,
        limit=limit
    )
    
    # Check cache first (2 minute TTL for top bucket queries)
    cached_result = cache.get(cache_key)
    if cached_result:
        current_app.logger.debug(f"Cache hit for top buckets by size added")
        return jsonify(cached_result)
    
    try:
        data = db.get_top_buckets_by_size(operation_type='added', limit=limit, start_date_str=start_date, end_date_str=end_date)
        
        # Cache the result for 2 minutes
        cache.set(cache_key, data, ttl=120)
        
        return jsonify(data)
    except Exception as e:
        current_app.logger.error(f"Error fetching top buckets by size added: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@dashboard_bp.route('/top_buckets/size_removed', methods=['GET'])
def get_top_size_removed():
    db = current_app.config['DATABASE_INSTANCE']
    start_date, end_date = get_date_range_from_request(request.args)
    limit = int(request.args.get('limit', 10))
    
    # Cache key for top buckets by size removed
    cache_key = cache._generate_cache_key(
        "top_size_removed",
        start=start_date,
        end=end_date,
        limit=limit
    )
    
    # Check cache first (2 minute TTL for top bucket queries)
    cached_result = cache.get(cache_key)
    if cached_result:
        current_app.logger.debug(f"Cache hit for top buckets by size removed")
        return jsonify(cached_result)
    
    try:
        data = db.get_top_buckets_by_size(operation_type='removed', limit=limit, start_date_str=start_date, end_date_str=end_date)
        
        # Cache the result for 2 minutes
        cache.set(cache_key, data, ttl=120)
        
        return jsonify(data)
    except Exception as e:
        current_app.logger.error(f"Error fetching top buckets by size removed: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@dashboard_bp.route('/top_buckets/objects_added', methods=['GET'])
def get_top_objects_added():
    db = current_app.config['DATABASE_INSTANCE']
    start_date, end_date = get_date_range_from_request(request.args)
    limit = int(request.args.get('limit', 10))
    
    # Cache key for top buckets by objects added
    cache_key = cache._generate_cache_key(
        "top_objects_added",
        start=start_date,
        end=end_date,
        limit=limit
    )
    
    # Check cache first (2 minute TTL for top bucket queries)
    cached_result = cache.get(cache_key)
    if cached_result:
        current_app.logger.info(f"Cache HIT for top buckets by objects added")
        return jsonify(cached_result)
    
    try:
        current_app.logger.info(f"Cache MISS for top objects added - executing query")
        data = db.get_top_buckets_by_object_count(operation_type='added', limit=limit, start_date_str=start_date, end_date_str=end_date)
        
        # Cache the result for 2 minutes
        cache.set(cache_key, data, ttl=120)
        current_app.logger.info(f"Cache STORED for top objects added (TTL: 2m)")
        
        return jsonify(data)
    except Exception as e:
        current_app.logger.error(f"Error fetching top buckets by objects added: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@dashboard_bp.route('/top_buckets/objects_removed', methods=['GET'])
def get_top_objects_removed():
    db = current_app.config['DATABASE_INSTANCE']
    start_date, end_date = get_date_range_from_request(request.args)
    limit = int(request.args.get('limit', 10))
    
    # Cache key for top buckets by objects removed
    cache_key = cache._generate_cache_key(
        "top_objects_removed",
        start=start_date,
        end=end_date,
        limit=limit
    )
    
    # Check cache first (2 minute TTL for top bucket queries)
    cached_result = cache.get(cache_key)
    if cached_result:
        current_app.logger.info(f"Cache HIT for top buckets by objects removed")
        return jsonify(cached_result)
    
    try:
        current_app.logger.info(f"Cache MISS for top objects removed - executing query")
        data = db.get_top_buckets_by_object_count(operation_type='removed', limit=limit, start_date_str=start_date, end_date_str=end_date)
        
        # Cache the result for 2 minutes
        cache.set(cache_key, data, ttl=120)
        current_app.logger.info(f"Cache STORED for top objects removed (TTL: 2m)")
        
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

@dashboard_bp.route('/trends', methods=['GET'])
def get_trend_analysis():
    """Get detailed trend analysis and predictions for data growth"""
    db = current_app.config['DATABASE_INSTANCE']
    bucket_name = request.args.get('bucket_name') if request.args.get('bucket_name') != 'all' else None
    start_date_str, end_date_str = get_date_range_from_request(request.args)
    prediction_days = int(request.args.get('prediction_days', 7))  # Default 7 days prediction
    
    try:
        current_app.logger.info(f"Trend analysis request: bucket={bucket_name}, date_range={start_date_str} to {end_date_str}, predictions={prediction_days}")
        
        # Get historical data
        daily_data = db.get_daily_object_operation_breakdown(start_date_str, end_date_str, bucket_name)
        
        if len(daily_data) < 2:
            return jsonify({
                'error': 'Insufficient data for trend analysis. Need at least 2 data points.',
                'daily_data': daily_data,
                'trend_analysis': {},
                'predictions': []
            })
        
        # Extract data series for trend calculation
        objects_added_series = [day['objects_added'] for day in daily_data]
        size_added_series = [day['size_added'] for day in daily_data]
        objects_deleted_series = [day['objects_deleted'] for day in daily_data]
        size_deleted_series = [day['size_deleted'] for day in daily_data]
        
        # Calculate net changes
        net_objects_series = [day['objects_added'] - day['objects_deleted'] for day in daily_data]
        net_size_series = [day['size_added'] - day['size_deleted'] for day in daily_data]
        
        # Calculate trends
        trends = {
            'objects_added': calculate_linear_regression(objects_added_series),
            'size_added': calculate_linear_regression(size_added_series),
            'objects_deleted': calculate_linear_regression(objects_deleted_series),
            'size_deleted': calculate_linear_regression(size_deleted_series),
            'net_objects': calculate_linear_regression(net_objects_series),
            'net_size': calculate_linear_regression(net_size_series)
        }
        
        # Generate future predictions
        predictions = []
        base_date = datetime.fromisoformat(end_date_str.split('T')[0])
        
        for i in range(1, prediction_days + 1):
            future_date = base_date + timedelta(days=i)
            future_x = len(daily_data) + i - 1
            
            prediction_day = {
                'date': future_date.strftime('%Y-%m-%d'),
                'day_offset': i,
                'objects_added': max(0, trends['objects_added']['slope'] * future_x + trends['objects_added']['intercept']) if trends['objects_added'] else 0,
                'size_added': max(0, trends['size_added']['slope'] * future_x + trends['size_added']['intercept']) if trends['size_added'] else 0,
                'objects_deleted': max(0, trends['objects_deleted']['slope'] * future_x + trends['objects_deleted']['intercept']) if trends['objects_deleted'] else 0,
                'size_deleted': max(0, trends['size_deleted']['slope'] * future_x + trends['size_deleted']['intercept']) if trends['size_deleted'] else 0,
                'net_objects': (trends['net_objects']['slope'] * future_x + trends['net_objects']['intercept']) if trends['net_objects'] else 0,
                'net_size': (trends['net_size']['slope'] * future_x + trends['net_size']['intercept']) if trends['net_size'] else 0
            }
            predictions.append(prediction_day)
        
        # Calculate growth rates and insights
        insights = {}
        if trends['net_size']:
            daily_growth_rate = trends['net_size']['slope']
            monthly_growth = daily_growth_rate * 30
            yearly_growth = daily_growth_rate * 365
            
            # Current total size from latest data point
            current_size = sum(day['size_added'] - day['size_deleted'] for day in daily_data)
            
            insights = {
                'daily_growth_rate': daily_growth_rate,
                'monthly_projected_growth': monthly_growth,
                'yearly_projected_growth': yearly_growth,
                'current_total_size': current_size,
                'projected_size_in_30_days': current_size + monthly_growth,
                'projected_size_in_365_days': current_size + yearly_growth,
                'trend_strength': trends['net_size']['r_squared'],
                'trend_reliability': 'High' if trends['net_size']['r_squared'] > 0.8 else 'Medium' if trends['net_size']['r_squared'] > 0.5 else 'Low'
            }
        
        return jsonify({
            'daily_data': daily_data,
            'trend_analysis': trends,
            'predictions': predictions,
            'insights': insights,
            'data_period': {
                'start_date': start_date_str,
                'end_date': end_date_str,
                'data_points': len(daily_data),
                'prediction_days': prediction_days
            }
        })
        
    except Exception as e:
        current_app.logger.error(f"Error fetching trend analysis: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

def calculate_linear_regression(data_points):
    """Calculate linear regression for trend prediction"""
    if len(data_points) < 2:
        return None
    
    n = len(data_points)
    sum_x = sum(range(n))
    sum_y = sum(data_points)
    sum_xy = sum(i * y for i, y in enumerate(data_points))
    sum_x2 = sum(i * i for i in range(n))
    
    # Calculate slope (m) and y-intercept (b) for y = mx + b
    try:
        slope = (n * sum_xy - sum_x * sum_y) / (n * sum_x2 - sum_x * sum_x)
        intercept = (sum_y - slope * sum_x) / n
        
        # Calculate R-squared for trend strength
        y_mean = sum_y / n
        ss_tot = sum((y - y_mean) ** 2 for y in data_points)
        ss_res = sum((y - (slope * i + intercept)) ** 2 for i, y in enumerate(data_points))
        r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0
        
        return {
            'slope': slope,
            'intercept': intercept,
            'r_squared': r_squared,
            'trend_direction': 'increasing' if slope > 0 else 'decreasing' if slope < 0 else 'stable'
        }
    except ZeroDivisionError:
        return None

def generate_trend_predictions(trend_data, current_data_length, prediction_periods=5):
    """Generate future predictions based on trend"""
    if not trend_data:
        return []
    
    predictions = []
    for i in range(prediction_periods):
        future_x = current_data_length + i
        predicted_y = trend_data['slope'] * future_x + trend_data['intercept']
        # Ensure predictions don't go negative
        predicted_y = max(0, predicted_y)
        predictions.append(predicted_y)
    
    return predictions

@dashboard_bp.route('/top_objects/<stat_type>', methods=['GET'])
def api_dashboard_top_objects(stat_type):
    """Get top objects by various statistics"""
    try:
        db = current_app.config['DATABASE_INSTANCE']
        limit = int(request.args.get('limit', 10))
        
        # Get current filters 
        time_frame = request.args.get('time_frame', 'last_7_days')
        bucket_name = request.args.get('bucket_name')
        if bucket_name == 'all':
            bucket_name = None
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        
        # Calculate date range
        start_date_str, end_date_str = get_date_range_from_request(request.args)
        
        if stat_type == 'largest':
            # Get the largest objects
            objects = db.get_top_largest_objects(
                limit=limit,
                start_date_str=start_date_str,
                end_date_str=end_date_str,
                bucket_name=bucket_name
            )
            
            # Format the response with detailed information for modal
            formatted_objects = []
            for obj in objects:
                # Clean up object key for display in list
                object_key = obj.get('object_key', 'Unknown')
                object_key_display = object_key
                if object_key and len(object_key) > 50:
                    # Truncate long paths, showing start and end
                    object_key_display = object_key[:20] + '...' + object_key[-27:]
                
                # Parse the created_at timestamp for better display
                created_at = obj.get('created_at', '')
                event_timestamp = obj.get('event_timestamp', '')
                
                try:
                    if created_at:
                        created_dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                        created_formatted = created_dt.strftime('%Y-%m-%d %H:%M:%S UTC')
                    else:
                        created_formatted = 'Unknown'
                except:
                    created_formatted = created_at or 'Unknown'
                
                try:
                    if event_timestamp:
                        event_dt = datetime.fromisoformat(event_timestamp.replace('Z', '+00:00'))
                        event_formatted = event_dt.strftime('%Y-%m-%d %H:%M:%S UTC')
                    else:
                        event_formatted = 'Unknown'
                except:
                    event_formatted = event_timestamp or 'Unknown'
                
                formatted_objects.append({
                    'object_key': object_key_display,
                    'object_key_full': object_key,  # Full path for modal
                    'object_size': obj.get('object_size', 0),
                    'bucket_name': obj.get('bucket_name', 'Unknown'),
                    'created_at': created_at,
                    'created_at_formatted': created_formatted,
                    'event_timestamp': event_timestamp,
                    'event_timestamp_formatted': event_formatted,
                    'event_type': obj.get('event_type', 'Unknown'),
                    'request_id': obj.get('request_id', 'Unknown'),
                    'size_formatted': format_file_size(obj.get('object_size', 0)),
                    # Additional useful details for modal
                    'size_mb': round(obj.get('object_size', 0) / (1024 * 1024), 2),
                    'size_gb': round(obj.get('object_size', 0) / (1024 * 1024 * 1024), 3)
                })
            
            return jsonify(formatted_objects)
        else:
            return jsonify({'error': 'Invalid stat_type'}), 400
        
    except Exception as e:
        current_app.logger.error(f"Error getting top objects {stat_type}: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

def format_file_size(bytes_value):
    """Format bytes as human readable string"""
    if bytes_value == 0:
        return "0 B"
    
    try:
        bytes_value = float(bytes_value)
    except (ValueError, TypeError):
        return "Invalid size"
    
    units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
    unit_index = 0
    
    while bytes_value >= 1024 and unit_index < len(units) - 1:
        bytes_value /= 1024
        unit_index += 1
    
    if unit_index == 0:
        return f"{int(bytes_value)} {units[unit_index]}"
    else:
        return f"{bytes_value:.2f} {units[unit_index]}"

@dashboard_bp.route('/billing/current', methods=['GET'])
def get_current_billing():
    """Get current month-to-date billing estimate"""
    db = current_app.config['DATABASE_INSTANCE']
    bucket_name = request.args.get('bucket_name') if request.args.get('bucket_name') != 'all' else None
    
    # Cache key for billing data
    cache_key = cache._generate_cache_key(
        "current_billing",
        bucket=bucket_name
    )
    
    # Check cache first (1 minute TTL for billing data)
    cached_result = cache.get(cache_key)
    if cached_result:
        current_app.logger.info(f"Cache HIT for current billing")
        return jsonify(cached_result)
    
    try:
        current_app.logger.info(f"Cache MISS for billing - executing query")
        # Calculate month-to-date costs
        now_utc = datetime.utcnow()
        month_start = now_utc.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        
        # Calculate last day of current month properly
        if now_utc.month == 12:
            next_month = now_utc.replace(year=now_utc.year + 1, month=1, day=1)
        else:
            next_month = now_utc.replace(month=now_utc.month + 1, day=1)
        
        month_end = (next_month - timedelta(days=1)).replace(hour=23, minute=59, second=59, microsecond=999999)
        
        start_date_str = month_start.isoformat()
        end_date_str = now_utc.replace(hour=23, minute=59, second=59, microsecond=999999).isoformat()
        
        current_app.logger.info(f"Current billing request: bucket={bucket_name}, month_range={start_date_str} to {end_date_str}")
        
        # Get estimated costs using the existing method
        billing_data = db.calculate_estimated_costs(start_date_str, end_date_str, bucket_name)
        
        # Check if billing configuration is missing
        if billing_data.get('needs_configuration') or billing_data.get('error'):
            current_app.logger.warning(f"Billing configuration issue: {billing_data}")
            result = {
                'error': billing_data.get('error', 'Billing configuration not set up'),
                'needs_configuration': True,
                'month': now_utc.strftime('%B %Y'),
                'days_in_month': month_end.day,
                'days_elapsed': now_utc.day,
                'month_progress': (now_utc.day / month_end.day) * 100
            }
            return jsonify(result)
        
        # Add month context
        billing_data['month'] = now_utc.strftime('%B %Y')
        billing_data['days_in_month'] = month_end.day  # Actual days in current month
        billing_data['days_elapsed'] = now_utc.day
        billing_data['month_progress'] = (now_utc.day / month_end.day) * 100
        
        # Cache the result for 1 minute (billing data changes frequently)
        cache.set(cache_key, billing_data, ttl=60)
        current_app.logger.info(f"Cache STORED for billing (TTL: 1m)")
        
        current_app.logger.info(f"Current billing result: ${billing_data.get('estimated_total', 0):.2f} ({billing_data['days_elapsed']}/{billing_data['days_in_month']} days)")
        return jsonify(billing_data)
        
    except Exception as e:
        current_app.logger.error(f"Error fetching current billing data: {e}", exc_info=True)
        return jsonify({
            'error': f'Server error: {str(e)}',
            'needs_configuration': False
        }), 500

@dashboard_bp.route('/billing/configure', methods=['POST'])
def save_billing_configuration():
    """Save billing configuration from the UI"""
    db = current_app.config['DATABASE_INSTANCE']
    
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        baseline_amount = data.get('baseline_amount')
        billing_period_start = data.get('billing_period_start')
        discount_percentage = data.get('discount_percentage', 0.0)
        
        if baseline_amount is None or baseline_amount < 0:
            return jsonify({'error': 'Valid baseline_amount is required'}), 400
        
        if not billing_period_start:
            return jsonify({'error': 'billing_period_start is required'}), 400
        
        # Prepare configuration
        config = {
            'baseline_amount': float(baseline_amount),
            'discount_percentage': float(discount_percentage),
            'billing_period_start': billing_period_start,
            'next_billing_period_start': None,
            'storage_price_per_gb': 0.005,  # B2 default
            'class_a_api_price': 0.004,     # Per 1,000 calls
            'class_b_api_price': 0.004,     # Per 10,000 calls
            'class_c_api_price': 0.004      # Per 10,000 calls
        }
        
        success = db.save_billing_configuration(config)
        
        if success:
            current_app.logger.info(f"Billing configuration updated: baseline=${baseline_amount}, cycle_start={billing_period_start}")
            return jsonify({
                'success': True,
                'message': 'Billing configuration saved successfully'
            })
        else:
            return jsonify({'error': 'Failed to save configuration'}), 500
        
    except Exception as e:
        current_app.logger.error(f"Error saving billing configuration: {e}", exc_info=True)
        return jsonify({'error': f'Server error: {str(e)}'}), 500

@dashboard_bp.route('/cache/status', methods=['GET'])
def get_cache_status():
    """Get Redis cache statistics"""
    try:
        # Get both regular cache and simple cache stats
        regular_stats = cache.get_cache_stats()
        simple_stats = simple_cache.get_cache_stats()
        
        combined_stats = {
            'regular_cache': regular_stats,
            'simple_cache': simple_stats,
            'status': 'connected',
            'cache_types': ['regular', 'simple_time_series']
        }
        
        return jsonify(combined_stats)
    except Exception as e:
        current_app.logger.error(f"Error fetching cache status: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@dashboard_bp.route('/cache/invalidate', methods=['POST'])
def invalidate_dashboard_cache():
    """Manually invalidate all dashboard cache entries"""
    try:
        # Invalidate both cache types
        regular_deleted = cache.invalidate_dashboard_cache()
        simple_deleted = simple_cache.invalidate_current_day_cache()
        
        return jsonify({
            'success': True,
            'message': f'Invalidated {regular_deleted + simple_deleted} total cache entries',
            'regular_cache_deleted': regular_deleted,
            'simple_cache_deleted': simple_deleted,
            'total_deleted': regular_deleted + simple_deleted
        })
    except Exception as e:
        current_app.logger.error(f"Error invalidating cache: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@dashboard_bp.route('/cache/simple/status', methods=['GET'])
def get_simple_cache_status():
    """Get simple time-series cache statistics specifically"""
    try:
        stats = simple_cache.get_cache_stats()
        return jsonify(stats)
    except Exception as e:
        current_app.logger.error(f"Error fetching simple cache status: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@dashboard_bp.route('/cache/simple/invalidate', methods=['POST'])
def invalidate_simple_cache():
    """Manually invalidate simple cache entries (current day only)"""
    try:
        deleted_count = simple_cache.invalidate_current_day_cache()
        return jsonify({
            'success': True,
            'message': f'Invalidated {deleted_count} simple cache entries',
            'deleted_count': deleted_count
        })
    except Exception as e:
        current_app.logger.error(f"Error invalidating simple cache: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@dashboard_bp.route('/cache/simple/invalidate/<date_str>', methods=['POST'])
def invalidate_simple_cache_date(date_str):
    """Manually invalidate simple cache entries for a specific date"""
    try:
        deleted_count = simple_cache.invalidate_date_cache(date_str)
        return jsonify({
            'success': True,
            'message': f'Invalidated {deleted_count} cache entries for {date_str}',
            'deleted_count': deleted_count,
            'date': date_str
        })
    except Exception as e:
        current_app.logger.error(f"Error invalidating simple cache for {date_str}: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500 