import json
import sqlite3
import requests
import os
import time
import threading
import logging
import subprocess
import signal
import sys
from flask import Flask, jsonify, request, render_template, render_template_string, Response, send_from_directory, send_file
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
from google.protobuf import descriptor as _descriptor
from google.protobuf import descriptor_pool as _descriptor_pool
from google.protobuf import symbol_database as _symbol_database
from google.protobuf.internal import builder as _builder
import re
import urllib.parse

# Load Bio Config
try:
    from FFLONGBIO.config import SITE_CONFIG
except ImportError:
    SITE_CONFIG = {"site_name": "MV Creator PRO", "bio_char_limit": 300}


app = Flask(__name__)
client_logs = []
bot_statuses = {}  # Store bot status (Online, Offline, Connecting) here for the UI

# To hold active bot clients
active_clients = {}
client_logs = []

# HEROKU OPTIMIZATION: Limit total bots to stay within memory limits (e.g., 512MB/1GB)
MAX_BOT_LIMIT = 5 
BOT_ROTATION_INTERVAL = 3600 # 1 hour in seconds
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin12345")
last_rotation_time = time.time()
current_rotation_index = 0

# History of exploit requests
exploit_history = []

class WebLogHandler(logging.Handler):
    def emit(self, record):
        try:
            log_entry = self.format(record)
            client_logs.append(log_entry)
            if len(client_logs) > 500:
                client_logs.pop(0)
        except Exception:
            self.handleError(record)

logger = logging.getLogger()
logger.setLevel(logging.INFO)
# Avoid duplicate logging if it already has handlers
if not any(isinstance(h, WebLogHandler) for h in logger.handlers):
    web_handler = WebLogHandler()
    web_handler.setFormatter(logging.Formatter('%(asctime)s - [%(levelname)s] - %(message)s'))
    logger.addHandler(web_handler)

# --- Bio Injector Logic ---
_sym_db = _symbol_database.Default()
DESCRIPTOR = _descriptor_pool.Default().AddSerializedFile(b'\n\ndata.proto\"\xbb\x01\n\x04\x44\x61ta\x12\x0f\n\x07\x66ield_2\x18\x02 \x01(\x05\x12\x1e\n\x07\x66ield_5\x18\x05 \x01(\x0b\x32\r.EmptyMessage\x12\x1e\n\x07\x66ield_6\x18\x06 \x01(\x0b\x32\r.EmptyMessage\x12\x0f\n\x07\x66ield_8\x18\x08 \x01(\t\x12\x0f\n\x07\x66ield_9\x18\t \x01(\x05\x12\x1f\n\x08\x66ield_11\x18\x0b \x01(\x0b\x32\r.EmptyMessage\x12\x1f\n\x08\x66ield_12\x18\x0c \x01(\x0b\x32\r.EmptyMessage\"\x0e\n\x0c\x45mptyMessageb\x06proto3')
_globals = globals()
_builder.BuildMessageAndEnumDescriptors(DESCRIPTOR, _globals)
_builder.BuildTopDescriptorsAndMessages(DESCRIPTOR, 'data1_pb2', _globals)

Data = _sym_db.GetSymbol('Data')
EmptyMessage = _sym_db.GetSymbol('EmptyMessage')

BIO_KEY = bytes([89, 103, 38, 116, 99, 37, 68, 69, 117, 104, 54, 37, 90, 99, 94, 56])
BIO_IV = bytes([54, 111, 121, 90, 68, 114, 50, 50, 69, 51, 121, 99, 104, 106, 77, 37])

def get_region_url(region):
    urls = {
        "IND": "https://client.ind.freefiremobile.com",
        "BR": "https://client.us.freefiremobile.com",
        "US": "https://client.us.freefiremobile.com",
        "SAC": "https://client.us.freefiremobile.com",
        "NA": "https://client.us.freefiremobile.com",
        "ME": "https://clientbp.common.ggbluefox.com",
        "TH": "https://clientbp.common.ggbluefox.com"
    }
    return urls.get(region.upper(), "https://clientbp.ggblueshark.com")

def get_account_from_eat(eat_token):
    try:
        if '?eat=' in eat_token:
            eat_token = urllib.parse.parse_qs(urllib.parse.urlparse(eat_token).query).get('eat', [eat_token])[0]
        elif '&eat=' in eat_token:
            match = re.search(r'[?&]eat=([^&]+)', eat_token)
            if match: eat_token = match.group(1)
        
        res = requests.get(f"https://eat-api.thory.buzz/api?eatjwt={eat_token}", timeout=15)
        if res.status_code != 200: return None, None, f"API error: {res.status_code}"
        d = res.json()
        if d.get('status') != 'success': return None, None, d.get('message', 'Invalid token')
        return d.get('token'), {"uid": d.get('uid'), "region": d.get('region', 'IND'), "nickname": d.get('nickname')}, None
    except Exception as e: return None, None, str(e)

def update_bio_with_jwt(jwt_token, bio_text, region):
    try:
        base_url = get_region_url(region)
        data = Data()
        data.field_2, data.field_8, data.field_9 = 17, bio_text.replace('+', ' '), 1
        data.field_5.CopyFrom(EmptyMessage()); data.field_6.CopyFrom(EmptyMessage())
        data.field_11.CopyFrom(EmptyMessage()); data.field_12.CopyFrom(EmptyMessage())
        
        cipher = AES.new(BIO_KEY, AES.MODE_CBC, BIO_IV)
        encrypted = cipher.encrypt(pad(data.SerializeToString(), AES.block_size))
        
        host = "clientbp.ggblueshark.com"
        if "ind" in base_url: host = "client.ind.freefiremobile.com"
        elif "us" in base_url: host = "client.us.freefiremobile.com"
        elif "common" in base_url: host = "clientbp.common.ggbluefox.com"

        headers = {
            "Authorization": f"Bearer {jwt_token}",
            "ReleaseVersion": SITE_CONFIG.get('freefire_version', 'OB56'),
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 11; SM-A305F Build/RP1A.200720.012)",
            "Host": host,
            "Connection": "Keep-Alive"
        }
        res = requests.post(f"{base_url}/UpdateSocialBasicInfo", headers=headers, data=encrypted, timeout=30)
        return res.status_code == 200
    except Exception as e: raise Exception(str(e))


def init_db():
    try:
        conn = sqlite3.connect("app_config.db")
        cursor = conn.cursor()
        
        # Create AppConfig table if not exists
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS AppConfig (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                version TEXT DEFAULT '1.1',
                update_required BOOLEAN DEFAULT 0,
                message TEXT DEFAULT 'Server is online',
                telegram_url TEXT DEFAULT 'https://t.me/MissCodeX',
                youtube_url TEXT DEFAULT 'https://www.youtube.com/@MvFemily',
                apk_url TEXT DEFAULT '/uploads/MVCreatorPRO.apk'
            )
        """)
        
        # Check if table has rows, if not insert default row
        cursor.execute("SELECT COUNT(*) FROM AppConfig")
        if cursor.fetchone()[0] == 0:
            cursor.execute("""
                INSERT INTO AppConfig (version, update_required, message, telegram_url, youtube_url, apk_url)
                VALUES ('1.1', 0, 'Server is online', 'https://t.me/MissCodeX', 'https://www.youtube.com/@MvFemily', '/uploads/MVCreatorPRO.apk')
            """)
            conn.commit()
            
        # Create Version table if not exists
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS Version (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                version TEXT DEFAULT '1.1',
                update_required BOOLEAN DEFAULT 0,
                message TEXT DEFAULT 'Server is online',
                telegram_url TEXT DEFAULT 'https://t.me/MissCodeX',
                youtube_url TEXT DEFAULT 'https://www.youtube.com/@MvFemily',
                apk_url TEXT DEFAULT '/uploads/MVCreatorPRO.apk'
            )
        """)
        
        # Check if table has rows, if not insert default row
        cursor.execute("SELECT COUNT(*) FROM Version")
        if cursor.fetchone()[0] == 0:
            cursor.execute("""
                INSERT INTO Version (version, update_required, message, telegram_url, youtube_url, apk_url)
                VALUES ('1.1', 0, 'Server is online', 'https://t.me/MissCodeX', 'https://www.youtube.com/@MvFemily', '/uploads/MVCreatorPRO.apk')
            """)
            conn.commit()
            
        # Ensure the columns telegram_url, youtube_url, and apk_url exist in both tables
        for table_name in ["AppConfig", "Version"]:
            cursor.execute(f"PRAGMA table_info({table_name})")
            columns = [col[1] for col in cursor.fetchall()]
            if "telegram_url" not in columns:
                cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN telegram_url TEXT DEFAULT 'https://t.me/MissCodeX'")
            if "youtube_url" not in columns:
                cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN youtube_url TEXT DEFAULT 'https://www.youtube.com/@MvFemily'")
            if "apk_url" not in columns:
                cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN apk_url TEXT DEFAULT '/uploads/MVCreatorPRO.apk'")
            conn.commit()
            
        # Update existing records from old default URLs to new ones
        for table_name in ["AppConfig", "Version"]:
            cursor.execute(f"UPDATE {table_name} SET telegram_url = 'https://t.me/MissCodeX' WHERE telegram_url = 'https://t.me/blackapis' OR telegram_url IS NULL")
            cursor.execute(f"UPDATE {table_name} SET youtube_url = 'https://www.youtube.com/@MvFemily' WHERE youtube_url = 'https://youtube.com/@harshmanjhi180' OR youtube_url IS NULL")
            conn.commit()
            
        conn.close()
    except Exception as e:
        print(f"[DB] Error initializing database: {e}")


@app.route('/')
def index():
    return render_template('index.html')

@app.route('/download/apk')
def download_apk():
    # Try to get the latest uploaded APK path from the database
    apk_path = "MVCreatorPRO.apk"
    try:
        conn = sqlite3.connect("app_config.db")
        cursor = conn.cursor()
        
        row = None
        try:
            cursor.execute("SELECT apk_url FROM AppConfig LIMIT 1")
            row = cursor.fetchone()
        except sqlite3.OperationalError:
            pass
            
        if not row:
            try:
                cursor.execute("SELECT apk_url FROM Version LIMIT 1")
                row = cursor.fetchone()
            except sqlite3.OperationalError:
                pass
                
        conn.close()
        
        if row and row[0]:
            clean_path = row[0].lstrip('/')
            if clean_path.startswith('uploads/'):
                apk_path = clean_path
    except Exception as e:
        logging.error(f"[API] Error reading APK download path from DB: {e}")

    if os.path.exists(apk_path):
        try:
            return send_file(os.path.abspath(apk_path), as_attachment=True)
        except Exception as e:
            return jsonify({"status": "error", "message": f"Error downloading APK: {e}"}), 500
    else:
        # Fallback to default in root directory
        if os.path.exists("MVCreatorPRO.apk"):
            try:
                return send_file(os.path.abspath("MVCreatorPRO.apk"), as_attachment=True)
            except Exception as e:
                return jsonify({"status": "error", "message": f"Error downloading APK: {e}"}), 500
                
        return jsonify({
            "status": "error", 
            "message": f"APK file not found on the server ({apk_path}). Please upload update via admin panel."
        }), 404

@app.route('/api/version')
def get_version():
    version_val = "1.1"
    update_required_val = False
    message_val = "Server is online"
    telegram_url_val = "https://t.me/MissCodeX"
    youtube_url_val = "https://www.youtube.com/@MvFemily"
    apk_url_val = "/uploads/MVCreatorPRO.apk"
    
    try:
        conn = sqlite3.connect("app_config.db")
        cursor = conn.cursor()
        
        # Try fetching from AppConfig first, then fallback to Version
        row = None
        try:
            cursor.execute("SELECT version, update_required, message, telegram_url, youtube_url, apk_url FROM AppConfig LIMIT 1")
            row = cursor.fetchone()
        except sqlite3.OperationalError:
            try:
                cursor.execute("SELECT version, update_required, message, telegram_url, youtube_url FROM AppConfig LIMIT 1")
                row = cursor.fetchone()
            except sqlite3.OperationalError:
                pass
            
        if not row:
            try:
                cursor.execute("SELECT version, update_required, message, telegram_url, youtube_url, apk_url FROM Version LIMIT 1")
                row = cursor.fetchone()
            except sqlite3.OperationalError:
                try:
                    cursor.execute("SELECT version, update_required, message, telegram_url, youtube_url FROM Version LIMIT 1")
                    row = cursor.fetchone()
                except sqlite3.OperationalError:
                    pass
                
        conn.close()
        
        if row:
            version_val = row[0]
            update_required_val = bool(row[1])
            message_val = row[2]
            telegram_url_val = row[3]
            youtube_url_val = row[4]
            if len(row) > 5 and row[5]:
                apk_url_val = row[5]
    except Exception as e:
        logging.error(f"[API] Error reading version from DB: {e}")
        
    scheme = "https" if request.is_secure or "herokuapp.com" in request.host else "http"
    download_url = f"{scheme}://{request.host}{apk_url_val}"
    
    return jsonify({
        "status": "success",
        "version": version_val,
        "update_required": update_required_val,
        "message": message_val,
        "telegram_url": telegram_url_val,
        "youtube_url": youtube_url_val,
        "download_url": download_url
    })


@app.route('/api/admin/verify_password', methods=['POST'])
def verify_admin_password():
    data = request.get_json(silent=True) or {}
    password = data.get('password')
    if password == ADMIN_PASSWORD:
        return jsonify({"status": "success", "message": "Verification successful"})
    return jsonify({"status": "error", "message": "Incorrect admin password. Access denied!"}), 401


@app.route('/api/admin/upload_update', methods=['POST'])
def upload_update():
    # Extract other fields robustly
    version = request.form.get('version') or request.args.get('version') or request.headers.get('version') or '1.1'
    update_required_str = request.form.get('update_required') or request.args.get('update_required') or request.headers.get('update_required') or 'false'
    message = request.form.get('message') or request.args.get('message') or request.headers.get('message') or ''
    telegram_url = request.form.get('telegram_url') or request.args.get('telegram_url') or request.headers.get('telegram_url')
    youtube_url = request.form.get('youtube_url') or request.args.get('youtube_url') or request.headers.get('youtube_url')
    
    # Log the request structure for debugging
    logging.info(f"[UPLOAD] Form fields: {list(request.form.keys())}")
    logging.info(f"[UPLOAD] Query params: {list(request.args.keys())}")
    logging.info(f"[UPLOAD] Headers: {list(request.headers.keys())}")
    logging.info(f"[UPLOAD] Files: {list(request.files.keys())}")
        
    if 'file' not in request.files:
        logging.warning("[UPLOAD] Upload failed: No APK file in request.")
        return jsonify({"status": "error", "message": "No APK file uploaded"}), 400
        
    file = request.files['file']
    if file.filename == '':
        logging.warning("[UPLOAD] Upload failed: Empty filename.")
        return jsonify({"status": "error", "message": "No selected file"}), 400
        
    os.makedirs('uploads', exist_ok=True)
    filename = file.filename
    file_path = os.path.join('uploads', filename)
    file.save(file_path)
    logging.info(f"[UPLOAD] Saved file to {file_path}")
    
    update_required = 1 if update_required_str.lower() == 'true' else 0
    apk_url = f"/uploads/{filename}"
    
    try:
        conn = sqlite3.connect("app_config.db")
        cursor = conn.cursor()
        
        updates = [("version", version), ("update_required", update_required), ("message", message), ("apk_url", apk_url)]
        if telegram_url:
            updates.append(("telegram_url", telegram_url))
        if youtube_url:
            updates.append(("youtube_url", youtube_url))
            
        for table_name in ["AppConfig", "Version"]:
            cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
            if cursor.fetchone()[0] == 0:
                cols = [u[0] for u in updates]
                vals = [u[1] for u in updates]
                placeholders = ", ".join(["?"] * len(vals))
                col_names = ", ".join(cols)
                cursor.execute(f"INSERT INTO {table_name} ({col_names}) VALUES ({placeholders})", vals)
            else:
                set_clause = ", ".join([f"{u[0]} = ?" for u in updates])
                vals = [u[1] for u in updates]
                cursor.execute(f"UPDATE {table_name} SET {set_clause} WHERE id = (SELECT id FROM {table_name} LIMIT 1)", vals)
                
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"[API] Error saving update to DB: {e}")
        return jsonify({"status": "error", "message": f"Database save failed: {str(e)}"}), 500
        
    return jsonify({
        "status": "success",
        "message": f"Version {version} has been successfully published! Users will see the update popup instantly."
    })


@app.route('/uploads/<path:filename>')
def serve_uploads(filename):
    return send_from_directory(os.path.join(os.getcwd(), 'uploads'), filename)


@app.route('/api/verify-token', methods=['POST'])
def verify_token():
    try:
        token = request.json.get('eat_token')
        if not token: return jsonify({"success": False, "error": "Missing token"}), 400
        jwt, acc, err = get_account_from_eat(token)
        if err: return jsonify({"success": False, "error": err}), 400
        return jsonify({"success": True, "account": acc, "jwt_token": jwt})
    except Exception as e: return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/update-bio', methods=['POST'])
def update_bio():
    try:
        d = request.json
        jwt, bio, reg = d.get('jwt_token'), d.get('bio'), d.get('region')
        if not jwt or not bio: return jsonify({"success": False, "error": "Missing data"}), 400
        if update_bio_with_jwt(jwt, bio, reg):
            return jsonify({"success": True, "message": "Bio updated!"})
        return jsonify({"success": False, "error": "Update failed"}), 400
    except Exception as e: return jsonify({"success": False, "error": str(e)}), 500


@app.route('/robots.txt')
def robots():
    return send_from_directory(os.getcwd(), 'robots.txt')

@app.route('/googlec56e56af2571922d.html')
def google_verify():
    return send_from_directory(os.getcwd(), 'googlec56e56af2571922d.html')

@app.route('/api/accounts', methods=['GET'])
def get_accounts():
    if not os.path.exists('bot.txt'):
        return jsonify([])
    with open('bot.txt', 'r') as f:
        try:
            data = json.load(f)
            # If it's the old dict format, convert to list for consistency
            if isinstance(data, dict):
                data = [{"uid": k, "password": v} for k, v in data.items()]
        except:
            data = []
    return jsonify(data)

def log_reader(process, uid):
    """Reads stdout from the spawned process and updates web logs and statuses"""
    if uid not in bot_statuses:
        bot_statuses[uid] = {"status": "Connecting...", "name": "Unknown", "last_update": time.time()}
        
    try:
        # Read the stream line by line
        for line in iter(process.stdout.readline, ''):
            if not line: break
            log_line = line.strip()
            
            # Update last_update timestamp to show bot is alive
            bot_statuses[uid]["last_update"] = time.time()
            
            # Detect successful login/online status
            if "NAJMI-M24 BOT - ONLINE" in log_line or "READY" in log_line or "Bot is now running" in log_line:
                bot_statuses[uid]["status"] = "Online"
                bot_statuses[uid]["last_update"] = time.time()
            
            if "Welcome," in log_line:
                # Extract name: "👋 Welcome, PlayerName!"
                parts = log_line.split("Welcome,")
                if len(parts) > 1:
                    name_part = parts[1].strip()
                    # Remove exclamation marks or formatting
                    name_part = name_part.replace("!", "").replace("[0m", "").strip()
                    bot_statuses[uid]["name"] = name_part
                    bot_statuses[uid]["status"] = "Online"
                    
            # elif "fatal error" in log_line or "Bad login" in log_line or ("Error" in log_line and "Invalid Account" in log_line):
            #     # Auto-remove bad bots from bot.txt as requested
            #     try:
            #         if os.path.exists('bot.txt'):
            #             with open('bot.txt', 'r') as f:
            #                 data = json.load(f)
            #             if uid in data:
            #                 del data[uid]
            #                 with open('bot.txt', 'w') as f:
            #                     json.dump(data, f, indent=4)
            #                 client_logs.append(f"{time.strftime('%Y-%m-%d %H:%M:%S')} - [SYSTEM] - Removed invalid bot {uid} from bot.txt")
            #     except Exception as e:
            #         pass
            elif "Error" in log_line or "Failed" in log_line:
                # Some errors don't crash the bot, but we can log them
                pass
                
            formatted_log = f"{time.strftime('%Y-%m-%d %H:%M:%S')} - [{uid}] - {log_line}"
            client_logs.append(formatted_log)
            if len(client_logs) > 500:
                client_logs.pop(0)
    except Exception as e:
        client_logs.append(f"{time.strftime('%Y-%m-%d %H:%M:%S')} - [{uid}] - ERROR reading process output: {e}")
    finally:
        if uid in bot_statuses:
            bot_statuses[uid]["status"] = "Offline"
            bot_statuses[uid]["last_update"] = time.time()
        process.stdout.close()

@app.route('/api/bots_status', methods=['GET'])
def bots_status():
    if not os.path.exists('bot.txt'):
        return jsonify({"summary": {"total": 0, "online": 0, "offline": 0}, "bots": []})
    
    with open('bot.txt', 'r') as f:
        try:
            stored_data = json.load(f)
            if isinstance(stored_data, dict):
                stored_bots = [{"uid": k, "password": v} for k, v in stored_data.items()]
            else:
                stored_bots = stored_data
        except:
            stored_bots = []
            
    logging.warning(f"[DEBUG] active_clients keys: {list(active_clients.keys())}")
    for u, p in active_clients.items():
        logging.warning(f"[DEBUG] bot {u} poll: {p.poll()} pid: {p.pid}")
        
    bot_list = []
    online_count = 0
    offline_count = 0
    
    for bot_obj in stored_bots:
        uid = str(bot_obj.get('uid'))
        if uid in active_clients:
            proc = active_clients[uid]
            if proc.poll() is None:
                # Running
                status_info = bot_statuses.get(uid, {"status": "Connecting...", "name": "Unknown"})
                is_online = status_info.get("status") == "Online"
                if is_online: online_count += 1
                else: offline_count += 1
                
                bot_list.append({
                    "uid": uid,
                    "name": status_info.get("name", "Unknown"),
                    "status": status_info.get("status", "Unknown"),
                    "pid": proc.pid
                })
            else:
                # Dead
                offline_count += 1
                bot_list.append({
                    "uid": uid,
                    "name": "Crashed",
                    "status": "Offline",
                    "pid": None
                })
        else:
            offline_count += 1
            bot_list.append({
                "uid": uid,
                "name": "Offline",
                "status": "Offline",
                "pid": None
            })
            
    return jsonify({
        "summary": {
            "total": len(stored_bots),
            "online": online_count,
            "offline": offline_count
        },
        "bots": bot_list
    })

@app.route('/api/accounts', methods=['POST'])
def add_account():
    req = request.json
    uid = req.get('uid')
    pwd = req.get('password')
    data = []
    if os.path.exists('bot.txt'):
        with open('bot.txt', 'r') as f:
            try:
                data = json.load(f)
                if isinstance(data, dict):
                    data = [{"uid": k, "password": v} for k, v in data.items()]
            except:
                pass
    
    # Check if already exists
    exists = False
    for item in data:
        if str(item['uid']) == str(uid):
            item['password'] = pwd
            exists = True
            break
    
    if not exists:
        data.append({"uid": uid, "password": pwd})
        
    with open('bot.txt', 'w') as f:
        json.dump(data, f, indent=4)
    return jsonify({"status": "success", "message": "Account added."})

def logic_start_bots():
    if not os.path.exists('bot.txt'):
        return 0, "No accounts found."
    with open('bot.txt', 'r') as f:
        try:
            stored_data = json.load(f)
            if isinstance(stored_data, dict):
                data_list = [{"uid": k, "password": v} for k, v in stored_data.items()]
            else:
                data_list = stored_data
        except:
            return 0, "Error loading bot.txt"
    
    started = 0
    running_count = len([u for u, p in active_clients.items() if p.poll() is None])
    started = 0
    running_count = len([u for u, p in active_clients.items() if p.poll() is None])
    
    # ONLY start the bots for the current rotation
    targets = []
    for i in range(MAX_BOT_LIMIT):
        idx = (current_rotation_index + i) % len(data_list)
        targets.append(data_list[idx])
        
    for bot_obj in targets:
        uid = str(bot_obj.get('uid'))
        pwd = bot_obj.get('password')
        
        if uid not in active_clients or active_clients[uid].poll() is not None:
            if running_count >= MAX_BOT_LIMIT:
                # If we have excess bots (from a previous setting), kill the oldest one
                running_uids = [u for u, p in active_clients.items() if p.poll() is None]
                if running_uids:
                    oldest_uid = running_uids[0]
                    logging.info(f"[SYSTEM] Killing excess bot {oldest_uid} to respect limit.")
                    try:
                        active_clients[oldest_uid].terminate()
                    except: pass
                    running_count -= 1

            try:
                cmd = [sys.executable, "main.py", str(uid), str(pwd)]
                env = os.environ.copy()
                env["PYTHONUNBUFFERED"] = "1"
                proc = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, bufsize=1, env=env
                )
                active_clients[uid] = proc
                threading.Thread(target=log_reader, args=(proc, uid), daemon=True).start()
                started += 1
                running_count += 1
                time.sleep(2)
            except Exception as e:
                logging.error(f"Failed to start bot {uid}: {e}")
                
    return started, "Success"

@app.route('/api/start_bots', methods=['POST'])
def start_bots():
    started, msg = logic_start_bots()
    if msg == "No accounts found.":
        return jsonify({"status": "error", "message": msg}), 400
    return jsonify({"status": "success", "message": f"{started} bots started."})

@app.route('/api/start_specific_bots', methods=['POST'])
def start_specific_bots():
    uids = request.json.get('uids', [])
    if not uids:
        return jsonify({"status": "error", "message": "No UIDs provided"}), 400
        
    if not os.path.exists('bot.txt'):
        return jsonify({"status": "error", "message": "No accounts found."}), 400
        
    with open('bot.txt', 'r') as f:
        try:
            stored_data = json.load(f)
            if isinstance(stored_data, dict):
                data_dict = stored_data
            else:
                data_dict = {str(item.get('uid')): item.get('password') for item in stored_data}
        except Exception as e:
            return jsonify({"status": "error", "message": f"Error loading bot.txt: {e}"}), 400
    
    started = 0
    running_count = len([u for u, p in active_clients.items() if p.poll() is None])

    for uid in uids:
        if running_count >= MAX_BOT_LIMIT:
            oldest_uid = next(iter(active_clients))
            active_clients[oldest_uid].terminate()
            running_count -= 1
            
        uid = str(uid)
        pwd = data_dict.get(uid)
        if pwd:
            if uid not in active_clients or active_clients[uid].poll() is not None:
                try:
                    cmd = [sys.executable, "main.py", str(uid), str(pwd)]
                    env = os.environ.copy()
                    env["PYTHONUNBUFFERED"] = "1"
                    
                    proc = subprocess.Popen(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        bufsize=1,
                        env=env
                    )
                    
                    active_clients[uid] = proc
                    log_thread = threading.Thread(target=log_reader, args=(proc, uid))
                    log_thread.daemon = True
                    log_thread.start()
                    
                    started += 1
                    time.sleep(1)
                except Exception as e:
                    logging.error(f"Failed to start bot {uid}: {e}")
                    
    return jsonify({"status": "success", "message": f"{started} bots started."})
ipc_lock = threading.Lock()

def send_ipc_command(uid, command):
    port_file = f".ipc/{uid}.port"
    if not os.path.exists(port_file): 
        logging.error(f"[IPC] Port file missing for {uid}")
        return None
    with ipc_lock:
        try:
            with open(port_file, "r") as f:
                port = int(f.read().strip())
            import socket
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(10.0)
                logging.info(f"[IPC] Connecting to {uid} on port {port}...")
                s.connect(('127.0.0.1', port))
                logging.info(f"[IPC] Sending command: {command}")
                s.sendall((command + "\n").encode())
                resp = s.recv(1024).decode().strip()
                logging.info(f"[IPC] Received response: '{resp}'")
                return resp
        except Exception as e:
            logging.error(f"[IPC] Error sending {command} to {uid}: {e}")
            return None

@app.route('/api/player_stats/<uid>')
def player_stats(uid):
    # 1. Try to get general info from external API
    general_info = {}
    try:
        api_url = f"https://info-api-mg24-pro.vercel.app/get?uid={uid}"
        res = requests.get(api_url, timeout=5)
        if res.status_code == 200:
            general_info = res.json()
    except Exception as e:
        logging.error(f"External API error for {uid}: {e}")

    # 2. Get real-time status from bot via IPC
    real_time_status = {}
    # Use the first active bot to check status
    active_uids = [u for u in active_clients.keys() if active_clients[u].poll() is None]
    if active_uids:
        bot_uid = active_uids[0]
        resp = send_ipc_command(bot_uid, f"GET_STATS {uid}")
        if resp and resp.startswith('{'):
            try:
                real_time_status = json.loads(resp)
            except:
                pass
    
    return jsonify({
        "uid": uid,
        "general": general_info,
        "real_time": real_time_status
    })

def send_ipc_to_target_or_free_bot(command, target_bot_uid=None):
    """
    Routes IPC commands to a specific bot (if targeted by session_id) 
    or iterates through active online bots to find an available (unlocked) bot.
    """
    active_uids = [u for u in active_clients.keys() if active_clients[u].poll() is None]
    if not active_uids:
        return None, "ERROR: No active bots connected"

    # 1. Target specific bot if target_bot_uid is provided (e.g. from LOCK_<bot_uid>_<hash>)
    if target_bot_uid and str(target_bot_uid) in active_uids:
        resp = send_ipc_command(str(target_bot_uid), command)
        return str(target_bot_uid), resp

    # 2. Otherwise iterate active_uids to find an available (unlocked) bot
    last_err = None
    for bot_uid in active_uids:
        resp = send_ipc_command(bot_uid, command)
        if resp:
            if "SUCCESS" in resp or "OK" in resp:
                return bot_uid, resp
            elif "ERROR" in resp:
                err_text = resp.split("ERROR: ")[-1].strip() if "ERROR: " in resp else resp
                # Check for any locked / busy / failed error message
                err_lower = err_text.lower()
                if any(k in err_lower for k in ["locked", "busy", "failed", "cannot", "timeout", "error"]):
                    last_err = err_text
                    logging.info(f"[ROUTING] Bot {bot_uid} is unavailable ({err_text}). Trying next free bot...")
                    continue
                else:
                    return bot_uid, resp
        else:
            logging.info(f"[ROUTING] Bot {bot_uid} did not respond via IPC. Trying next free bot...")

    return None, f"ERROR: {last_err or 'All online bots are currently busy/locked in squads'}"

@app.route('/api/group_exploit', methods=['POST'])
def group_exploit():
    uid = request.json.get('uid')
    slot = request.json.get('slot', 5)
    if not uid:
        return jsonify({"status": "error", "message": "UID required"}), 400
        
    bot_uid, resp = send_ipc_to_target_or_free_bot(f"GROUP_EXPLOIT {uid} {slot}")
    if resp and "SUCCESS" in resp:
        exploit_history.insert(0, {
            "uid": uid,
            "slot": slot,
            "time": time.strftime("%H:%M:%S"),
            "status": "Success"
        })
        if len(exploit_history) > 20: exploit_history.pop()
        return jsonify({"status": "success", "message": "Exploit sequence initiated.", "bot_uid": bot_uid})
    else:
        err_msg = resp.split("ERROR: ")[-1].strip() if resp and "ERROR: " in resp else (resp or "All online bots are busy")
        return jsonify({"status": "error", "message": err_msg}), 400

@app.route('/api/exploit_logs')
def get_exploit_logs():
    return jsonify(exploit_history)

@app.route('/api/send_bot_command', methods=['POST'])
def send_bot_command():
    data = request.json or {}
    cmd_type = data.get('type')
    payload = data.get('payload', '')
    
    type_map = {
        "invite": "INVITE",
        "like": "LIKE",
        "check_ban": "CHECK_BAN",
        "kick": "KICK",
        "room_msg": "ROOM_MSG",
        "fast_emote": "FAST_EMOTE"
    }
    
    ipc_cmd = type_map.get(cmd_type)
    if not ipc_cmd:
        return jsonify({"status": "error", "message": "Invalid command type"}), 400

    bot_uid, resp = send_ipc_to_target_or_free_bot(f"{ipc_cmd} {payload}")
    if resp and "SUCCESS" in resp:
        return jsonify({"status": "success", "message": resp.split("SUCCESS: ")[-1], "bot_uid": bot_uid})
    else:
        err_msg = resp.split("ERROR: ")[-1].strip() if resp and "ERROR: " in resp else (resp or "Failed to execute command")
        return jsonify({"status": "error", "message": err_msg}), 400

@app.route('/api/fast_emote', methods=['POST'])
def fast_emote():
    data = request.json or {}
    team_code = data.get('team_code')
    session_id = data.get('session_id')
    uids = data.get('uids')
    emote_id = data.get('emote_id')
    mode = data.get('mode')
    if not mode:
        mode = "lock" if session_id else "quit"
    
    target_identifier = session_id or team_code
    if not target_identifier or not uids or not emote_id:
        return jsonify({"status": "error", "message": "Missing team_code/session_id, uids, or emote_id"}), 400
        
    if isinstance(uids, list):
        uids_str = ",".join([str(u) for u in uids])
    else:
        uids_str = str(uids)

    # If session_id format is LOCK_<bot_uid>_<hash>, extract targeted bot_uid
    target_bot_uid = None
    if session_id and "_" in str(session_id):
        parts = str(session_id).split("_")
        if len(parts) >= 3:
            target_bot_uid = parts[1]

    bot_uid, resp = send_ipc_to_target_or_free_bot(
        f"FAST_EMOTE {target_identifier} {uids_str} {emote_id} {mode}",
        target_bot_uid=target_bot_uid
    )

    if resp and "SUCCESS" in resp:
        res_str = resp.split("SUCCESS: ")[-1].strip()
        try:
            res_dict = json.loads(res_str)
            res_dict["bot_uid"] = bot_uid
            return jsonify(res_dict)
        except Exception:
            return jsonify({"status": "success", "message": res_str, "bot_uid": bot_uid})
    else:
        err_msg = resp.split("ERROR: ")[-1].strip() if resp and "ERROR: " in resp else (resp or "Failed to execute fast emote")
        return jsonify({"status": "error", "message": err_msg}), 400

@app.route('/api/create_squad', methods=['POST'])
def create_squad():
    squad_file = ".ipc/latest_squad.txt"
    if os.path.exists(squad_file):
        try:
            os.remove(squad_file)
        except:
            pass

    bot_uid, resp = send_ipc_to_target_or_free_bot("CREATE_SQUAD")
    if resp and "OK" in resp:
        for _ in range(30):
            if os.path.exists(squad_file):
                try:
                    with open(squad_file, "r") as f:
                        team_code = f.read().strip()
                    return jsonify({"status": "success", "team_code": team_code, "bot_uid": bot_uid})
                except Exception as e:
                    print(f" Error reading squad file: {e}")
            time.sleep(0.1)
        return jsonify({"status": "error", "message": "Timed out waiting for team code"}), 500
    else:
        err_msg = resp.split("ERROR: ")[-1].strip() if resp and "ERROR: " in resp else (resp or "All online bots are busy")
        return jsonify({"status": "error", "message": err_msg}), 500

@app.route('/api/generate_group', methods=['POST'])
def generate_group():
    try:
        req = request.json
        count = req.get('count', 5)
        name_prefix = req.get('name', 'BlackApis')
        pwd_prefix = req.get('password_prefix', 'FF')
        
        accounts = []
        api_url = f"https://gen-by-black-api.vercel.app/generate?name={name_prefix}&password_prefix={pwd_prefix}"
        
        for i in range(count):
            try:
                res = requests.get(api_url, timeout=30)
                if res.status_code == 200:
                    data = res.json()
                    if data.get("success"):
                        accounts.append({
                            "uid": data.get("uid"),
                            "password": data.get("password"),
                            "name": data.get("name")
                        })
                time.sleep(0.5) # Avoid spamming the API too fast
            except Exception as e:
                logging.error(f"Error generating account {i}: {e}")
        
        return jsonify({"status": "success", "accounts": accounts})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/save_group', methods=['POST'])
def save_group():
    try:
        accounts = request.json.get('accounts', [])
        if not accounts:
            return jsonify({"status": "error", "message": "No accounts provided"}), 400
            
        # Add to bot.txt
        data = {}
        if os.path.exists('bot.txt'):
            with open('bot.txt', 'r') as f:
                try:
                    data = json.load(f)
                except:
                    pass
        
        for acc in accounts:
            uid = str(acc.get('uid'))
            pwd = acc.get('password')
            if uid and pwd:
                # Update if exists, else append
                found = False
                for existing in data:
                    if str(existing.get('uid')) == uid:
                        existing['password'] = pwd
                        found = True
                        break
                if not found:
                    data.append({"uid": uid, "password": pwd})
                
        with open('bot.txt', 'w') as f:
            json.dump(data, f, indent=4)
            
        return jsonify({"status": "success", "message": f"{len(accounts)} accounts saved to bot.txt"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/logs')
def stream_logs():
    def generate():
        last_idx = 0
        while True:
            if last_idx < len(client_logs):
                # Using a snapshot copy to avoid concurrency issues during iteration
                new_logs = client_logs[last_idx:]
                for log in new_logs:
                    # Sanitize log for SSE data format (no newlines in a single data block unless formatted)
                    clean_log = log.replace('\n', ' ')
                    yield f"data: {clean_log}\n\n"
                last_idx += len(new_logs)
            time.sleep(0.5)
    return Response(generate(), mimetype='text/event-stream')

def auto_start_bots():
    """Wait for server to settle then trigger bot startup"""
    time.sleep(2)
    print("[SYSTEM] Auto-starting bots on boot...")
    res = logic_start_bots()
    print(f"[SYSTEM] Bot startup result: {res}")

# Startup initialization for production (Gunicorn)
if os.environ.get('PORT'):
    # In production, ensure we only start bots once
    print("[HEROKU] Production environment detected. Initializing bots...")
    threading.Thread(target=auto_start_bots, daemon=True).start()

def bot_monitor_loop():
    """Background thread to rotate and monitor bots"""
    global last_rotation_time, current_rotation_index
    while True:
        try:
            # 1. Check if it's time to rotate
            now = time.time()
            is_rotation_time = (now - last_rotation_time) >= BOT_ROTATION_INTERVAL
            
            # 2. Load accounts
            try:
                with open('bot.txt', 'r') as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        data_list = [{"uid": k, "password": v} for k, v in data.items()]
                    else:
                        data_list = data
            except Exception as e:
                logging.error(f"[MONITOR] Error reading bot.txt: {e}")
                time.sleep(10)
                continue

            # 3. Handle Rotation Logic
            if is_rotation_time or not active_clients:
                if is_rotation_time:
                    logging.info("[MONITOR] Rotation time reached. Stopping current bots...")
                    # Kill everyone and remove stale IPC port files
                    for uid in list(active_clients.keys()):
                        proc = active_clients.get(uid)
                        if proc and proc.poll() is None:
                            try:
                                if os.name == 'nt': subprocess.call(['taskkill', '/F', '/T', '/PID', str(proc.pid)])
                                else: proc.terminate()
                            except: pass
                        port_file = f".ipc/{uid}.port"
                        if os.path.exists(port_file):
                            try: os.remove(port_file)
                            except: pass
                    active_clients.clear()
                    bot_statuses.clear()
                    
                    # Update index for next bots
                    current_rotation_index = (current_rotation_index + MAX_BOT_LIMIT) % len(data_list)
                    last_rotation_time = now
                
                # Pick the 2 bots based on current index
                targets = []
                for i in range(MAX_BOT_LIMIT):
                    idx = (current_rotation_index + i) % len(data_list)
                    targets.append(data_list[idx])
                
                # Start them
                for bot_obj in targets:
                    uid = str(bot_obj.get('uid'))
                    pwd = bot_obj.get('password')
                    if uid not in active_clients or active_clients[uid].poll() is not None:
                        logging.info(f"[MONITOR] Starting bot {uid} (Rotation)...")
                        cmd = [sys.executable, "main.py", str(uid), str(pwd)]
                        env = os.environ.copy()
                        env["PYTHONUNBUFFERED"] = "1"
                        proc = subprocess.Popen(
                            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, bufsize=1, env=env
                        )
                        active_clients[uid] = proc
                        threading.Thread(target=log_reader, args=(proc, uid), daemon=True).start()
                        time.sleep(5) # Stagger
            
            # 4. Health Check & Auto-Restart (for the current rotation)
            running_uids = [u for u, p in active_clients.items() if p.poll() is None]
            
            # If any of the 2 target bots are not running, start them
            current_targets = []
            for i in range(MAX_BOT_LIMIT):
                idx = (current_rotation_index + i) % len(data_list)
                current_targets.append(data_list[idx])
            
            for bot_obj in current_targets:
                uid = str(bot_obj.get('uid'))
                pwd = bot_obj.get('password')
                
                # Check if it's stalled
                status_info = bot_statuses.get(uid, {})
                if uid in active_clients and active_clients[uid].poll() is None:
                    if status_info.get("status") != "Online" and (time.time() - status_info.get("last_update", 0) > 300):
                        logging.warning(f"[MONITOR] Bot {uid} stalled. Killing...")
                        proc = active_clients[uid]
                        try:
                            if os.name == 'nt': subprocess.call(['taskkill', '/F', '/T', '/PID', str(proc.pid)])
                            else: proc.terminate()
                        except: pass
                
                # Restart if dead or just killed
                if uid not in active_clients or active_clients[uid].poll() is not None:
                    logging.info(f"[MONITOR] Restarting bot {uid} (Maintain Shift)...")
                    cmd = [sys.executable, "main.py", str(uid), str(pwd)]
                    env = os.environ.copy()
                    env["PYTHONUNBUFFERED"] = "1"
                    proc = subprocess.Popen(
                        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        text=True, bufsize=1, env=env
                    )
                    active_clients[uid] = proc
                    threading.Thread(target=log_reader, args=(proc, uid), daemon=True).start()
                    time.sleep(2)

        except Exception as e:
            logging.error(f"[MONITOR] Loop error: {e}")
        time.sleep(30) # Check every 30 seconds

@app.route('/api/get_all_logs')
def get_all_logs():
    return jsonify(client_logs)

@app.route('/api/allstats', methods=['GET'])
def get_all_stats():
    """
    Returns comprehensive system status, running processes, and active bot stats in JSON format.
    Supports multi-user concurrency monitoring and real-time bot state inspection.
    """
    import psutil
    import datetime
    
    # 1. System Info
    cpu_percent = psutil.cpu_percent(interval=0.1)
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage('/') if os.name != 'nt' else psutil.disk_usage('C:\\')
    
    # 2. Active bots inspection
    active_uids = [u for u in active_clients.keys() if active_clients[u].poll() is None]
    bot_details = []
    locked_bots_count = 0
    free_bots_count = 0
    
    for uid, proc in list(active_clients.items()):
        is_running = proc.poll() is None
        proc_memory_mb = 0
        proc_cpu_percent = 0
        if is_running:
            try:
                p = psutil.Process(proc.pid)
                proc_memory_mb = round(p.memory_info().rss / (1024 * 1024), 2)
                proc_cpu_percent = p.cpu_percent(interval=0.05)
            except Exception:
                pass

        bot_info = {
            "uid": uid,
            "status": "ONLINE" if is_running else "OFFLINE",
            "pid": proc.pid if is_running else None,
            "memory_mb": proc_memory_mb,
            "cpu_percent": proc_cpu_percent,
            "is_locked": False,
            "lock_session_id": None,
            "squad_member_count": 0,
            "insquad": False,
            "real_time_status": None
        }

        # Query IPC GET_BOT_STATUS if online
        if is_running:
            raw_resp = send_ipc_command(uid, "GET_BOT_STATUS")
            if raw_resp and "SUCCESS: " in raw_resp:
                try:
                    status_json_str = raw_resp.split("SUCCESS: ")[-1].strip()
                    parsed_bot_status = json.loads(status_json_str)
                    bot_info["real_time_status"] = parsed_bot_status
                    bot_info["is_locked"] = parsed_bot_status.get("is_locked", False)
                    bot_info["lock_session_id"] = parsed_bot_status.get("lock_session_id")
                    bot_info["insquad"] = parsed_bot_status.get("insquad", False)
                    bot_info["squad_member_count"] = parsed_bot_status.get("squad_member_count", 0)
                    bot_info["lock_info"] = parsed_bot_status.get("lock_info")
                except Exception as ex:
                    logging.error(f"Error parsing bot status for {uid}: {ex}")

        if is_running:
            if bot_info["is_locked"]:
                locked_bots_count += 1
            else:
                free_bots_count += 1

        bot_details.append(bot_info)

    # 3. Overall server processes breakdown
    python_processes = []
    try:
        for p in psutil.process_iter(['pid', 'name', 'cmdline', 'memory_info', 'cpu_percent']):
            try:
                cmd = " ".join(p.info['cmdline'] or [])
                if 'python' in (p.info['name'] or '').lower() or 'main.py' in cmd or 'web.py' in cmd:
                    python_processes.append({
                        "pid": p.info['pid'],
                        "name": p.info['name'],
                        "cmdline": cmd,
                        "memory_mb": round((p.info['memory_info'].rss if p.info['memory_info'] else 0) / (1024 * 1024), 2),
                        "cpu_percent": p.info['cpu_percent']
                    })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
    except Exception as e:
        logging.error(f"Error reading process list: {e}")

    server_stats = {
        "timestamp": datetime.datetime.now().isoformat(),
        "status": "ONLINE",
        "system": {
            "cpu_percent": cpu_percent,
            "memory": {
                "total_mb": round(memory.total / (1024 * 1024), 2),
                "available_mb": round(memory.available / (1024 * 1024), 2),
                "used_mb": round(memory.used / (1024 * 1024), 2),
                "percent": memory.percent
            },
            "disk": {
                "total_gb": round(disk.total / (1024 * 1024 * 1024), 2),
                "free_gb": round(disk.free / (1024 * 1024 * 1024), 2),
                "percent": disk.percent
            }
        },
        "bot_pool": {
            "total_configured": len(active_clients),
            "total_online": len(active_uids),
            "total_locked": locked_bots_count,
            "total_unlocked_available": free_bots_count,
        },
        "bots": bot_details,
        "running_python_processes": python_processes,
        "exploit_history_count": len(exploit_history),
        "recent_exploits": exploit_history[:10]
    }
    
    return jsonify(server_stats)

@app.route('/allstats', methods=['GET'])
def get_all_stats_ui():
    """
    Renders an interactive, real-time Telemetry Dashboard UI for viewing bot pool health,
    CPU/RAM usage, process breakdown, lock concurrency, and live statistics.
    """
    dashboard_html = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>FREE5GROUP - Telemetry & Bot Control Center</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg: #0b0f19;
            --card-bg: rgba(23, 31, 51, 0.7);
            --card-border: rgba(255, 255, 255, 0.08);
            --primary: #6366f1;
            --primary-glow: rgba(99, 102, 241, 0.35);
            --success: #10b981;
            --success-glow: rgba(16, 185, 129, 0.35);
            --warning: #f59e0b;
            --danger: #ef4444;
            --text-main: #f3f4f6;
            --text-muted: #9ca3af;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Inter', sans-serif; }
        body { background: var(--bg); color: var(--text-main); padding: 24px; min-height: 100vh; background-image: radial-gradient(circle at 10% 20%, rgba(99, 102, 241, 0.15) 0%, transparent 40%), radial-gradient(circle at 90% 80%, rgba(16, 185, 129, 0.15) 0%, transparent 40%); }
        .container { max-width: 1400px; margin: 0 auto; }
        header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; padding-bottom: 16px; border-bottom: 1px solid var(--card-border); }
        .logo-title { display: flex; align-items: center; gap: 14px; }
        .logo-badge { background: linear-gradient(135deg, #6366f1, #a855f7); padding: 8px 14px; border-radius: 10px; font-weight: 800; font-size: 1.1rem; box-shadow: 0 0 20px var(--primary-glow); }
        .live-badge { display: flex; align-items: center; gap: 8px; background: rgba(16, 185, 129, 0.12); color: var(--success); border: 1px solid rgba(16, 185, 129, 0.3); padding: 6px 14px; border-radius: 20px; font-size: 0.85rem; font-weight: 600; }
        .pulse-dot { width: 8px; height: 8px; background: var(--success); border-radius: 50%; box-shadow: 0 0 10px var(--success); animation: pulse 1.5s infinite; }
        @keyframes pulse { 0% { opacity: 0.4; } 50% { opacity: 1; transform: scale(1.2); } 100% { opacity: 0.4; } }
        
        .metrics-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 16px; margin-bottom: 28px; }
        .card { background: var(--card-bg); backdrop-filter: blur(12px); border: 1px solid var(--card-border); border-radius: 16px; padding: 20px; transition: transform 0.2s, box-shadow 0.2s; }
        .card:hover { border-color: rgba(255, 255, 255, 0.2); }
        .card-header { display: flex; justify-content: space-between; align-items: center; color: var(--text-muted); font-size: 0.85rem; font-weight: 600; text-transform: uppercase; margin-bottom: 12px; }
        .metric-value { font-size: 2rem; font-weight: 700; color: #fff; }
        .progress-bar-bg { width: 100%; height: 8px; background: rgba(255, 255, 255, 0.1); border-radius: 4px; margin-top: 12px; overflow: hidden; }
        .progress-bar-fill { height: 100%; background: linear-gradient(90deg, #6366f1, #10b981); border-radius: 4px; transition: width 0.4s ease; }
        
        .section-title { font-size: 1.25rem; font-weight: 700; margin-bottom: 16px; display: flex; justify-content: space-between; align-items: center; }
        .bots-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 16px; margin-bottom: 32px; }
        .bot-card { background: var(--card-bg); border: 1px solid var(--card-border); border-radius: 14px; padding: 18px; position: relative; }
        .bot-card.locked { border-color: rgba(245, 158, 11, 0.4); background: rgba(245, 158, 11, 0.05); }
        .bot-card.online { border-color: rgba(16, 185, 129, 0.3); }
        .bot-uid { font-size: 1.1rem; font-weight: 700; display: flex; align-items: center; justify-content: space-between; }
        .status-tag { font-size: 0.75rem; padding: 4px 10px; border-radius: 12px; font-weight: 700; text-transform: uppercase; }
        .tag-online { background: rgba(16, 185, 129, 0.2); color: #34d399; }
        .tag-locked { background: rgba(245, 158, 11, 0.2); color: #fbbf24; }
        .tag-offline { background: rgba(239, 68, 68, 0.2); color: #f87171; }
        
        .bot-stats-row { display: flex; justify-content: space-between; margin-top: 12px; padding-top: 10px; border-top: 1px solid rgba(255, 255, 255, 0.06); font-size: 0.85rem; color: var(--text-muted); }
        .bot-stats-row span strong { color: #fff; }

        table { width: 100%; border-collapse: collapse; margin-top: 12px; font-size: 0.9rem; }
        th, td { padding: 12px 16px; text-align: left; border-bottom: 1px solid var(--card-border); }
        th { color: var(--text-muted); font-weight: 600; text-transform: uppercase; font-size: 0.8rem; background: rgba(255, 255, 255, 0.02); }
        tr:hover { background: rgba(255, 255, 255, 0.03); }
        .btn-api { background: rgba(99, 102, 241, 0.2); color: #818cf8; border: 1px solid rgba(99, 102, 241, 0.4); padding: 8px 16px; border-radius: 8px; font-size: 0.85rem; font-weight: 600; text-decoration: none; transition: all 0.2s; }
        .btn-api:hover { background: var(--primary); color: #fff; }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div class="logo-title">
                <div class="logo-badge">FREE5GROUP</div>
                <div>
                    <h2>Server Telemetry & Bot Monitor</h2>
                    <p style="color: var(--text-muted); font-size: 0.85rem;">Real-time Bot Pool Inspection & System Metrics</p>
                </div>
            </div>
            <div style="display: flex; gap: 12px; align-items: center;">
                <div class="live-badge"><div class="pulse-dot"></div> LIVE AUTO-REFRESH (2s)</div>
                <a href="/api/allstats" target="_blank" class="btn-api">🔗 Raw JSON API</a>
            </div>
        </header>

        <!-- Top Overview Cards -->
        <div class="metrics-grid">
            <div class="card">
                <div class="card-header"><span>CPU Usage</span> <span>💻</span></div>
                <div class="metric-value" id="cpu-val">0%</div>
                <div class="progress-bar-bg"><div class="progress-bar-fill" id="cpu-bar" style="width: 0%;"></div></div>
            </div>
            <div class="card">
                <div class="card-header"><span>RAM Usage</span> <span>🧠</span></div>
                <div class="metric-value" id="ram-val">0 MB</div>
                <div style="color: var(--text-muted); font-size: 0.8rem; margin-top: 4px;" id="ram-sub">Used: 0 / 0 MB</div>
                <div class="progress-bar-bg"><div class="progress-bar-fill" id="ram-bar" style="width: 0%;"></div></div>
            </div>
            <div class="card">
                <div class="card-header"><span>Active Bot Pool</span> <span>🤖</span></div>
                <div class="metric-value" id="bots-online-val">0</div>
                <div style="color: var(--text-muted); font-size: 0.8rem; margin-top: 4px;" id="bots-sub">Online Bots / Configured Pool</div>
            </div>
            <div class="card">
                <div class="card-header"><span>Lock Concurrency</span> <span>🔒</span></div>
                <div class="metric-value" id="lock-val">0</div>
                <div style="color: var(--text-muted); font-size: 0.8rem; margin-top: 4px;" id="lock-sub">Locked Squad Sessions Active</div>
            </div>
        </div>

        <!-- Bot Pool Section -->
        <div class="section-title">
            <span>Active Bot Instances</span>
            <input type="text" id="bot-search" placeholder="Search UID..." style="background: rgba(255,255,255,0.08); border: 1px solid var(--card-border); color: #fff; padding: 6px 14px; border-radius: 8px; font-size: 0.85rem;">
        </div>
        <div class="bots-grid" id="bots-container">
            <!-- Bot cards rendered dynamically -->
        </div>

        <!-- Python Processes Section -->
        <div class="section-title"><span>System Python Subprocesses</span></div>
        <div class="card" style="padding: 0; overflow: hidden; margin-bottom: 32px;">
            <table>
                <thead>
                    <tr>
                        <th>PID</th>
                        <th>Process Name</th>
                        <th>CPU %</th>
                        <th>RAM (MB)</th>
                        <th>Command Line</th>
                    </tr>
                </thead>
                <tbody id="proc-tbody">
                    <!-- Process rows rendered dynamically -->
                </tbody>
            </table>
        </div>

        <!-- Recent Attacks Feed -->
        <div class="section-title"><span>Recent Emote & Exploit Attacks</span></div>
        <div class="card" style="padding: 0; overflow: hidden;">
            <table>
                <thead>
                    <tr>
                        <th>Timestamp</th>
                        <th>Target</th>
                        <th>Emote ID</th>
                        <th>Mode</th>
                        <th>Bot UID</th>
                    </tr>
                </thead>
                <tbody id="attacks-tbody">
                    <!-- Attacks rows rendered dynamically -->
                </tbody>
            </table>
        </div>
    </div>

    <script>
        async function fetchStats() {
            try {
                const res = await fetch('/api/allstats');
                const data = await res.json();
                
                // Update Top Cards
                document.getElementById('cpu-val').innerText = `${data.system.cpu_percent}%`;
                document.getElementById('cpu-bar').style.width = `${Math.min(data.system.cpu_percent, 100)}%`;
                
                document.getElementById('ram-val').innerText = `${data.system.memory.percent}%`;
                document.getElementById('ram-sub').innerText = `Used: ${data.system.memory.used_mb} MB / ${data.system.memory.total_mb} MB`;
                document.getElementById('ram-bar').style.width = `${data.system.memory.percent}%`;
                
                document.getElementById('bots-online-val').innerText = `${data.bot_pool.total_online} / ${data.bot_pool.total_configured}`;
                document.getElementById('bots-sub').innerText = `Available Unlocked: ${data.bot_pool.total_unlocked_available} | Locked: ${data.bot_pool.total_locked}`;
                
                document.getElementById('lock-val').innerText = `${data.bot_pool.total_locked}`;
                document.getElementById('lock-sub').innerText = `Active Locked Sessions`;

                // Update Bot Grid
                const searchTerm = document.getElementById('bot-search').value.toLowerCase();
                const botsContainer = document.getElementById('bots-container');
                botsContainer.innerHTML = '';
                
                if (data.bots && data.bots.length > 0) {
                    data.bots.filter(b => b.uid.toLowerCase().includes(searchTerm)).forEach(bot => {
                        const isLocked = bot.is_locked;
                        const isOnline = bot.status === 'ONLINE';
                        const tagClass = isLocked ? 'tag-locked' : (isOnline ? 'tag-online' : 'tag-offline');
                        const statusLabel = isLocked ? 'LOCKED' : (isOnline ? 'ONLINE' : 'OFFLINE');
                        const cardBorderClass = isLocked ? 'locked' : (isOnline ? 'online' : '');
                        
                        const squadInfo = bot.insquad ? `In Squad (Members: ${bot.squad_member_count})` : 'Solo Mode';
                        const lockId = bot.lock_session_id ? `<code>${bot.lock_session_id}</code>` : 'None';
                        const remSec = (bot.lock_info && bot.lock_info.remaining_seconds) ? `${bot.lock_info.remaining_seconds}s remaining` : 'N/A';

                        const html = `
                            <div class="bot-card ${cardBorderClass}">
                                <div class="bot-uid">
                                    <span>🤖 ${bot.uid}</span>
                                    <span class="status-tag ${tagClass}">${statusLabel}</span>
                                </div>
                                <div class="bot-stats-row">
                                    <span>PID: <strong>${bot.pid || 'N/A'}</strong></span>
                                    <span>CPU: <strong>${bot.cpu_percent}%</strong></span>
                                    <span>RAM: <strong>${bot.memory_mb} MB</strong></span>
                                </div>
                                <div class="bot-stats-row">
                                    <span>Squad: <strong>${squadInfo}</strong></span>
                                </div>
                                <div class="bot-stats-row">
                                    <span>Lock Session: ${lockId}</span>
                                </div>
                                ${isLocked ? `<div class="bot-stats-row" style="color: #fbbf24;"><span>⏱️ Timer: ${remSec}</span></div>` : ''}
                            </div>
                        `;
                        botsContainer.innerHTML += html;
                    });
                } else {
                    botsContainer.innerHTML = '<p style="color: var(--text-muted); grid-column: 1/-1;">No bots active in pool.</p>';
                }

                // Update Processes Table
                const procTbody = document.getElementById('proc-tbody');
                procTbody.innerHTML = '';
                if (data.running_python_processes && data.running_python_processes.length > 0) {
                    data.running_python_processes.forEach(proc => {
                        procTbody.innerHTML += `
                            <tr>
                                <td><strong>${proc.pid}</strong></td>
                                <td>${proc.name}</td>
                                <td>${proc.cpu_percent}%</td>
                                <td>${proc.memory_mb} MB</td>
                                <td style="font-family: monospace; font-size: 0.8rem; color: var(--text-muted);">${proc.cmdline.slice(0, 80)}</td>
                            </tr>
                        `;
                    });
                }

                // Update Attacks Table
                const attacksTbody = document.getElementById('attacks-tbody');
                attacksTbody.innerHTML = '';
                if (data.recent_exploits && data.recent_exploits.length > 0) {
                    data.recent_exploits.forEach(att => {
                        attacksTbody.innerHTML += `
                            <tr>
                                <td>${att.timestamp || 'N/A'}</td>
                                <td>${att.target || att.team_code || 'N/A'}</td>
                                <td>${att.emote_id || 'N/A'}</td>
                                <td><span class="status-tag tag-online">${att.mode || 'quit'}</span></td>
                                <td>${att.bot_uid || 'N/A'}</td>
                            </tr>
                        `;
                    });
                }
            } catch (err) {
                console.error("Telemetry fetch error:", err);
            }
        }

        setInterval(fetchStats, 2000);
        fetchStats();
    </script>
</body>
</html>"""
    return render_template_string(dashboard_html)

if __name__ == '__main__':
    # Force templates dir exists
    os.makedirs('templates', exist_ok=True)
    
    # Initialize SQLite database
    init_db()
    
    # Start bot monitor thread (handles both initial start and auto-restart)
    threading.Thread(target=bot_monitor_loop, daemon=True).start()
    
    # Use dynamic port for Heroku or 5000 for local
    port = int(os.environ.get('PORT', 80))
    print(f"[SYSTEM] Web Server starting on port {port}...")
    app.run(host='0.0.0.0', port=port, debug=True, use_reloader=False)
