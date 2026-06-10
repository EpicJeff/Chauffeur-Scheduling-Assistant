import re

with open('e:/repositories/Chauffeur/chauffeur/services/storage.py', 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace("telemetry_table = db.table('telemetry')", "telemetry_table = db.table('telemetry')\n    push_subscriptions_table = db.table('push_subscriptions')\n    drive_status_table = db.table('drive_status')")

new_methods = """
# Push Subscriptions
def save_push_subscription(driver_id: str, subscription_info: dict):
    with db_lock:
        push_subscriptions_table.upsert({'driver_id': driver_id, 'subscription': subscription_info}, Query().driver_id == driver_id)

def get_push_subscriptions(driver_id: str = None):
    with db_lock:
        if driver_id:
            return push_subscriptions_table.search(Query().driver_id == driver_id)
        return push_subscriptions_table.all()

# Drive Status
def mark_drive_status(leg_id: str, status: str):
    with db_lock:
        drive_status_table.upsert({'leg_id': leg_id, 'status': status}, Query().leg_id == leg_id)

def get_completed_drives():
    with db_lock:
        return [doc['leg_id'] for doc in drive_status_table.search(Query().status == 'completed')]
"""

content += new_methods

with open('e:/repositories/Chauffeur/chauffeur/services/storage.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("storage patched")
