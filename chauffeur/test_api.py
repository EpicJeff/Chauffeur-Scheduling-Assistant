from main import get_schedule
import traceback

try:
    res = get_schedule()
    print("Success get_schedule")
except Exception as e:
    print("Exception in get_schedule:")
    traceback.print_exc()

from main import get_drivers, get_rules, get_settings
try:
    print("Drivers:", get_drivers())
    print("Rules:", get_rules())
    print("Settings:", get_settings())
except Exception as e:
    print("Exception in basic APIs:")
    traceback.print_exc()
