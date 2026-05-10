# Deployment Guide - MV Creator PRO

## Option 1: VPS (Recommended)
Since this bot requires **persistent TCP connections** and **background processes**, a VPS is the best choice.
1. Install Python 3.9+
2. Clone the repo.
3. Run `pip install -r requirements.txt`
4. Run `python web.py`
5. Access via `http://your-vps-ip:5000`

## Option 2: Vercel (Web Interface Only)
Vercel is serverless and **cannot run the bots**. Use this ONLY for the UI.
1. Connect your GitHub repo to Vercel.
2. Vercel will automatically detect `vercel.json` and `web.py`.
3. Note: Bot startup and file saving will NOT work on Vercel.

## Option 3: Render / Railway
Good for persistent Flask apps.
1. Create a "Web Service".
2. Set Build Command: `pip install -r requirements.txt`
3. Set Start Command: `gunicorn web:app`
