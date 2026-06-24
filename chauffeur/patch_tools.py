import re

with open('services/agent_tools.py', 'r', encoding='utf-8') as f:
    content = f.read()

schemas = '''class AddErrandTool(BaseModel):
    """
    Adds a new errand to the queue.
    """
    title: str = Field(..., description="The name or title of the errand (e.g. 'Get Groceries').")
    duration_mins: int = Field(..., description="Estimated duration of the errand in minutes.")
    location: str = Field(..., description="The location of the errand.")
    priority: int = Field(default=2, description="Priority: 1 (High), 2 (Medium), 3 (Low).")
    tags: List[str] = Field(default=[], description="List of tags.")
    recurrence_rule: str = Field(default="", description="Recurrence: 'daily', 'weekly', 'monthly', or empty for one-off.")
    starts_on: float = Field(default=0.0, description="Unix timestamp for the anchor/starts-on date. If 0, uses current time.")

class UpdateErrandTool(BaseModel):
    """
    Updates an existing errand or marks it as completed.
    """
    errand_id: str = Field(..., description="The ID of the errand to update.")
    is_completed: bool = Field(default=False, description="Set to true to mark the errand as completed (this will automatically reschedule it if recurring).")
    title: str = Field(default="", description="Optional new title.")
    duration_mins: int = Field(default=0, description="Optional new duration.")
    location: str = Field(default="", description="Optional new location.")
    starts_on: float = Field(default=0.0, description="Optional new starts_on unix timestamp.")

class DeleteErrandTool(BaseModel):
    """
    Deletes an errand completely.
    """
    errand_id: str = Field(..., description="The ID of the errand to delete.")

class GetErrandsTool(BaseModel):
    """
    Gets a list of all active errands.
    """
    pass

# A unified schema registry'''

registry_additions = '''    "add_errand": AddErrandTool.model_json_schema(),
    "update_errand": UpdateErrandTool.model_json_schema(),
    "delete_errand": DeleteErrandTool.model_json_schema(),
    "get_errands": GetErrandsTool.model_json_schema(),
}'''

handlers = '''def handle_add_errand(args: dict) -> dict:
    from services import storage
    import time
    starts_on = args.get('starts_on', 0.0)
    if not starts_on: starts_on = time.time()
    errand = {
        'title': args.get('title'),
        'duration_mins': args.get('duration_mins', 30),
        'location': args.get('location'),
        'priority': args.get('priority', 2),
        'tags': args.get('tags', []),
        'recurrence_rule': args.get('recurrence_rule') or None,
        'starts_on': starts_on,
        'created_at': time.time(),
        'is_completed': False,
        'status': 'pending'
    }
    storage.add_errand(errand)
    return {"status": "success", "message": "Errand added."}

def handle_update_errand(args: dict) -> dict:
    from services import storage
    errand_id = args.get('errand_id')
    errand = storage.get_errand(errand_id)
    if not errand: return {"status": "error", "message": "Errand not found."}
    
    if args.get('is_completed'):
        storage.complete_errand(errand_id)
        return {"status": "success", "message": "Errand marked as completed and rescheduled if recurring."}
    
    update_data = {}
    if args.get('title'): update_data['title'] = args.get('title')
    if args.get('duration_mins'): update_data['duration_mins'] = args.get('duration_mins')
    if args.get('location'): update_data['location'] = args.get('location')
    if args.get('starts_on'): update_data['starts_on'] = args.get('starts_on')
    
    if update_data:
        storage.update_errand(errand_id, update_data)
        
    return {"status": "success", "message": "Errand updated."}

def handle_delete_errand(args: dict) -> dict:
    from services import storage
    storage.delete_errand(args.get('errand_id'))
    return {"status": "success", "message": "Errand deleted."}

def handle_get_errands(args: dict) -> dict:
    from services import storage
    errands = storage.get_all_errands()
    return {"status": "success", "errands": errands}

TOOL_HANDLERS = {'''

handler_registry = '''    "update_memory": handle_update_memory,
    "add_errand": handle_add_errand,
    "update_errand": handle_update_errand,
    "delete_errand": handle_delete_errand,
    "get_errands": handle_get_errands,
}'''

content = content.replace('# A unified schema registry', schemas)
content = content.replace('}', registry_additions, 1) # First occurrence of } in TOOL_SCHEMAS
content = content.replace('TOOL_HANDLERS = {', handlers)
content = content.replace('    "update_memory": handle_update_memory,\n}', handler_registry)

with open('services/agent_tools.py', 'w', encoding='utf-8') as f:
    f.write(content)
