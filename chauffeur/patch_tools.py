import json
import re

with open('e:/repositories/Chauffeur/chauffeur/services/agent_tools.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Add schemas
schemas = '''class StartDriveTool(BaseModel):
    \"\"\"Logs a telemetry event that the driver has started a leg, and returns a navigation URL.\"\"\"
    driver_id: str = Field(..., description="The ID of the driver.")
    event_id: str = Field(..., description="The ID of the event/errand the driver is heading to.")
    destination: str = Field(..., description="The location the driver is heading to.")

class UpdateDriveStatusTool(BaseModel):
    \"\"\"Updates the completion status of a drive leg or event.\"\"\"
    event_id: str = Field(..., description="The exact event ID to mark completed.")
    status: str = Field(default="completed", description="The status, usually 'completed'.")
    leg_id: str = Field(default="", description="The exact leg ID if known (e.g. 'route_evt1_evt2').")

# A unified schema registry'''

content = content.replace('# A unified schema registry', schemas)

# Add to TOOL_SCHEMAS
tool_schemas_addition = '''TOOL_SCHEMAS = {
    "start_drive": StartDriveTool.model_json_schema(),
    "update_drive_status": UpdateDriveStatusTool.model_json_schema(),'''

content = content.replace('TOOL_SCHEMAS = {', tool_schemas_addition)

# Add handlers
handlers = '''
def handle_start_drive(args: dict) -> dict:
    from services import storage
    import urllib.parse
    event = {
        "driver_id": args.get("driver_id"),
        "event_id": args.get("event_id"),
        "action": "started driving",
        "location": args.get("destination")
    }
    storage.add_telemetry_event(event)
    dest = urllib.parse.quote(args.get("destination", ""))
    return {
        "status": "success",
        "message": f"Navigation link: https://www.google.com/maps/dir/?api=1&destination={dest}"
    }

def handle_update_drive_status(args: dict) -> dict:
    from services import storage
    leg_id = args.get("leg_id")
    event_id = args.get("event_id")
    status = args.get("status", "completed")
    
    if leg_id:
        storage.mark_drive_status(leg_id, status)
    if event_id:
        storage.mark_drive_status(f"route_{event_id}", status)
        storage.mark_drive_status(f"final_{event_id}", status)
        storage.mark_drive_status(f"route_{event_id}_1", status)
        storage.mark_drive_status(f"route_{event_id}_2", status)
        # We don't know the full route_{prev}_{event} but this covers single legs.

    return {"status": "success", "message": f"Marked drive status as {status}."}

TOOL_HANDLERS = {'''

content = content.replace('TOOL_HANDLERS = {', handlers)

# Add to TOOL_HANDLERS
tool_handlers_addition = '''TOOL_HANDLERS = {
    "start_drive": handle_start_drive,
    "update_drive_status": handle_update_drive_status,'''

content = content.replace('TOOL_HANDLERS = {', tool_handlers_addition)

with open('e:/repositories/Chauffeur/chauffeur/services/agent_tools.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("Done")
