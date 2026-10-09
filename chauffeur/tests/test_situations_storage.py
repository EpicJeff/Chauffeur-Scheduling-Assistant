"""Storage for the situations slice: the asks ledger, insight-by-id, and a
finding in_hand that the sweep updates but never re-adds."""
import datetime
import time
from unittest import mock

from harness import check  # noqa: F401
from services import storage, findings, watchers

NOON = datetime.datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)


def _reset():
    for t in (storage.asks_table, storage.findings_table, storage.chores_table,
              storage.members_table, storage.cache_table, storage.app_state_table,
              storage.chat_channels_table, storage.chat_messages_table):
        t.truncate()
    storage.get_settings = lambda: {"calendar_ids": ["primary"]}
    storage.add_member({"id": "mom", "name": "Mom", "role": "parent"})


def scenario_ask_roundtrip():
    _reset()
    aid = storage.add_ask({'situation_kind': 'finding', 'situation_id': 'f1',
                           'to_name': 'Sarah', 'what': 'drive Kate Thursday',
                           'channel': 'text', 'asked_by': 'mom', 'legacy_id': 'old1'})
    row = storage.get_ask(aid)
    check(row and row['state'] == 'drafted' and row['nudges_sent'] == 0,
          f"a new ask starts drafted with no nudges, got {row}")
    check(storage.get_ask_by_legacy_id('old1')['id'] == aid, "found by legacy id")
    check(storage.update_ask(aid, {'state': 'sent', 'sent_at': time.time()}), "update by id")
    check([a['id'] for a in storage.get_asks(situation_kind='finding', situation_id='f1')] == [aid],
          "listed by situation")
    check(storage.get_asks(state='drafted') == [], "state filter sees the update")
    check(storage.get_asks(to_member_id='nobody') == [], "member filter")


def scenario_insight_by_id():
    _reset()
    storage.mind_insights_table.truncate()
    iid = storage.add_mind_insight({'slug': 's', 'line': 'x', 'category': 'c'})
    check(storage.get_mind_insight(iid)['id'] == iid, "insight by id")
    check(storage.get_mind_insight('nope') is None, "unknown id is None")


def scenario_in_hand_finding_is_updated_never_readded():
    _reset()
    now_ts = NOON.timestamp()
    storage.set_cached_schedule({"events": [], "assignments": {}, "unassigned": []})
    storage.add_chore({"id": "c1", "title": "Mow lawn", "state": "done",
                       "done_at": now_ts - 3 * 86400, "created_at": now_ts - 9 * 86400,
                       "points": 20, "recurrence": "once", "eligible_member_ids": []})
    with mock.patch.object(watchers, '_prep_kit_findings', return_value=[]), \
         mock.patch('services.agent_tools_v2._post_chat_message',
                    side_effect=lambda ch, sender, body, card=None: {}):
        watchers.run_watchers(now=NOON)
        fid = storage.get_findings(state='open')[0]['id']
        storage.update_finding(fid, {'state': 'in_hand', 'owner_member_id': 'mom'})
        watchers.run_watchers(now=NOON + datetime.timedelta(days=1))
    rows = storage.get_findings(kind='chore_verify')
    check(len(rows) == 1 and rows[0]['state'] == 'in_hand', f"one row, still in hand: {rows}")
    check('day(s)' in rows[0]['line'], "the sentence keeps updating while in hand")
    check(findings.open_findings() == [], "open_findings hides in-hand rows by default")
    check(len(findings.open_findings(include_in_hand=True)) == 1, "…and shows them when asked")
    # Reality still closes it.
    storage.chores_table.update({'state': 'verified'}, storage.Query().id == 'c1')
    with mock.patch.object(watchers, '_prep_kit_findings', return_value=[]), \
         mock.patch('services.agent_tools_v2._post_chat_message',
                    side_effect=lambda ch, sender, body, card=None: {}):
        watchers.run_watchers(now=NOON + datetime.timedelta(days=1, hours=1))
    check(storage.get_finding(fid)['state'] == 'done', "absence closes an in-hand finding")


SCENARIOS = [scenario_ask_roundtrip, scenario_insight_by_id,
             scenario_in_hand_finding_is_updated_never_readded]

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
