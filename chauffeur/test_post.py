import requests
import json

base_url = "http://127.0.0.1:8083"

import subprocess
import time
import os

env = os.environ.copy()
p = subprocess.Popen(["venv\\Scripts\\python.exe", "-m", "uvicorn", "main:app", "--port", "8083"], env=env)
time.sleep(3)

def check_post(url, data):
    print(f"\n--- POST {url} ---")
    try:
        res = requests.post(base_url + url, json=data)
        print("Status:", res.status_code)
        print("Body:", res.text)
    except Exception as e:
        print("Exception:", e)

check_post("/api/drivers", {"id": "d1", "name": "Test Driver", "color_code": "#FF0000"})
check_post("/api/rules", {"id": "r1", "driver_id": "d1", "constraint_type": "required", "event_keyword": "Soccer"})
check_post("/api/settings", {"calendar_ids": ["test"]})

p.terminate()
