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
    iid = storage.add_mind_insight({'slug': 'z', 'line': 'x', 'category': 'c'})
    # endpoint math: days clamped 1..60, default 7
    for asked, expect in ((0, 1), (7, 7), (999, 60)):
        days = max(1, min(60, int(asked or 7) if asked else 1))
        storage.update_mind_insight(iid, {'snoozed_until': _t.time() + days * 86400})
    row = storage.get_mind_insight_by_slug('z')
    check(row['snoozed_until'] > _t.time() + 59 * 86400, "clamped to 60d max")
    import datetime as _dt
    check(_m.visible_insights({'id': 'mom', 'role': 'parent'}) == [] or
          all(r['slug'] != 'z' for r in _m.visible_insights(
              {'id': 'mom', 'role': 'parent'})),
          "snoozed row leaves the lane")


def scenario_step_approve_rides_the_chat_rail():
    from services import mind as _m
    storage.mind_insights_table.truncate()
    iid = storage.add_mind_insight({'slug': 'w', 'line': 'x', 'category': 'c'})
    storage.update_mind_insight(iid, {'state': 'in_hand', 'plan_json': {
        'created_ts': 1.0,
        'steps': [{'id': 's1', 'kind': 'tool', 'text': 't',
                   'owner_member_id': None, 'owner_name': '',
                   'due': '2026-09-02', 'status': 'open',
                   'proposal_json': {'proposal_id': 'pr7', 'summary': 'S'}}]}})
    # the endpoint approves pr7 via chat_actions.act_on_proposal, then:
    res = _m.close_step(iid, 's1', 'done')
    check(res['status'] == 'success' and res['insight_state'] == 'retired',
          f"single-step plan retires on approve, got {res}")
    check(storage.get_mind_insight_by_slug('w')['outcome'] == 'acted',
          "approve lands as acted")


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
    print("test_mind_endpoints OK")
