import os
import re

filepath = 'main.py'
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Update Errands API
api_orig = '''# --- Errands API ---
@app.get("/api/errands")
def get_errands():
    return storage.get_all_errands()

@app.post("/api/errands")
def create_errand(errand: Errand, background_tasks: BackgroundTasks):
    doc_id = storage.add_errand(errand.model_dump() if hasattr(errand, 'model_dump') else errand.dict())
    background_tasks.add_task(trigger_background_refresh)
    return {"doc_id": doc_id, "status": "created"}

@app.put("/api/errands/{doc_id}")
def update_errand(doc_id: int, errand: Errand, background_tasks: BackgroundTasks):
    storage.update_errand(doc_id, errand.model_dump() if hasattr(errand, 'model_dump') else errand.dict())
    background_tasks.add_task(trigger_background_refresh)
    return {"status": "updated"}'''

api_new = '''# --- Errands API ---
def check_past_due_errands():
    errands = storage.get_all_errands()
    import time
    now_ts = time.time()
    for e in errands:
        if not e.get('is_completed') and e.get('status', 'pending') != 'past_due':
            lse = e.get('last_scheduled_end')
            if lse and lse < now_ts:
                e['status'] = 'past_due'
                storage.update_errand(e['doc_id'], e)

@app.get("/api/errands")
def get_errands():
    check_past_due_errands()
    raw = storage.get_all_errands()
    return [Errand(**e).model_dump() if hasattr(Errand(**e), 'model_dump') else Errand(**e).dict() for e in raw]

@app.post("/api/errands")
def create_errand(errand: Errand, background_tasks: BackgroundTasks):
    doc_id = storage.add_errand(errand.model_dump() if hasattr(errand, 'model_dump') else errand.dict())
    background_tasks.add_task(trigger_background_refresh)
    return {"doc_id": doc_id, "status": "created"}

@app.put("/api/errands/{doc_id}")
def update_errand(doc_id: int, errand: Errand, background_tasks: BackgroundTasks):
    # Check for recurrence trigger
    old_e_list = [e for e in storage.get_all_errands() if e['doc_id'] == doc_id]
    if old_e_list:
        old_e = old_e_list[0]
        if not old_e.get('is_completed') and errand.is_completed and errand.recurrence_rule:
            new_e = errand.model_dump() if hasattr(errand, 'model_dump') else errand.dict()
            import uuid
            import time
            new_e['id'] = uuid.uuid4().hex
            new_e['is_completed'] = False
            new_e['status'] = 'pending'
            new_e['last_scheduled_end'] = None
            new_e['created_at'] = time.time()
            if 'doc_id' in new_e:
                del new_e['doc_id']
            storage.add_errand(new_e)

    storage.update_errand(doc_id, errand.model_dump() if hasattr(errand, 'model_dump') else errand.dict())
    background_tasks.add_task(trigger_background_refresh)
    return {"status": "updated"}'''

content = content.replace(api_orig, api_new)

# 2. Update last_scheduled_end saving logic inside _refresh_schedule_logic_impl
# Find where scheduled_errands is generated and appended
sched_orig = '''            scheduled_errands = matcher.insert_errands_into_schedule(
                assignments=combined_assignments,
                events=combined_events_to_solve,
                errands=storage.get_all_errands(),
                drivers=drivers
            )'''

sched_new = '''            scheduled_errands = matcher.insert_errands_into_schedule(
                assignments=combined_assignments,
                events=combined_events_to_solve,
                errands=storage.get_all_errands(),
                drivers=drivers
            )
            
            # If this is the live master schedule, save the scheduled target times
            if not start_date_str and not end_date_str:
                import datetime
                import time
                all_db_errands = storage.get_all_errands()
                for se in scheduled_errands:
                    try:
                        # naive datetime string to timestamp
                        end_dt = datetime.datetime.fromisoformat(se['end'])
                        end_ts = end_dt.timestamp()
                        for db_e in all_db_errands:
                            if db_e['id'] == se['id']:
                                db_e['last_scheduled_end'] = end_ts
                                storage.update_errand(db_e['doc_id'], db_e)
                    except Exception as ex:
                        print(f"Error saving last_scheduled_end: {ex}")'''

content = content.replace(sched_orig, sched_new)

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(content)

print("main.py updated successfully")
