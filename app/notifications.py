import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

from app.config import (
    EMAIL_ENABLED, EMAIL_SENDER, EMAIL_RECIPIENTS, 
    EMAIL_SERVER, EMAIL_PORT, EMAIL_USERNAME, 
    EMAIL_PASSWORD, EMAIL_USE_TLS, EMAIL_USE_SSL
)

logger = logging.getLogger(__name__)

def send_email_notification(subject, message, recipients=None, notification_type='alert'):
    """
    Send an email notification using the configured email settings
    
    Args:
        subject (str): Email subject
        message (str): Email message body (HTML format)
        recipients (list, optional): List of email recipients. Defaults to EMAIL_RECIPIENTS.
        notification_type (str): Type of notification for logging purposes.
        
    Returns:
        bool: True if sent successfully, False otherwise
    """
    if not EMAIL_ENABLED:
        logger.info("Email notifications are disabled")
        return False
        
    try:
        # Use default recipients if none provided
        recipients = recipients or EMAIL_RECIPIENTS
        
        if not recipients or not EMAIL_SENDER or not EMAIL_SERVER:
            logger.warning("Incomplete email configuration, skipping notification")
            return False
            
        # Create message
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = EMAIL_SENDER
        msg['To'] = ', '.join(recipients)
        
        # Attach HTML message
        html_part = MIMEText(message, 'html')
        msg.attach(html_part)
        
        # Connect to SMTP server
        if EMAIL_USE_SSL:
            server = smtplib.SMTP_SSL(EMAIL_SERVER, EMAIL_PORT)
        else:
            server = smtplib.SMTP(EMAIL_SERVER, EMAIL_PORT)
            
        if EMAIL_USE_TLS:
            server.starttls()
            
        # Log in if credentials provided
        if EMAIL_USERNAME and EMAIL_PASSWORD:
            server.login(EMAIL_USERNAME, EMAIL_PASSWORD)
            
        # Send email
        server.sendmail(EMAIL_SENDER, recipients, msg.as_string())
        server.quit()
        
        logger.info(f"Email notification sent to {len(recipients)} recipients")
          # Log to database if available
        try:
            # Import global db instance from app.py
            from app.app import db
            db.log_notification(
                notification_type=notification_type,
                details=subject,
                recipients=recipients,
                status='success'
            )
        except Exception as db_error:
            logger.warning(f"Could not log notification to database: {str(db_error)}")
        
        return True
        
    except Exception as e:
        logger.error(f"Failed to send email notification: {str(e)}")
        
        # Log failure to database if available
        try:
            # Import global db instance from app.py
            from app.app import db
            db.log_notification(
                notification_type=notification_type,
                details=f"Failed to send '{subject}': {str(e)}",
                recipients=recipients,
                status='failed'
            )
        except Exception as db_error:
            logger.warning(f"Could not log notification failure to database: {str(db_error)}")
        
        return False
        
def format_cost_change_email(changes, snapshot_id):
    """
    Format cost change notification email
    
    Args:
        changes (dict): Dictionary of cost changes
        snapshot_id (int): ID of the snapshot with changes
        
    Returns:
        tuple: (subject, html_message)
    """
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    # Create the email subject with the most significant change
    if 'total' in changes:
        percent_change = changes['total']['percent']
        direction = 'increased' if percent_change > 0 else 'decreased'
        subject = f"⚠️ Backblaze costs {direction} by {abs(percent_change):.1f}% - Alert"
    else:
        subject = f"⚠️ Backblaze cost change detected - Alert"
    
    # Format the HTML message
    html = f"""
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
            .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
            .header {{ background-color: #f8f9fa; padding: 15px; border-bottom: 3px solid #dee2e6; }}
            .content {{ padding: 20px 0; }}
            table {{ border-collapse: collapse; width: 100%; margin: 20px 0; }}
            th, td {{ padding: 12px 15px; text-align: left; border-bottom: 1px solid #ddd; }}
            th {{ background-color: #f2f2f2; }}
            .increase {{ color: #d9534f; }}
            .decrease {{ color: #5cb85c; }}
            .footer {{ font-size: 12px; color: #777; border-top: 1px solid #eee; padding-top: 15px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h2>Backblaze B2 Cost Alert</h2>
                <p>Significant cost changes detected in your Backblaze B2 account</p>
            </div>
            
            <div class="content">
                <p>The monitoring system detected significant cost changes at {now}.</p>
                
                <table>
                    <thead>
                        <tr>
                            <th>Category</th>
                            <th>Previous</th>
                            <th>Current</th>
                            <th>Change</th>
                        </tr>
                    </thead>
                    <tbody>
    """
    
    # Add rows for each cost category
    categories = {
        'storage': 'Storage',
        'download': 'Download',
        'api': 'API Calls',
        'total': 'Total Cost'
    }
    
    for key, label in categories.items():
        if key in changes:
            change = changes[key]
            percent = change['percent']
            css_class = 'increase' if percent > 0 else 'decrease'
            direction = '+' if percent > 0 else ''
            
            html += f"""
                <tr>
                    <td>{label}</td>
                    <td>${change['from']:.4f}</td>
                    <td>${change['to']:.4f}</td>
                    <td class="{css_class}">{direction}{percent:.1f}% (${change['absolute']:.4f})</td>
                </tr>
            """
    
    # Add bucket-specific changes if available
    if 'buckets' in changes:
        html += """
            </tbody>
        </table>
        
        <h3>Bucket-Specific Changes</h3>
        <table>
            <thead>
                <tr>
                    <th>Bucket</th>
                    <th>Previous</th>
                    <th>Current</th>
                    <th>Change</th>
                </tr>
            </thead>
            <tbody>
        """
        
        for bucket_change in changes['buckets']:
            bucket_name = bucket_change['bucket_name']
            change = bucket_change['change']
            percent = change['percent']
            css_class = 'increase' if percent > 0 else 'decrease'
            direction = '+' if percent > 0 else ''
            
            html += f"""
                <tr>
                    <td>{bucket_name}</td>
                    <td>${change['from']:.4f}</td>
                    <td>${change['to']:.4f}</td>
                    <td class="{css_class}">{direction}{percent:.1f}% (${change['absolute']:.4f})</td>
                </tr>
            """
    
    # Complete the email HTML
    html += f"""
                </tbody>
            </table>
            
            <p>
                <a href="/snapshots/{snapshot_id}" style="color: #0275d8;">View details in the monitoring dashboard</a>
            </p>
        </div>
        
        <div class="footer">
            <p>This is an automated notification from your Backblaze B2 cost monitoring system.</p>
        </div>
    </div>
    </body>
    </html>
    """
    
    return subject, html
