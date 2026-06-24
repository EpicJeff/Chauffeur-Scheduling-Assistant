import main
from fastapi import BackgroundTasks

class DummyTasks:
    def add_task(self, *args, **kwargs): pass

try:
    res = main.get_schedule(DummyTasks(), '2026-06-01T00:00:00-04:00', '2026-06-30T23:59:59-04:00', False)
    print(res)
except Exception as e:
    import traceback
    traceback.print_exc()
