import urllib.request
import time
import subprocess
import os

env = os.environ.copy()
# Run uvicorn from the C:\ directory or something
p = subprocess.Popen(["E:\\repositories\\Graph-Calendar-Assistant\\venv\\Scripts\\python.exe", "-m", "uvicorn", "main:app", "--port", "8085"], env=env, cwd="C:\\")
time.sleep(3)

try:
    req = urllib.request.Request("http://127.0.0.1:8085/dashboard")
    with urllib.request.urlopen(req) as response:
        print("Status:", response.status)
except Exception as e:
    print("Exception:", e)

p.terminate()
