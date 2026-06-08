import urllib.request
import urllib.error
import time
import subprocess
import os

env = os.environ.copy()
p = subprocess.Popen(["venv\\Scripts\\python.exe", "-m", "uvicorn", "main:app", "--port", "8081"], env=env)
time.sleep(3)

try:
    req = urllib.request.Request("http://127.0.0.1:8081/dashboard")
    with urllib.request.urlopen(req) as response:
        print("Status:", response.status)
        print(response.read().decode('utf-8')[:200])
except urllib.error.HTTPError as e:
    print("HTTPError Status:", e.code)
    print("Reason:", e.reason)
    print("Body:", e.read().decode('utf-8'))
except Exception as e:
    print("Exception:", e)

try:
    req2 = urllib.request.Request("http://127.0.0.1:8081/")
    with urllib.request.urlopen(req2) as response2:
        print("Status / :", response2.status)
except urllib.error.HTTPError as e:
    print("HTTPError Status /:", e.code)
    print("Body:", e.read().decode('utf-8'))

p.terminate()
