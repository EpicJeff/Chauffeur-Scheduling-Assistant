import re

with open('e:/repositories/Chauffeur/chauffeur/main.py', 'r', encoding='utf-8') as f:
    content = f.read()

endpoints = """from fastapi.responses import FileResponse
@app.get("/sw.js")
def get_service_worker():
    return FileResponse(os.path.join(STATIC_DIR, "sw.js"), media_type="application/javascript")

@app.get("/api/vapid_public_key")"""

content = content.replace("@app.get(\"/api/vapid_public_key\")", endpoints)

with open('e:/repositories/Chauffeur/chauffeur/main.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("main sw endpoint patched")
