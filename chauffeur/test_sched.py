import main
from fastapi import BackgroundTasks

class DummyTasks:
    def add_task(self, *args, **kwargs): pass

try:
    res = main.get_schedule(DummyTasks(), '2026-06-01T00:00:00Z', '2026-06-30T23:59:59Z', False)
    print('Num events:', len(res.get('events', [])))
    if res.get('events'):
        print(res['events'][0].keys() if isinstance(res['events'][0], dict) else dir(res['events'][0]))
except Exception as e:
    import traceback
    traceback.print_exc()
