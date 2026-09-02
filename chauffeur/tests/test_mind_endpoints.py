"""Endpoint behavior: filtered payloads, role gates, outcomes recorded."""
from harness import check
from services import storage, mind

def _reset():
    storage.mind_insights_table.truncate()
    storage.add_mind_insight({'slug': 'n1', 'line': 'normal', 'category': 'c',
                              'sensitivity': 'normal'})
    storage.add_mind_insight({'slug': 's1', 'line': 'secret', 'category': 'c',
                              'sensitivity': 'sensitive'})

def scenario_dismiss_records_outcome():
    _reset()
    row = storage.get_mind_insight_by_slug('n1')
    ok = storage.update_mind_insight(row['id'], {'state': 'retired',
                                                 'outcome': 'dismissed'})
    check(ok, "dismiss path writes retired/dismissed")

def scenario_act_records_outcome():
    _reset()
    row = storage.get_mind_insight_by_slug('n1')
    storage.update_mind_insight(row['id'], {'state': 'retired', 'outcome': 'acted'})
    check(storage.get_mind_insight_by_slug('n1')['outcome'] == 'acted',
          "act path writes retired/acted")

def scenario_lane_is_filtered():
    _reset()
    check(len(mind.visible_insights({'id': 'k', 'role': 'child'})) == 1,
          "child payload has no sensitive row")


# --- The admin surface, which is a place and not a person --------------------
# v2.430.1 taught `_mind_actor` that the control-center pages carry no member
# identity by design: they authenticate as a trusted PLACE, so an unresolved
# caller there is allowed through with no author recorded. What it did not
# teach is the APPROVAL gate underneath `act`, which is the one Mind endpoint
# that hands its actor to a second check -- `chat_actions.act_on_proposal`
# refuses anything `_is_admin` says no to, and `_is_admin(None)` is False. The
# result was a 400 "Only a parent can approve this" on the Mind page's own
# Approve button, on the screen that is already parent-only.


def _reset_people():
    storage.members_table.truncate()
    storage.add_member({'id': 'mom', 'name': 'Mom', 'role': 'parent'})
    storage.add_member({'id': 'kid', 'name': 'Lily', 'role': 'child'})


def _insight_with_proposal():
    from services import chat_actions as _ca
    prop = _ca.create_action_proposal(
        'reassign_driver', 'Give Tuesday soccer to Lorena',
        {'event_name': 'Soccer', 'driver_name': 'Lorena',
         'target_date': '2026-09-08'})
    iid = storage.add_mind_insight({
        'slug': 'p1', 'line': 'Jeff has three drives and Lorena has one',
        'category': 'load',
        'proposal_json': {'proposal_id': prop['proposal_id'],
                          'summary': 'Give it to Lorena'}})
    return iid, prop['proposal_id']


def scenario_the_admin_page_can_approve_without_a_member_identity():
    _reset(); _reset_people()
    import main
    from services import auth as _auth, chat_actions as _ca
    iid, pid = _insight_with_proposal()
    orig_identify, orig_execute = _auth.identify, _ca._execute
    try:
        _auth.identify = lambda h, q: {'tier': _auth.SERVICE, 'member': None}
        _ca._execute = lambda a, p: {'status': 'success', 'message': 'done'}
        res = main.mind_act(iid, body={}, request=None)
        check(res.get('status') == 'success',
              f"the Mind page's own Approve button must work, got {res}")
        check(storage.get_action_proposal(pid)['status'] == 'approved',
              "and the proposal really is approved")
        check(storage.get_action_proposal(pid)['approved_by_member_id'] == 'mom',
              "recorded against the household's parent of record")
        row = [r for r in storage.get_mind_insights() if r['id'] == iid][0]
        check(row.get('outcome') == 'acted', f"insight retired as acted, got {row}")
    finally:
        _auth.identify, _ca._execute = orig_identify, orig_execute


def scenario_a_named_parent_is_not_overwritten_by_the_nomination():
    """A claim beats the stand-in: whoever actually tapped is who approved."""
    _reset(); _reset_people()
    storage.add_member({'id': 'dad', 'name': 'Dad', 'role': 'parent'})
    import main
    from services import auth as _auth, chat_actions as _ca
    iid, pid = _insight_with_proposal()
    orig_identify, orig_execute = _auth.identify, _ca._execute
    try:
        _auth.identify = lambda h, q: {'tier': _auth.SERVICE, 'member': None}
        _ca._execute = lambda a, p: {'status': 'success', 'message': 'done'}
        main.mind_act(iid, body={'member_id': 'dad'}, request=None)
        check(storage.get_action_proposal(pid)['approved_by_member_id'] == 'dad',
              "the person who tapped is the person recorded")
    finally:
        _auth.identify, _ca._execute = orig_identify, orig_execute


def scenario_an_enrolled_panel_still_cannot_approve():
    """A wall panel is a place too, but a place in a hallway anyone walks past."""
    _reset(); _reset_people()
    import main
    from fastapi import HTTPException
    from services import auth as _auth
    iid, pid = _insight_with_proposal()
    orig = _auth.identify
    try:
        _auth.identify = lambda h, q: {'tier': _auth.DEVICE, 'device': {},
                                       'member': None}
        try:
            main.mind_act(iid, body={}, request=None)
            check(False, "an enrolled panel must not approve a Mind proposal")
        except HTTPException as e:
            check(e.status_code == 403, f"refused with 403, got {e.status_code}")
        check(storage.get_action_proposal(pid)['status'] == 'proposed',
              "and the proposal is untouched")
    finally:
        _auth.identify = orig


def scenario_no_parent_on_record_is_an_honest_refusal():
    """With nobody to stand in for, say so rather than approving anonymously."""
    _reset()
    storage.members_table.truncate()
    storage.add_member({'id': 'kid', 'name': 'Lily', 'role': 'child'})
    import main
    from fastapi import HTTPException
    from services import auth as _auth
    iid, pid = _insight_with_proposal()
    orig = _auth.identify
    try:
        _auth.identify = lambda h, q: {'tier': _auth.SERVICE, 'member': None}
        try:
            main.mind_act(iid, body={}, request=None)
            check(False, "with no parent on record this must not silently approve")
        except HTTPException as e:
            check(e.status_code in (400, 403), f"got {e.status_code}")
        check(storage.get_action_proposal(pid)['status'] == 'proposed',
              "and the proposal is untouched")
    finally:
        _auth.identify = orig


def scenario_snooze_clamps_and_parks():
    import time as _t
    from services import mind as _m
    storage.mind_insights_table.truncate()
    storage.members_table.truncate()
    storage.add_member({'id': 'mom', 'name': 'Mom', 'role': 'parent'})
    iid = storage.add_mind_insight({'slug': 'z', 'line': 'x', 'category': 'c'})
    import main
    from services import auth as _auth
    orig_identify = _auth.identify
    try:
        _auth.identify = lambda h, q: {'tier': _auth.SERVICE, 'member': None}
        # Test days=0 (clamped to 1)
        res = main.mind_snooze(iid, body={'days': 0}, request=None)
        check(res['days'] == 1, f"days=0 clamped to 1, got {res['days']}")
        row = storage.get_mind_insight_by_slug('z')
        check(row['snoozed_until'] > _t.time() + 0.5 * 86400 and
              row['snoozed_until'] < _t.time() + 1.5 * 86400,
              f"snoozed_until set to ~1 day from now")
        # Test days=7 (default range)
        res = main.mind_snooze(iid, body={'days': 7}, request=None)
        check(res['days'] == 7, f"days=7 unchanged, got {res['days']}")
        row = storage.get_mind_insight_by_slug('z')
        check(row['snoozed_until'] > _t.time() + 6.5 * 86400 and
              row['snoozed_until'] < _t.time() + 7.5 * 86400,
              f"snoozed_until set to ~7 days from now")
        # Test days=999 (clamped to 60)
        res = main.mind_snooze(iid, body={'days': 999}, request=None)
        check(res['days'] == 60, f"days=999 clamped to 60, got {res['days']}")
        row = storage.get_mind_insight_by_slug('z')
        check(row['snoozed_until'] > _t.time() + 59.5 * 86400,
              f"snoozed_until set to ~60 days from now")
        # Test body={} (default 7)
        res = main.mind_snooze(iid, body={}, request=None)
        check(res['days'] == 7, f"empty body defaults to 7, got {res['days']}")
        # Test non-numeric body (fallback 7)
        res = main.mind_snooze(iid, body={'days': 'x'}, request=None)
        check(res['days'] == 7, f"non-numeric days falls back to 7, got {res['days']}")
        # Test 404 for bogus insight id
        from fastapi import HTTPException
        try:
            main.mind_snooze('bogus_id', body={'days': 1}, request=None)
            check(False, "should raise 404 for bogus insight id")
        except HTTPException as e:
            check(e.status_code == 404, f"bogus id raises 404, got {e.status_code}")
        # Test that future-snoozed row is filtered from visible_insights
        check(all(r['slug'] != 'z' for r in _m.visible_insights(
            {'id': 'mom', 'role': 'parent'})),
          "snoozed row leaves the lane")
    finally:
        _auth.identify = orig_identify


def scenario_step_approve_rides_the_chat_rail():
    _reset(); _reset_people()
    import main
    from services import auth as _auth, chat_actions as _ca
    from fastapi import HTTPException
    iid, pid = _insight_with_proposal()
    # Update insight to in_hand state with plan containing the proposal
    storage.update_mind_insight(iid, {'state': 'in_hand', 'plan_json': {
        'created_ts': 1.0,
        'steps': [{'id': 's1', 'kind': 'tool', 'text': 't',
                   'owner_member_id': None, 'owner_name': '',
                   'due': '2026-09-02', 'status': 'open',
                   'proposal_json': {'proposal_id': pid, 'summary': 'S'}}]}})
    orig_identify, orig_execute = _auth.identify, _ca._execute
    try:
        _auth.identify = lambda h, q: {'tier': _auth.SERVICE, 'member': None}
        _ca._execute = lambda a, p: {'status': 'success', 'message': 'done'}
        # Call the endpoint to approve the step
        res = main.mind_step_approve(iid, 's1', body={}, request=None)
        check(res['status'] == 'success',
              f"step_approve returns success, got {res}")
        check(res['insight_state'] == 'retired',
              f"single-step plan retires on approve, got {res['insight_state']}")
        # Verify insight is retired as acted
        row = storage.get_mind_insight_by_slug('p1')
        check(row['outcome'] == 'acted',
              f"insight outcome is acted, got {row.get('outcome')}")
        # Verify step status is done
        steps = (row.get('plan_json') or {}).get('steps') or []
        step = next((s for s in steps if s.get('id') == 's1'), None)
        check(step['status'] == 'done',
              f"step status is done, got {step['status']}")
        # Verify proposal is approved
        check(storage.get_action_proposal(pid)['status'] == 'approved',
              "proposal is approved")
        # Test 400 when step has no proposal bound
        iid2 = storage.add_mind_insight({'slug': 'unbound', 'line': 'x', 'category': 'c'})
        storage.update_mind_insight(iid2, {'state': 'in_hand', 'plan_json': {
            'created_ts': 1.0,
            'steps': [{'id': 's2', 'kind': 'tool', 'text': 't',
                       'owner_member_id': None, 'owner_name': '',
                       'due': '2026-09-02', 'status': 'open',
                       'proposal_json': {}}]}})
        try:
            main.mind_step_approve(iid2, 's2', body={}, request=None)
            check(False, "should raise 400 for unbound step")
        except HTTPException as e:
            check(e.status_code == 400, f"unbound step raises 400, got {e.status_code}")
        # Test 404 for bogus step id
        try:
            main.mind_step_approve(iid, 'bogus_step', body={}, request=None)
            check(False, "should raise 404 for bogus step id")
        except HTTPException as e:
            check(e.status_code == 404, f"bogus step id raises 404, got {e.status_code}")
    finally:
        _auth.identify, _ca._execute = orig_identify, orig_execute


# --- A closed step is closed, and an approval that moves the schedule says so
# I2: `Skip` left the step's bound proposal sitting there, still approvable --
# so skipping was a suggestion, not an answer, and a stale card could still be
# fired. I5: a Mind approval runs the same typed actions a chat card runs, and
# `act_on_proposal` reports `schedule_dirty`; both Mind approve doors dropped
# it, so the wall kept showing the old driver until something else re-solved.


class _FakeBackground:
    """Stands in for FastAPI's BackgroundTasks so a direct call can see what
    the endpoint queued."""

    def __init__(self):
        self.tasks = []

    def add_task(self, fn, *a, **kw):
        self.tasks.append(fn)


def _planned_row_with_bound_step(step_status='open'):
    from services import chat_actions as _ca
    prop = _ca.create_action_proposal(
        'reassign_driver', 'Give Tuesday soccer to Lorena',
        {'event_name': 'Soccer', 'driver_name': 'Lorena',
         'target_date': '2026-09-08'})
    iid = storage.add_mind_insight({'slug': 'planned', 'category': 'load',
                                    'line': 'Tuesday is stacked'})
    storage.update_mind_insight(iid, {
        'state': 'in_hand',
        'plan_json': {'created_ts': 1.0, 'steps': [
            {'id': 's1', 'kind': 'tool', 'text': 'Hand Tuesday to Lorena',
             'owner_member_id': None, 'owner_name': '', 'due': '2026-09-08',
             'status': step_status,
             'proposal_json': {'proposal_id': prop['proposal_id'],
                               'summary': 'Give it to Lorena'}}]}})
    return iid, prop['proposal_id']


def scenario_a_skipped_step_cannot_be_approved():
    _reset(); _reset_people()
    import main
    from fastapi import HTTPException
    from services import auth as _auth, chat_actions as _ca
    iid, pid = _planned_row_with_bound_step(step_status='skipped')
    orig_identify, orig_execute = _auth.identify, _ca._execute
    ran = []
    try:
        _auth.identify = lambda h, q: {'tier': _auth.SERVICE, 'member': None}
        _ca._execute = lambda a, p: (ran.append(a) or
                                     {'status': 'success', 'message': 'done'})
        try:
            main.mind_step_approve(iid, 's1', body={}, request=None)
            check(False, "a skipped step must not be executable")
        except HTTPException as e:
            check(e.status_code == 400, f"refused with 400, got {e.status_code}")
            check('skipped' in (e.detail or ''), f"and says why, got {e.detail}")
        check(not ran, "nothing ran")
        check(storage.get_action_proposal(pid)['status'] == 'proposed',
              "the proposal is untouched, not spent")
    finally:
        _auth.identify, _ca._execute = orig_identify, orig_execute


def scenario_a_schedule_changing_step_approval_asks_for_a_resolve():
    _reset(); _reset_people()
    import main
    from services import auth as _auth, chat_actions as _ca
    iid, pid = _planned_row_with_bound_step()
    orig_identify, orig_execute = _auth.identify, _ca._execute
    bg = _FakeBackground()
    try:
        _auth.identify = lambda h, q: {'tier': _auth.SERVICE, 'member': None}
        _ca._execute = lambda a, p: {'status': 'success', 'message': 'done'}
        res = main.mind_step_approve(iid, 's1', body={}, request=None,
                                     background_tasks=bg)
        check(res.get('status') == 'success', f"the step ran, got {res}")
        check(main.trigger_background_refresh in bg.tasks,
              f"a reassignment re-solves, got {bg.tasks}")
        check(res.get('insight_state') == 'retired',
              "and the last step closing retires the insight")
    finally:
        _auth.identify, _ca._execute = orig_identify, orig_execute


def scenario_the_row_level_approval_asks_for_one_too():
    _reset(); _reset_people()
    import main
    from services import auth as _auth, chat_actions as _ca
    iid, pid = _insight_with_proposal()
    orig_identify, orig_execute = _auth.identify, _ca._execute
    bg = _FakeBackground()
    try:
        _auth.identify = lambda h, q: {'tier': _auth.SERVICE, 'member': None}
        _ca._execute = lambda a, p: {'status': 'success', 'message': 'done'}
        main.mind_act(iid, body={}, request=None, background_tasks=bg)
        check(main.trigger_background_refresh in bg.tasks,
              f"same defect, same visit, got {bg.tasks}")
    finally:
        _auth.identify, _ca._execute = orig_identify, orig_execute


if __name__ == '__main__':
    scenario_dismiss_records_outcome()
    scenario_act_records_outcome()
    scenario_lane_is_filtered()
    scenario_the_admin_page_can_approve_without_a_member_identity()
    scenario_a_named_parent_is_not_overwritten_by_the_nomination()
    scenario_an_enrolled_panel_still_cannot_approve()
    scenario_no_parent_on_record_is_an_honest_refusal()
    scenario_snooze_clamps_and_parks()
    scenario_step_approve_rides_the_chat_rail()
    scenario_a_skipped_step_cannot_be_approved()
    scenario_a_schedule_changing_step_approval_asks_for_a_resolve()
    scenario_the_row_level_approval_asks_for_one_too()
    print("test_mind_endpoints OK")
