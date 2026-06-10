import re

with open('e:/repositories/Chauffeur/chauffeur/main.py', 'r', encoding='utf-8') as f:
    content = f.read()

imports = """import subprocess
from pydantic import BaseModel
from typing import Dict, Any

class PushSubscription(BaseModel):
    driver_id: str
    subscription: Dict[str, Any]

class DriveStatus(BaseModel):
    leg_id: str
    status: str
"""
content = content.replace("from fastapi import FastAPI, Request", imports + "\nfrom fastapi import FastAPI, Request")

endpoints = """
@app.get("/api/vapid_public_key")
def get_vapid_public_key():
    # Return the URL-safe base64 VAPID public key
    return {"public_key": "BLq6066CQlVR7OfljOCtbfedooq5P4L9g0pS2z7vVUt1bVC-0wbyF_iZIGwva_igQkYcDw6CIpBqsOIbFoSbbl8"}

@app.post("/api/push_subscribe")
def push_subscribe(sub: PushSubscription):
    storage.save_push_subscription(sub.driver_id, sub.subscription)
    return {"status": "ok"}

@app.post("/api/drive_status")
def update_drive_status(status: DriveStatus):
    storage.mark_drive_status(status.leg_id, status.status)
    return {"status": "ok"}
"""
content = content.replace("@app.get(\"/api/schedule\")", endpoints + "\n@app.get(\"/api/schedule\")")

schedule_endpoint_old = """    return cache_doc"""
schedule_endpoint_new = """    cache_doc['completed_drives'] = storage.get_completed_drives()
    return cache_doc"""
content = content.replace(schedule_endpoint_old, schedule_endpoint_new)

with open('e:/repositories/Chauffeur/chauffeur/main.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("main patched")
