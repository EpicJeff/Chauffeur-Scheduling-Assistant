"""The situation and ask endpoints: viewer filtering, the three answer gates
through HTTP, server-bound options, and the ask card's buttons."""
import datetime

from harness import check  # noqa: F401
from services import storage, situations, asks, auth as _auth

NOON = datetime.datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)


class _Req:
    def __init__(self, member_id=None):
        self.headers = {}
        self.query_params = {'member_id': member_id} if member_id else {}


def _reset():
    for t in (storage.asks_table, storage.findings_table, storage.mind_insights_table, storage.members_table,
              storage.cache_table, storage.app_state_table, storage.assist_contacts_table,
              storage.chat_channels_table, storage.chat_messages_table, storage.threads_table,
              storage.missions_table, storage.mission_steps_table):
        t.truncate()
    storage.get_settings = lambda: {'calendar_ids': ['primary']}
    storage.add_member({'id': 'mom', 'name': 'Mom', 'role': 'parent'})
    storage.add_member({'id': 'nan', 'name': 'Nan', 'role': 'helper'})
    storage.add_member({'id': 'kid', 'name': 'Kate', 'role': 'child', 'is_child': True})
    situations.REFRESH_DELAY_S = 0
    situations._pool_call = lambda *a, **k: {}
    start = (NOON + datetime.timedelta(days=2)).replace(hour=16)
    storage.set_cached_schedule({'events': [{'id': 'ev1', 'title': 'Soccer', 'start': start.isoformat(),
                                             'end': start.isoformat()}], 'assignments': {}, 'unassigned': ['ev1']})
    fid = storage.add_finding({'identity': 'unassigned:ev1', 'kind': 'unassigned', 'severity': 'decide',
                               'line': 'No driver yet', 'subject_type': 'event', 'subject_id': 'ev1',
                               'due_at': start.timestamp(), 'state': 'open', 'fingerprint': f"ev1|{start.timestamp()}"})
    iid = storage.add_mind_insight({'slug': 's', 'line': 'quiet week', 'category': 'c', 'approach': 'x', 'identity': 'c:1'})
    return fid, iid


def _as(member_id):
    """Resolve the PWA's claimed member the way _acting_id does, without HTTP."""
    _auth.acting_member = lambda h, q, claimed=None: {'id': member_id} if member_id else {}
    _auth.impersonation_refused = lambda acting: False
    _auth.identify = lambda h, q: {'tier': _auth.MEMBER if member_id else _auth.SERVICE, 'member': None}


def scenario_list_is_viewer_filtered():
    fid, iid = _reset()
    import main
    _as('mom')
    rows = main.situations_list(kinds='finding,insight', request=_Req('mom'))['situations']
    check({r['id'] for r in rows} == {fid, iid}, f"a parent sees both: {[r['id'] for r in rows]}")
    _as('kid')
    rows = main.situations_list(kinds='finding,insight', request=_Req('kid'))['situations']
    check([r['id'] for r in rows] == [iid], "a child sees the insight only")


def scenario_act_is_server_bound_and_gated():
    fid, iid = _reset()
    import main
    from fastapi import HTTPException
    _as('kid')
    try:
        main.situations_act('finding', fid, body={'verb': 'dismiss', 'option_id': 'dismiss', 'member_id': 'kid'},
                            request=_Req('kid'), background_tasks=None)
        check(False, "a child must be refused")
    except HTTPException as e:
        check(e.status_code == 403, f"403 for a child, got {e.status_code}")
    _as('mom')
    res = main.situations_act('finding', fid, body={'verb': 'dismiss', 'option_id': 'dismiss', 'member_id': 'mom'},
                              request=_Req('mom'), background_tasks=None)
    check(res['status'] == 'success' and storage.get_finding(fid)['state'] == 'dismissed', "a parent dismisses")


def scenario_ask_flow_over_http():
    fid, iid = _reset()
    import main
    from fastapi import HTTPException
    _as('mom')
    s = main.situation_get('finding', fid, request=_Req('mom'))
    opt = next(o for o in s['options'] if o['verb'] == 'ask' and o['id'] == 'ask:new')
    res = main.asks_create(body={'kind': 'finding', 'id': fid, 'option_id': opt['id'],
                                 'to': {'name': 'Nan', 'member_id': 'nan'}, 'channel': 'chauffeur', 'member_id': 'mom'},
                           request=_Req('mom'))
    a = res['ask']
    check(a['state'] == 'sent' and a['to_member_id'] == 'nan' and (a['unlocks'] or {}).get('action_type') == 'assist_assignment',
          f"an ask from an option carries the server's unlocks: {a}")
    check({c['channel'] for c in res['channels']} >= {'email', 'text', 'in_person'}, "channels come back with it")
    # The bystander child cannot answer; the recipient helper can.
    _as('kid')
    try:
        main.asks_answer(a['id'], body={'answer': 'yes', 'member_id': 'kid'}, request=_Req('kid'), background_tasks=None)
        check(False, "a bystander must be refused")
    except HTTPException as e:
        check(e.status_code == 403, "403 for a bystander")
    _as('nan')
    res = main.asks_answer(a['id'], body={'answer': 'yes', 'member_id': 'nan'}, request=_Req('nan'), background_tasks=None)
    check(res['status'] == 'success' and res['outcome'] == 'applied', f"the helper's own yes applies: {res}")
    msg = storage.get_chat_message(a['message_id'])
    check(msg['card']['state'] == 'yes' and msg['card']['actions'] == [], "the DM card followed the ledger")


def scenario_answer_gate_refuses_a_bystander():
    fid, iid = _reset()
    import main
    from fastapi import HTTPException
    _as('mom')
    res = main.asks_create(body={'kind': 'finding', 'id': fid, 'to': {'name': 'Nan', 'member_id': 'nan'},
                                 'what': 'drive Kate', 'channel': 'chauffeur', 'member_id': 'mom'}, request=_Req('mom'))
    a = res['ask']
    _as('kid')
    try:
        main.asks_answer(a['id'], body={'answer': 'no', 'member_id': 'kid'}, request=_Req('kid'), background_tasks=None)
        check(False, "refused")
    except HTTPException as e:
        check(e.status_code == 403 and storage.get_ask(a['id'])['state'] == 'sent', "refused, ledger untouched")


SCENARIOS = [scenario_list_is_viewer_filtered, scenario_act_is_server_bound_and_gated,
             scenario_ask_flow_over_http, scenario_answer_gate_refuses_a_bystander]

if __name__ == "__main__":
    import traceback
    failed = 0
    for fn in SCENARIOS:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL  {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(SCENARIOS) - failed}/{len(SCENARIOS)} scenarios passed")
    raise SystemExit(1 if failed else 0)
