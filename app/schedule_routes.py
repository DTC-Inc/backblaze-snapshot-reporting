import os
from flask import request, render_template, flash, redirect, url_for, Blueprint, current_app
from flask_login import login_required
from .app import db, logger

schedule_bp = Blueprint('schedule_routes', __name__, url_prefix='/schedule')

@schedule_bp.route('/settings', methods=['GET'])
@login_required
def schedule_settings():
    """View and edit snapshot schedule settings"""
    try:
        # Get current schedule settings
        schedule_settings_data = db.get_schedule_settings()
        
        # Get recent snapshots for reference
        snapshots = db.get_latest_snapshots(limit=10)
        
        return render_template(
            'schedule.html',
            settings=schedule_settings_data,
            snapshots=snapshots,
            page_title="Snapshot Schedule Settings"
        )
        
    except Exception as e:
        current_app.logger.error(f"Error in schedule settings route: {str(e)}")
        return render_template('error.html', error=str(e))

@schedule_bp.route('/settings', methods=['POST'])
@login_required
def save_schedule_settings():
    """Save snapshot schedule settings"""
    try:
        # Get form data
        schedule_type = request.form.get('schedule_type', 'interval')
        interval_hours = int(request.form.get('interval_hours', '24'))
        hour = int(request.form.get('hour', '0'))
        minute = int(request.form.get('minute', '0'))
        day_of_week = int(request.form.get('day_of_week', '0')) # 0 for Monday, 6 for Sunday as per Python's weekday()
        day_of_month = int(request.form.get('day_of_month', '1'))
        retain_days = int(request.form.get('retain_days', '90'))
        
        # Validate inputs
        if interval_hours < 1 or interval_hours > 168:
            flash('Hours between snapshots must be between 1 and 168.', 'danger')
            return redirect(url_for('.schedule_settings'))
            
        if hour < 0 or hour > 23:
            flash('Hour must be between 0 and 23.', 'danger')
            return redirect(url_for('.schedule_settings'))
            
        if minute < 0 or minute > 59:
            flash('Minute must be between 0 and 59.', 'danger')
            return redirect(url_for('.schedule_settings'))
            
        if day_of_week < 0 or day_of_week > 6:
            flash('Invalid day of week', 'danger')
            return redirect(url_for('.schedule_settings'))
            
        if day_of_month < 1 or day_of_month > 31:
            flash('Day of month must be between 1 and 31', 'danger')
            return redirect(url_for('.schedule_settings'))
            
        if retain_days < 7:
            flash('Retention period must be at least 7 days', 'danger')
            return redirect(url_for('.schedule_settings'))
        
        # Create settings object
        settings = {
            'schedule_type': schedule_type,
            'interval_hours': interval_hours,
            'hour': hour,
            'minute': minute,
            'day_of_week': day_of_week,
            'day_of_month': day_of_month,
            'retain_days': retain_days
        }
        
        # Save to database
        db.save_schedule_settings(settings)
        
        # Update app.config (in-memory for current process)
        current_app.config['SNAPSHOT_SCHEDULE_TYPE'] = schedule_type
        current_app.config['SNAPSHOT_INTERVAL_HOURS'] = interval_hours
        current_app.config['SNAPSHOT_HOUR'] = hour
        current_app.config['SNAPSHOT_MINUTE'] = minute
        current_app.config['SNAPSHOT_DAY_OF_WEEK'] = day_of_week
        current_app.config['SNAPSHOT_DAY_OF_MONTH'] = day_of_month
        current_app.config['SNAPSHOT_RETAIN_DAYS'] = retain_days
        
        flash('Schedule settings saved successfully!', 'success')
        return redirect(url_for('.schedule_settings'))
        
    except Exception as e:
        current_app.logger.error(f"Error saving schedule settings: {str(e)}")
        flash(f'Error saving settings: {str(e)}', 'danger')
        return redirect(url_for('.schedule_settings'))

@schedule_bp.route('/snapshots')
@login_required
def snapshots():
    """View all snapshots with filtering options"""
    try:
        limit = int(request.args.get('limit', 30))
        snapshots_data = db.get_latest_snapshots(limit=limit)
        
        return render_template(
            'snapshots_list.html',
            snapshots=snapshots_data,
            page_title="Snapshot History"
        )
        
    except Exception as e:
        current_app.logger.error(f"Error viewing snapshots: {str(e)}")
        return render_template('error.html', error=str(e))

@schedule_bp.route('/notifications/settings', methods=['GET']) # Example for notification_settings
@login_required
def notification_settings():
    # Placeholder for notification settings page
    # You would fetch current notification settings from db or config
    # current_settings = db.get_notification_settings() 
    current_settings = {"email_enabled": True, "recipient_email": "test@example.com"} # Dummy data
    return render_template('notification_settings.html', # Ensure this template exists
                           settings=current_settings, 
                           page_title="Notification Settings")

@schedule_bp.route('/notifications/settings', methods=['POST']) # Example for notification_settings
@login_required
def save_notification_settings():
    # Placeholder for saving notification settings
    # email_enabled = 'email_enabled' in request.form
    # recipient_email = request.form.get('recipient_email')
    # db.save_notification_settings(...)
    flash('Notification settings saved (placeholder).', 'success')
    return redirect(url_for('.notification_settings'))

@schedule_bp.route('/snapshots/manual-cleanup', methods=['POST'])
@login_required
def manual_snapshot_cleanup():
    """Manually trigger snapshot cleanup"""
    try:
        days = int(request.form.get('days', 30))
        if days < 1:
            flash('Retention days must be at least 1.', 'warning')
            return redirect(url_for('.snapshots')) # Corrected to blueprint endpoint
            
        deleted_count = db.delete_old_snapshots(days)
        flash(f'Successfully deleted {deleted_count} snapshots older than {days} days.', 'success')
        return redirect(url_for('.snapshots')) # Corrected to blueprint endpoint
        
    except Exception as e:
        current_app.logger.error(f"Error in manual cleanup: {str(e)}")
        flash(f'Error cleaning up snapshots: {str(e)}', 'danger')
        return redirect(url_for('.snapshots')) # Corrected to blueprint endpoint
