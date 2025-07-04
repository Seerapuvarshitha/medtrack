
print("Starting MedTrack Flask App...")

from flask import Flask, request, jsonify, session, render_template, redirect, url_for, flash
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
from dotenv import load_dotenv
import boto3
import logging
import os
import uuid
from functools import wraps
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# Load environment variables
if not load_dotenv():
    print("Warning: .env file not found. Using default configurations.")

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', os.urandom(24))
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=1)

# AWS and Email Configuration
AWS_REGION_NAME = os.environ.get('AWS_REGION_NAME', 'ap-south-1')
SMTP_SERVER = os.environ.get('SMTP_SERVER', 'smtp.gmail.com')
SMTP_PORT = int(os.environ.get('SMTP_PORT', 587))
SENDER_EMAIL = os.environ.get('SENDER_EMAIL')
SENDER_PASSWORD = os.environ.get('SENDER_PASSWORD')
ENABLE_EMAIL = os.environ.get('ENABLE_EMAIL', 'False').lower() == 'true'
SNS_TOPIC_ARN = os.environ.get('SNS_TOPIC_ARN')
ENABLE_SNS = os.environ.get('ENABLE_SNS', 'False').lower() == 'true'

# Table names
USERS_TABLE_NAME = os.environ.get('USERS_TABLE_NAME', 'MedTrackUsers')

# AWS Initialization
try:
    if os.environ.get('AWS_ACCESS_KEY_ID'):
        dynamodb = boto3.resource('dynamodb', region_name=AWS_REGION_NAME)
        sns = boto3.client('sns', region_name=AWS_REGION_NAME) if ENABLE_SNS else None
    else:
        dynamodb = None
        sns = None
        logger.warning("Running in local mode. AWS credentials not found.")
except Exception as e:
    logger.error(f"AWS initialization error: {e}")
    dynamodb = None
    sns = None

# Local mock DB
local_db = {
    'users': {},
    'appointments': [],
}

# Table accessors
def get_users_table():
    return dynamodb.Table(USERS_TABLE_NAME) if dynamodb else None

# Auth decorator
def login_required(role=None, api=False):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user' not in session:
                if api:
                    return jsonify({'error': 'Authentication required'}), 401
                flash('Please log in.', 'warning')
                return redirect(url_for('index'))

            if role and session.get('role') != role:
                if api:
                    return jsonify({'error': 'Unauthorized'}), 403
                flash('Access denied.', 'danger')
                return redirect(url_for('index'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# Email utility
def send_email_notification(to_email, subject, body):
    if not ENABLE_EMAIL:
        logger.info(f"Simulated email: {subject}")
        return True
    try:
        msg = MIMEMultipart()
        msg['From'] = SENDER_EMAIL
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))

        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.send_message(msg)
        server.quit()

        logger.info(f"Email sent to {to_email}")
        return True
    except Exception as e:
        logger.error(f"Email failed: {e}")
        return False

# Routes
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/signup/<role>', methods=['GET', 'POST'])
def signup(role):
    if role not in ('patient', 'doctor'):
        flash('Invalid role.', 'danger')
        return redirect(url_for('index'))

    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        password = request.form.get('password')

        if not name or not email or not password:
            flash('All fields required.', 'warning')
            return render_template('signup.html', role=role)

        if dynamodb:
            table = get_users_table()
            if table.get_item(Key={'email': email}).get('Item'):
                flash('User exists.', 'danger')
                return render_template('signup.html', role=role)
        elif email in local_db['users']:
            flash('User exists.', 'danger')
            return render_template('signup.html', role=role)

        user_id = str(uuid.uuid4())
        user_data = {
            'user_id': user_id,
            'name': name,
            'email': email,
            'password_hash': generate_password_hash(password),
            'role': role,
            'created_at': datetime.now().isoformat(),
            'is_active': True
        }
        if dynamodb:
            get_users_table().put_item(Item=user_data)
        else:
            local_db['users'][email] = user_data

        flash('Signup successful. Please log in.', 'success')
        return redirect(url_for('login', role=role))

    return render_template('signup.html', role=role)

@app.route('/login/<role>', methods=['GET', 'POST'])
def login(role):
    if role not in ('patient', 'doctor'):
        flash('Invalid role.', 'danger')
        return redirect(url_for('index'))

    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')

        user_data = None
        if dynamodb:
            try:
                response = get_users_table().get_item(Key={'email': email})
                user_data = response.get('Item')
            except Exception as e:
                logger.error(f"DynamoDB error: {e}")
        else:
            user_data = local_db['users'].get(email)

        if not user_data or not check_password_hash(user_data['password_hash'], password):
            flash('Invalid credentials.', 'danger')
            return render_template('login.html', role=role)

        if user_data['role'] != role:
            flash('Role mismatch.', 'danger')
            return render_template('login.html', role=role)

        session['user'] = user_data['email']
        session['user_id'] = user_data['user_id']
        session['name'] = user_data['name']
        session['role'] = user_data['role']
        session.permanent = True

        flash('Login successful.', 'success')
        return redirect(url_for(f"{role}_dashboard"))

    return render_template('login.html', role=role)

@app.route('/logout')
@login_required()
def logout():
    session.clear()
    flash("Logged out successfully.", "success")
    return redirect(url_for('index'))

@app.route('/patient_dashboard')
@login_required(role='patient')
def patient_dashboard():
    return render_template('patient_dashboard.html')

@app.route('/doctor_dashboard')
@login_required(role='doctor')
def doctor_dashboard():
    return render_template('doctor_dashboard.html')

if __name__ == '__main__':
    app.run(debug=True)
