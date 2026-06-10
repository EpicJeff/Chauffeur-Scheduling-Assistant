import re

with open('e:/repositories/Chauffeur/chauffeur/main.py', 'r', encoding='utf-8') as f:
    content = f.read()

push_loop_code = """import time
from datetime import datetime, timezone
import json
import asyncio
import os

async def push_notification_loop():
    while True:
        try:
            from services import storage
            
            cache_doc = storage.cache_table.all()
            if not cache_doc:
                await asyncio.sleep(60)
                continue
            cache_doc = cache_doc[0]
            
            schedule = cache_doc.get("schedule")
            events = {e["id"]: e for e in cache_doc.get("events", [])}
            if not schedule:
                await asyncio.sleep(60)
                continue
                
            now_ts = datetime.now().timestamp()
            subs = storage.get_push_subscriptions()
            completed = storage.get_completed_drives()
            
            vapid_private_key = "data/vapid_private.pem"
            if not os.path.exists(vapid_private_key):
                await asyncio.sleep(60)
                continue

            # Reconstruct the legs
            for d_id, items in schedule.items():
                initial_edges = items.get("initial_edges", {})
                route_edges = items.get("route_edges", {})
                final_edges = items.get("final_edges", {})
                
                # Check Initial Edges
                for ev_id, edge in initial_edges.items():
                    ev = events.get(ev_id)
                    if not ev: continue
                    dep_time = datetime.fromisoformat(ev["start"]).timestamp() - (edge.get("travel_mins", 0) + 5) * 60
                    leg_id = f"init_{ev_id}"
                    
                    if leg_id not in completed and 0 <= dep_time - now_ts <= 60:
                        send_push(d_id, subs, "Time to Leave!", f"Drive to {ev['location'].split(',')[0]}", leg_id)
                        
                # Check Route Edges
                for ev_id, edge in route_edges.items():
                    ev = events.get(ev_id)
                    next_ev = events.get(edge.get("to_event", ""))
                    if not ev or not next_ev: continue
                    
                    dep_time = datetime.fromisoformat(ev["end"]).timestamp()
                    leg_id = f"route_{ev_id}_{next_ev['id']}"
                    title = f"Drive to {next_ev['location'].split(',')[0]}"

                    if leg_id not in completed and 0 <= dep_time - now_ts <= 60:
                        send_push(d_id, subs, "Time to Leave!", title, leg_id)

                # Check Final Edges
                for ev_id, edge in final_edges.items():
                    ev = events.get(ev_id)
                    if not ev: continue
                    dep_time = datetime.fromisoformat(ev["end"]).timestamp()
                    leg_id = f"final_{ev_id}"

                    if leg_id not in completed and 0 <= dep_time - now_ts <= 60:
                        send_push(d_id, subs, "Time to Leave!", "Drive Home", leg_id)
                        
        except Exception as e:
            print(f"Error in push loop: {e}")
            
        await asyncio.sleep(60)

def send_push(d_id, subs, title, body, leg_id):
    from pywebpush import webpush, WebPushException
    import json
    for sub in subs:
        if sub.get("driver_id") == d_id:
            try:
                webpush(
                    subscription_info=sub["subscription"],
                    data=json.dumps({"title": title, "body": body, "actions": [{"action": "complete", "title": "Mark Completed"}], "data": {"leg_id": leg_id}}),
                    vapid_private_key="data/vapid_private.pem",
                    vapid_claims={"sub": "mailto:admin@example.com"}
                )
                print(f"Sent push to {d_id}: {title} - {body}")
            except WebPushException as ex:
                print(f"Push failed: {repr(ex)}")
"""

content = content.replace("async def lifespan(app: FastAPI):", push_loop_code + "\nasync def lifespan(app: FastAPI):")
content = content.replace("task = asyncio.create_task(poll_schedule())", "task = asyncio.create_task(poll_schedule())\n    push_task = asyncio.create_task(push_notification_loop())")
content = content.replace("task.cancel()", "task.cancel()\n    push_task.cancel()")

with open('e:/repositories/Chauffeur/chauffeur/main.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("push loop patched")
