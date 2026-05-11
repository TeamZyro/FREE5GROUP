import json
import requests
import os
import time
import threading
import logging
import subprocess
import signal
import sys
from flask import Flask, jsonify, request, render_template, Response, send_from_directory
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
            "ReleaseVersion": SITE_CONFIG.get('freefire_version', 'OB53'),
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 11; SM-A305F Build/RP1A.200720.012)",
            "Host": host,
            "Connection": "Keep-Alive"
        }
        res = requests.post(f"{base_url}/UpdateSocialBasicInfo", headers=headers, data=encrypted, timeout=30)
        return res.status_code == 200
    except Exception as e: raise Exception(str(e))


@app.route('/')
def index():
    return render_template('index.html')

@app.route('/group')
def group_page():
    return render_template('group.html')

@app.route('/bio')
def bio_page():
    return render_template('bio.html', config=SITE_CONFIG)

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
    bot_statuses[uid] = {"status": "Connecting...", "team": "Single", "name": "Loading..."}
    try:
        for line in iter(process.stdout.readline, ''):
            if not line:
                break
            log_line = line.strip()
            
            # Simple heuristic status extraction from the new main.py output
            if "Authentication successful" in log_line or "ONLINE" in log_line or "Server connection established" in log_line:
                bot_statuses[uid]["status"] = "Online"
            
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
        bot_statuses[uid]["status"] = "Offline"
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
    for bot_obj in data_list:
        uid = str(bot_obj.get('uid'))
        pwd = bot_obj.get('password')
        if uid not in active_clients or active_clients[uid].poll() is not None:
            try:
                # Spawn a completely independent process for each bot
                # Using sys.executable to ensure the same python environment
                cmd = [sys.executable, "main.py", str(uid), str(pwd)]
                
                # Force Python to not buffer stdout so logs appear instantly
                env = os.environ.copy()
                env["PYTHONUNBUFFERED"] = "1"
                
                # Start process and pipe stdout/stderr
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, # Merge stderr into stdout
                    text=True,
                    bufsize=1, # Line buffered
                    env=env
                )
                
                active_clients[uid] = proc
                
                # Start a thread to read the logs without blocking the web server
                log_thread = threading.Thread(target=log_reader, args=(proc, uid))
                log_thread.daemon = True
                log_thread.start()
                
                started += 1
                time.sleep(1) # Start staggering
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
        data = json.load(f)
    
    started = 0
    for uid in uids:
        uid = str(uid)
        if uid in data:
            pwd = data[uid]
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
def send_ipc_command(uid, command):
    port_file = f".ipc/{uid}.port"
    if not os.path.exists(port_file): 
        logging.error(f"[IPC] Port file missing for {uid}")
        return None
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

@app.route('/api/group_exploit', methods=['POST'])
def group_exploit():
    uid = request.json.get('uid')
    slot = request.json.get('slot', 5)
    if not uid:
        return jsonify({"status": "error", "message": "UID required"}), 400
        
    # Use the first active bot to send command
    active_uids = [u for u in active_clients.keys() if active_clients[u].poll() is None]
    if not active_uids:
        return jsonify({"status": "error", "message": "No active bots connected"}), 400
        
    bot_uid = active_uids[0]
    resp = send_ipc_command(bot_uid, f"GROUP_EXPLOIT {uid} {slot}")
    
    if resp and "SUCCESS" in resp:
        return jsonify({"status": "success", "message": "Exploit sequence initiated."})
    else:
        return jsonify({"status": "error", "message": resp or "Failed to communicate with bot"})

@app.route('/api/send_bot_command', methods=['POST'])
def send_bot_command():
    data = request.json
    cmd_type = data.get('type')
    payload = data.get('payload', '')
    
    # Map friendly types to IPC commands
    type_map = {
        "invite": "INVITE",
        "like": "LIKE",
        "check_ban": "CHECK_BAN",
        "kick": "KICK",
        "room_msg": "ROOM_MSG"
    }
    
    ipc_cmd = type_map.get(cmd_type)
    if not ipc_cmd:
        return jsonify({"status": "error", "message": "Invalid command type"}), 400
        
    active_uids = [u for u in active_clients.keys() if active_clients[u].poll() is None]
    if not active_uids:
        return jsonify({"status": "error", "message": "No active bots connected"}), 400
        
    bot_uid = active_uids[0]
    resp = send_ipc_command(bot_uid, f"{ipc_cmd} {payload}")
    
    if resp and "SUCCESS" in resp:
        return jsonify({"status": "success", "message": resp.split("SUCCESS: ")[-1]})
    else:
        return jsonify({"status": "error", "message": resp or "Failed to execute command"})

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
    """Background thread to auto-restart crashed bots"""
    while True:
        try:
            if os.path.exists('bot.txt'):
                with open('bot.txt', 'r') as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        data_list = [{"uid": k, "password": v} for k, v in data.items()]
                    else:
                        data_list = data
                
                for bot_obj in data_list:
                    uid = str(bot_obj.get('uid'))
                    pwd = bot_obj.get('password')
                    
                    # If bot is not in active_clients or has stopped
                    if uid not in active_clients or active_clients[uid].poll() is not None:
                        logging.info(f"[MONITOR] Restarting bot {uid}...")
                        
                        cmd = [sys.executable, "main.py", str(uid), str(pwd)]
                        env = os.environ.copy()
                        env["PYTHONUNBUFFERED"] = "1"
                        
                        proc = subprocess.Popen(
                            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, bufsize=1, env=env
                        )
                        active_clients[uid] = proc
                        threading.Thread(target=log_reader, args=(proc, uid), daemon=True).start()
                        time.sleep(1) # Stagger restarts
        except Exception as e:
            logging.error(f"[MONITOR] Loop error: {e}")
        time.sleep(30) # Check every 30 seconds

if __name__ == '__main__':
    # Force templates dir exists
    os.makedirs('templates', exist_ok=True)
    
    # Start bot monitor thread (handles both initial start and auto-restart)
    threading.Thread(target=bot_monitor_loop, daemon=True).start()
    
    # Use dynamic port for Heroku or 5000 for local
    port = int(os.environ.get('PORT', 5000))
    print(f"[SYSTEM] Web Server starting on port {port}...")
    app.run(host='0.0.0.0', port=port, debug=True, use_reloader=False)
