import sys
import os
import sqlite3

# Add current path to import path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from web import app, init_db

# Initialize DB
init_db()

# Query DB directly to verify
conn = sqlite3.connect("app_config.db")
cursor = conn.cursor()

print("AppConfig table info:")
cursor.execute("PRAGMA table_info(AppConfig)")
for col in cursor.fetchall():
    print(col)

print("\nAppConfig data:")
cursor.execute("SELECT * FROM AppConfig")
for row in cursor.fetchall():
    print(row)

print("\nVersion table info:")
cursor.execute("PRAGMA table_info(Version)")
for col in cursor.fetchall():
    print(col)

print("\nVersion data:")
cursor.execute("SELECT * FROM Version")
for row in cursor.fetchall():
    print(row)

conn.close()

# Test Flask app client
with app.test_client() as client:
    res = client.get('/api/version')
    print("\nAPI Response:")
    print(res.status_code)
    print(res.get_json())
