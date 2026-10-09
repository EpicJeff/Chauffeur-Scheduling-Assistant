"""coverage_asks → asks: idempotent, nudges intact, legacy ids resolve, a
legacy row never attaches to a newer occurrence's finding, and the old
endpoints still answer through the adapters."""
import asyncio
import datetime
import time

from harness import check  # noqa: F401
from services import storage, asks, migrations, coverage_options as cov, situations

NOON = datetime.datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)


def _reset():
    for t in (storage.asks_table, storage.coverage_asks_table, storage.findings_table, storage.members_table,
              storage.cache_table, storage.app_state_table, storage.assist_contacts_table,
              storage.assist_assignments_table, storage.assist_history_table):
        t.truncate()
    storage.get_settings = lambda: {'calendar_ids': ['primary']}
    storage.add_member({'id': 'mom', 'name': 'Mom', 'role': 'parent'})
    storage.add_assist_contact({'id': 'c1', 'name': 'Sarah', 'kinds': ['driving'], 'active': True})
    situations.REFRESH_DELAY_S = 0
    situations._pool_call = lambda *a, **k: {}


def _legacy(event_id, start, state='waiting', **kw):
    row = {'id': kw.pop('id', f"old-{event_id}-{state}"), 'event_id': event_id, 'event_title': 'Soccer',
           'event_date': start.date().isoformat(), 'event_start': start.isoformat(),
           'contact_id': 'c1', 'contact_name': 'Sarah', 'asked_by': 'mom', 'state': state,
           'asked_at': time.time() - 3600, 'nudges_sent': 1, 'rearmed_at': None, **kw}
    storage.coverage_asks_table.insert(row)
    return row


def scenario_migration_is_idempotent_and_keeps_nudges():
    _reset()
    start = (NOON + datetime.timedelta(days=2)).replace(hour=16)
    storage.set_cached_schedule({'events': [{'id': 'ev1', 'title': 'Soccer', 'start': start.isoformat(),
                                             'end': start.isoformat()}], 'assignments': {}, 'unassigned': ['ev1']})
    fid = storage.add_finding({'identity': 'unassigned:ev1', 'kind': 'unassigned', 'severity': 'decide',
                               'line': 'x', 'subject_type': 'event', 'subject_id': 'ev1',
                               'due_at': start.timestamp(), 'state': 'open', 'fingerprint': f"ev1|{start.timestamp()}"})
    _legacy('ev1', start)
    _legacy('ev1', start, state='covered', id='old-cov', resolved_at=time.time())
    asyncio.run(migrations.migrate_coverage_asks_v2499308())
    asyncio.run(migrations.migrate_coverage_asks_v2499308())
    rows = storage.get_asks(event_id='ev1')
    check(len(rows) == 2, f"two rows, once: {len(rows)}")
    by_legacy = {r['legacy_id']: r for r in rows}
    w = by_legacy['old-ev1-waiting']
    check(w['state'] == 'sent' and w['nudges_sent'] == 1 and w['channel'] == 'text', f"waiting→sent with nudges: {w}")
    check(w['situation_id'] == fid and w['situation_kind'] == 'finding', "attached to the matching finding")
    check((w['unlocks'] or {}).get('action_type') == 'assist_assignment', "legacy ask can still apply")
    c = by_legacy['old-cov']
    check(c['state'] == 'yes' and c['outcome'] == 'applied', f"covered→yes/applied: {c}")


def scenario_legacy_ask_does_not_attach_to_a_newer_occurrence():
    _reset()
    old_start = (NOON - datetime.timedelta(days=7)).replace(hour=16)
    new_start = (NOON + datetime.timedelta(days=2)).replace(hour=16)
    storage.set_cached_schedule({'events': [{'id': 'ev1', 'title': 'Soccer', 'start': new_start.isoformat(),
                                             'end': new_start.isoformat()}], 'assignments': {}, 'unassigned': ['ev1']})
    storage.add_finding({'identity': 'unassigned:ev1', 'kind': 'unassigned', 'severity': 'decide', 'line': 'x',
                         'subject_type': 'event', 'subject_id': 'ev1', 'due_at': new_start.timestamp(),
                         'state': 'open', 'fingerprint': f"ev1|{new_start.timestamp()}"})
    _legacy('ev1', old_start)
    asyncio.run(migrations.migrate_coverage_asks_v2499308())
    row = storage.get_asks(event_id='ev1')[0]
    check(row['situation_id'] is None, f"an older occurrence's ask has no situation: {row['situation_id']}")
    res = cov.answer_ask('old-ev1-waiting', 'no', member_id='mom')
    check(res['status'] == 'success' and storage.get_ask(row['id'])['state'] == 'no',
          "the legacy id still answers through the adapter")


def scenario_adapters_keep_the_old_shape():
    _reset()
    start = (NOON + datetime.timedelta(days=2)).replace(hour=16)
    storage.set_cached_schedule({'events': [{'id': 'ev1', 'title': 'Soccer', 'start': start.isoformat(),
                                             'end': start.isoformat()}], 'assignments': {}, 'unassigned': ['ev1']})
    res = cov.start_ask('ev1', 'c1', asked_by='mom')
    check(res['status'] == 'success' and res['ask_id'] and 'Soccer' in res['text'], f"start_ask shape: {res}")
    legacy = storage.get_coverage_ask(res['ask_id'])
    check(legacy and legacy['state'] == 'waiting' and legacy['contact_name'] == 'Sarah', f"legacy read shape: {legacy}")
    check([a['id'] for a in storage.get_coverage_asks(state='waiting')] == [res['ask_id']], "listing maps state")
    ans = cov.answer_ask(res['ask_id'], 'covered', member_id='mom')
    check(ans['status'] == 'success' and ans.get('schedule_dirty'), f"covered applies: {ans}")
    check(storage.get_coverage_ask(res['ask_id'])['state'] == 'covered', "reads back as covered")
    cov.answer_ask(res['ask_id'], 'undo', member_id='mom')
    check(storage.get_coverage_ask(res['ask_id'])['state'] == 'waiting', "undo rearms")
    check(not storage.get_assist_assignment_map().get('ev1'), "undo cleared the assignment")
    try:
        storage.add_coverage_ask({'event_id': 'ev1'})
        check(False, "add_coverage_ask must refuse")
    except RuntimeError:
        pass


SCENARIOS = [scenario_migration_is_idempotent_and_keeps_nudges,
             scenario_legacy_ask_does_not_attach_to_a_newer_occurrence,
             scenario_adapters_keep_the_old_shape]

def scenario_covered_without_a_contact_keeps_the_name():
    _reset()
    start = (NOON + datetime.timedelta(days=2)).replace(hour=16)
    storage.set_cached_schedule({'events': [{'id': 'ev1', 'title': 'Soccer', 'start': start.isoformat(),
                                             'end': start.isoformat()}], 'assignments': {}, 'unassigned': ['ev1']})
    res = cov.start_ask('ev1', contact_name='Beth Ray', asked_by='mom')
    ans = cov.answer_ask(res['ask_id'], 'covered', member_id='mom')
    check(ans['status'] == 'success' and 'Beth Ray' in ans['message'], f"covered by the named person: {ans}")
    names = [c.get('name') for c in storage.get_assist_contacts()]
    check('Beth Ray' in names and 'A friend' not in names, f"the contact is Beth, not 'A friend': {names}")
    check(storage.get_ask(res['ask_id'])['to_name'] == 'Beth Ray', "the ask keeps its name")


SCENARIOS += [scenario_covered_without_a_contact_keeps_the_name]

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
