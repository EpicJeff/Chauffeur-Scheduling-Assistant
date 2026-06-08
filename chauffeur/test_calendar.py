from services.calendar import get_calendar_service
import traceback

try:
    print("Testing get_calendar_service...")
    service = get_calendar_service()
    print("Success:", service)
except Exception as e:
    print("Exception:")
    traceback.print_exc()
