#!/usr/bin/env python3
import os
import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from pathlib import Path

EMAIL_CONFIG = {
    'smtp_server': 'smtp.gmail.com',
    'smtp_port': 587,
    'from_email': 'ifeltzir@gmail.com',
    'from_password': os.environ.get('GMAIL_APP_PASSWORD', ''),
    'to_emails': ['ifeltzir@gmail.com']
}

EMAIL_ALERT_STATUSES = [
    'Driver Phone Unresponsive',
    'Tracking - Waiting for Update',
    'Tracking Waiting for Update'
]

EMAIL_ALERTS_FILE = Path('/root/csl-bot/ftl_email_alerts.json')

def load_sent_email_alerts():
    if EMAIL_ALERTS_FILE.exists():
        try:
            with open(EMAIL_ALERTS_FILE, 'r') as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_sent_email_alert(load_id, pro_number, status):
    alerts = load_sent_email_alerts()
    key = f"{load_id}_{status}"
    alerts[key] = {
        'load_id': load_id,
        'pro_number': pro_number,
        'status': status,
        'timestamp': datetime.now().isoformat()
    }
    try:
        with open(EMAIL_ALERTS_FILE, 'w') as f:
            json.dump(alerts, f, indent=2)
    except Exception as e:
        print(f"Warning: Could not save: {e}")

def should_send_email_alert(load_id, status):
    alerts = load_sent_email_alerts()
    key = f"{load_id}_{status}"
    return key not in alerts

def send_email_alert(efj_number, pro_number, container_load, status, details=''):
    if not EMAIL_CONFIG['from_password']:
        print("WARNING: GMAIL_APP_PASSWORD not set")
        return False
    
    msg = MIMEMultipart('alternative')
    msg['Subject'] = f"🚨 CSL Alert: {status} - Load {pro_number}"
    msg['From'] = EMAIL_CONFIG['from_email']
    msg['To'] = ', '.join(EMAIL_CONFIG['to_emails'])
    
    text_body = f"""
CSL FTL Load Alert
==================

Status: {status}
PRO #: {pro_number}
EFJ #: {efj_number}
Container/Load: {container_load}
Time: {datetime.now().strftime('%Y-%m-%d %I:%M %p ET')}

{details}

---
This is an automated alert from CSL Logistics Bot.
"""
    
    html_body = f"""
<!DOCTYPE html>
<html>
<body style="font-family: Arial, sans-serif;">
    <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
        <div style="background: #007bff; color: white; padding: 15px;">
            <h2 style="margin: 0;">🚨 CSL FTL Load Alert</h2>
        </div>
        <div style="background: #f8d7da; border-left: 4px solid #dc3545; padding: 15px; margin: 20px 0;">
            <h3 style="margin-top: 0;">⚠️ {status}</h3>
        </div>
        <div style="background: #f8f9fa; padding: 20px;">
            <p><strong>PRO Number:</strong> {pro_number}</p>
            <p><strong>EFJ #:</strong> {efj_number}</p>
            <p><strong>Container/Load:</strong> {container_load}</p>
            <p><strong>Alert Time:</strong> {datetime.now().strftime('%Y-%m-%d %I:%M %p ET')}</p>
            {f'<p><strong>Details:</strong> {details}</p>' if details else ''}
        </div>
        <div style="margin-top: 20px; font-size: 12px; color: #6c757d;">
            <p>This is an automated alert from CSL Logistics Bot.</p>
        </div>
    </div>
</body>
</html>
"""
    
    msg.attach(MIMEText(text_body, 'plain'))
    msg.attach(MIMEText(html_body, 'html'))
    
    try:
        with smtplib.SMTP(EMAIL_CONFIG['smtp_server'], EMAIL_CONFIG['smtp_port']) as server:
            server.starttls()
            server.login(EMAIL_CONFIG['from_email'], EMAIL_CONFIG['from_password'])
            server.sendmail(EMAIL_CONFIG['from_email'], EMAIL_CONFIG['to_emails'], msg.as_string())
        print(f"✅ Email sent for {pro_number}: {status}")
        return True
    except Exception as e:
        print(f"❌ Failed to send email: {e}")
        return False

def check_and_alert_on_status(load_data, current_status):
    status_normalized = current_status.strip()
    should_alert = any(alert_status.lower() in status_normalized.lower() for alert_status in EMAIL_ALERT_STATUSES)
    
    if not should_alert:
        return False
    
    load_id = load_data.get('efj_number', '') or load_data.get('pro_number', '')
    
    if not should_send_email_alert(load_id, status_normalized):
        print(f"Already sent email for {load_id} - {status_normalized}")
        return False
    
    success = send_email_alert(
        efj_number=load_data.get('efj_number', 'N/A'),
        pro_number=load_data.get('pro_number', 'N/A'),
        container_load=load_data.get('container_load', 'N/A'),
        status=status_normalized,
        details=load_data.get('details', '')
    )
    
    if success:
        save_sent_email_alert(load_id, load_data.get('pro_number', 'N/A'), status_normalized)
    
    return success

if __name__ == '__main__':
    print("Testing email alert system...")
    print(f"To: {EMAIL_CONFIG['to_emails']}")
    print(f"Password set: {bool(EMAIL_CONFIG['from_password'])}")
    
    test_load = {
        'efj_number': 'EFJ999999',
        'pro_number': 'TEST123456',
        'container_load': 'TEST-CONTAINER',
        'details': 'Test alert from FTL email system'
    }
    
    print("\nSending test email...")
    success = send_email_alert(
        efj_number=test_load['efj_number'],
        pro_number=test_load['pro_number'],
        container_load=test_load['container_load'],
        status='Driver Phone Unresponsive',
        details=test_load['details']
    )
    
    if success:
        print("✅ Test email sent! Check inbox at:", EMAIL_CONFIG['to_emails'])
    else:
        print("❌ Test failed. Check configuration.")
