"""Small, family-safe action signals. Information alone is not an alarm."""
import datetime
from services import storage


def _signal(count=0, available=0):
    return {'count': count, 'available': available, 'known': True}


def _chores(now):
    rows = storage.get_all_chores() or []
    # The unclaimed chore pot is an opportunity, not household debt.
    return _signal(sum(r.get('state') in ('claimed', 'done') or
                       (r.get('state') == 'open' and bool(r.get('owner')))
                       for r in rows),
                   sum(r.get('state') == 'open' for r in rows))


def _routines(now):
    from services import runway
    count = remaining = 0
    for member in storage.get_all_members() or []:
        rows = storage.routines_for_day(member['id'], now.date().isoformat())
        for row in rows:
            if row.get('checked') or row.get('is_optional'):
                continue
            remaining += 1
            at = runway._hhmm_to_dt(now.date().isoformat(), row.get('time_of_day'))
            if at and at + datetime.timedelta(minutes=runway.GRACE_MINS) <= now:
                count += 1
    return _signal(count, remaining)


def _tasks(now):
    rows = storage.get_household_tasks() or []
    return _signal(sum(bool(r.get('due_date') and
                            r['due_date'] <= now.date().isoformat()) for r in rows), len(rows))


def _errands(now):
    rows = [r for r in storage.get_all_errands() or []
            if not r.get('is_completed') and r.get('status') != 'completed']
    return _signal(sum(r.get('status') == 'past_due' for r in rows), len(rows))


def _programs(now):
    from services import programs
    rows = programs.practice_windows(now.date(), now.date())
    # Practice is an invitation. Never turn progress or missed sessions into
    # an amber family scoreboard.
    return _signal(0, len(rows))


def state(now=None):
    now = now or datetime.datetime.now()
    if now.tzinfo is not None:
        now = now.astimezone().replace(tzinfo=None)
    result = {}
    for key, build in (('chores', _chores), ('routines', _routines),
                       ('tasks', _tasks), ('errands', _errands), ('programs', _programs)):
        try:
            result[key] = build(now)
        except Exception:
            # A failed read cannot honestly promise that nothing needs attention.
            result[key] = {'count': 0, 'available': 0, 'known': False}
    return result
