"""Context-local admission to the day's planned-mission call allowance."""
from contextlib import contextmanager
from contextvars import ContextVar


class BudgetExhausted(Exception):
    pass


_guard: ContextVar[object | None] = ContextVar('mission_budget_guard', default=None)


@contextmanager
def guard():
    """Activate accounting, reusing an outer guard when nested."""
    current = _guard.get()
    if current is not None:
        yield current
        return
    current = object()
    token = _guard.set(current)
    try:
        yield current
    finally:
        _guard.reset(token)


def active() -> bool:
    return _guard.get() is not None


def charge(n: int = 1):
    """Reserve each call before work starts; unguarded callers are unchanged."""
    if not active():
        return
    # Missions imports the pool chain, which in turn imports this module.
    from services import missions, storage
    settings = storage.get_settings() or {}
    cap = int(settings.get('mission_cap_pro_calls', missions.CAPS_DEFAULT['pro_calls']))
    for _ in range(n):
        if not missions._bump_call('pro', cap):
            raise BudgetExhausted("the day's limit")
