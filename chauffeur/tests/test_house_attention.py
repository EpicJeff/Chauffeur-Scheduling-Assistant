"""Attention means actionable work, not merely information or unread counts."""
import datetime
import json
from unittest.mock import patch
from harness import check
from services import house_attention as attention, house_room, storage


def scenario_attention_is_due_work():
    now = datetime.datetime(2026, 9, 14, 12)
    with patch.object(storage, 'get_all_chores', return_value=[
        {'state':'open'}, {'state':'claimed'}, {'state':'done'}, {'state':'verified'}]), \
         patch.object(storage, 'get_all_members', return_value=[{'id':'kid'}]), \
         patch.object(storage, 'routines_for_day', return_value=[
             {'time_of_day':'08:00'}, {'time_of_day':'19:00'},
             {'time_of_day':'09:00', 'checked':True}, {'title':'Untimed'}]), \
         patch.object(storage, 'get_household_tasks', return_value=[
             {'due_date':'2026-09-14'}, {'due_date':'2026-09-15'}, {'title':'Private detail'}]), \
         patch.object(storage, 'get_all_errands', return_value=[
             {'status':'past_due'}, {'status':'pending'}, {'status':'past_due','is_completed':True}]), \
         patch('services.programs.practice_windows', return_value=[{'title':'Private aim'}]):
        result = attention.state(now)
    check(result['chores']['count'] == 2, 'only assigned or awaiting-check chores demand attention')
    check(result['routines']['count'] == 1, 'future, checked and untimed routines stay quiet')
    check(result['tasks']['count'] == 1, 'only due household work lights up')
    check(result['errands']['count'] == 1, 'only overdue unfinished errands light up')
    check(result['programs']['count'] == 0 and result['programs']['available'] == 1,
          'practice is an invitation, not a deficit')
    check('Private' not in json.dumps(result), 'glance feed contains counts, never private descriptions')


def scenario_unavailable_is_not_all_clear():
    with patch.object(storage, 'get_all_chores', side_effect=RuntimeError('offline')):
        result = attention.state()
    check(result['chores']['known'] is False, 'failed provider must not promise quiet')


def scenario_packing_window_owns_the_glow():
    now = datetime.datetime(2026, 9, 14, 12)
    with patch('services.family_day.day_in_focus', return_value=now.date()), \
         patch('services.family_day.pack_window_opens', return_value='2026-09-14T11:00:00'), \
         patch('services.outings.outings_for', return_value=[{'key':'out','start':'2026-09-14T13:00:00'}]), \
         patch('services.outings.packing_for', return_value=[{'kit':'Practice', 'items':[{'key':'bottle','needed':2}]}]), \
         patch.object(storage, 'get_prep_kits', return_value=[]), \
         patch('services.prep_kits.passenger_objs', return_value=[]), \
         patch.object(storage, 'get_packing_claims', return_value=[{'outing_key':'out','item_key':'bottle'}]):
        packs, due = house_room._packs(now, {})
        check(due and packs[0]['attention'] and packs[0]['packed'] == 1, 'open window exposes missing items')
        early, due = house_room._packs(now.replace(hour=10), {})
        check(not due and not early[0]['attention'], 'tomorrow/future packing must not glow early')
        with patch('services.outings.outings_for', return_value=[{'key':'out', 'start':'2026-09-14T09:00:00', 'end':'2026-09-14T10:00:00'}]):
            finished, due = house_room._packs(now, {})
            check(not finished and not due, 'finished outings cannot leave stale packing alerts')


if __name__ == '__main__':
    scenario_attention_is_due_work()
    scenario_unavailable_is_not_all_clear()
    scenario_packing_window_owns_the_glow()
    print('House attention passed')
