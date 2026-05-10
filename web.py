import json
import requests
import os
import time
import threading
import logging
import subprocess
import signal
import sys
from flask import Flask, jsonify, request, render_template, Response

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

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/group')
def group_page():
    return render_template('group.html')

@app.route('/robots.txt')
def robots():
    return send_from_directory(os.getcwd(), 'robots.txt')

@app.route('/api/accounts', methods=['GET'])
def get_accounts():
    if not os.path.exists('bot.txt'):
        return jsonify({})
    with open('bot.txt', 'r') as f:
        data = json.load(f)
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
        return jsonify([])
    with open('bot.txt', 'r') as f:
        try:
            stored_bots = json.load(f)
        except:
            stored_bots = {}
            
    statuses = []
    for uid, _ in stored_bots.items():
        if uid in active_clients:
            # Check if process is still running
            proc = active_clients[uid]
            if proc.poll() is None:
                # Running
                status_info = bot_statuses.get(uid, {"status": "Connecting...", "name": "Unknown", "team": "Single"})
                statuses.append({
                    "uid": uid,
                    "name": status_info.get("name", "Unknown"),
                    "status": status_info.get("status", "Unknown"),
                    "team": status_info.get("team", "Single"),
                    "pid": proc.pid
                })
            else:
                # Dead
                statuses.append({
                    "uid": uid,
                    "name": bot_statuses.get(uid, {}).get("name", "Offline"),
                    "status": "Offline / Crashed",
                    "team": "-"
                })
        else:
            statuses.append({
                "uid": uid,
                "name": "Offline",
                "status": "Offline",
                "team": "-"
            })
    return jsonify(statuses)

@app.route('/api/accounts', methods=['POST'])
def add_account():
    req = request.json
    uid = req.get('uid')
    pwd = req.get('password')
    data = {}
    if os.path.exists('bot.txt'):
        with open('bot.txt', 'r') as f:
            try:
                data = json.load(f)
            except:
                pass
    data[uid] = pwd
    with open('bot.txt', 'w') as f:
        json.dump(data, f, indent=4)
    return jsonify({"status": "success", "message": "Account added."})

def logic_start_bots():
    if not os.path.exists('bot.txt'):
        return 0, "No accounts found."
    with open('bot.txt', 'r') as f:
        data = json.load(f)
    
    started = 0
    for uid, pwd in data.items():
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
                data[uid] = pwd
                
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

if __name__ == '__main__':
    # Force templates dir exists
    os.makedirs('templates', exist_ok=True)
    
    # Start auto-launcher thread for local dev (if not on Heroku)
    if not os.environ.get('PORT'):
        threading.Thread(target=auto_start_bots, daemon=True).start()
    
    # Use dynamic port for Heroku or 5000 for local
    port = int(os.environ.get('PORT', 5000))
    print(f"[SYSTEM] Web Server starting on port {port}...")
    app.run(host='0.0.0.0', port=port, debug=True, use_reloader=False)
