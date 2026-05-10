# Deployment Guide - MV Creator PRO

## Option 1: VPS (Recommended)
Since this bot requires **persistent TCP connections** and **background processes**, a VPS is the best choice.
1. Install Python 3.9+
2. Clone the repo.
3. Run `pip install -r requirements.txt`
4. Run `python web.py`
5. Access via `http://your-vps-ip:5000`

## Option 2: Vercel (Web Interface Only)
Serverless. UI will work, but bots and file saving won't.
- Files: `vercel.json`, `web.py`

## Option 3: Heroku
Persistent but with **Ephemeral Storage**.
1. Files: `Procfile`, `runtime.txt`, `requirements.txt`.
2. Port: Automatically handled by `os.environ.get('PORT')`.
3. Storage: `bot.txt` will reset on every restart.

## Option 4: Render / Railway / PythonAnywhere
Good alternatives for persistent Python apps.
