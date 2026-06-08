import urllib.request
import urllib.error
import time
import subprocess
import os

env = os.environ.copy()
p = subprocess.Popen(["venv\\Scripts\\python.exe", "-m", "uvicorn", "main:app", "--port", "8082"], env=env)
time.sleep(3)

def check_url(url):
    print(f"\n--- Checking {url} ---")
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req) as response:
            print("Status:", response.status)
            print("Body snippet:", response.read().decode('utf-8')[:200])
    except urllib.error.HTTPError as e:
        print("HTTPError Status:", e.code)
        print("Body:", e.read().decode('utf-8'))
    except Exception as e:
        print("Exception:", e)

check_url("http://127.0.0.1:8082/config")
check_url("http://127.0.0.1:8082/api/schedule")
check_url("http://127.0.0.1:8082/api/drivers")
check_url("http://127.0.0.1:8082/api/rules")
check_url("http://127.0.0.1:8082/api/settings")

p.terminate()
