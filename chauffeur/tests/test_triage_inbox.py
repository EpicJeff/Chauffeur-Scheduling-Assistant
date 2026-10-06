"""The Inbox: every event waiting for setup, answered together, saved once.

The Schedule page's inbox used to be a strip of cards above the timeline,
built from whatever days the page had loaded. Each card opened the event
modal, and each save re-solved the schedule, so setting up ten new events
meant ten saves and ten waits. The inbox is now a dialog fed by
/api/events/triage and saved through /api/events/config/batch.

The properties, in the order they matter:

  1. **The whole horizon, not the loaded days.** The list reads the
     full-horizon schedule cache, so an event three weeks out is listed
     even when the page shows today.
  2. **Only real setup work.** Configured events (including those whose
     config was written after the last solve), events that have already
     ended, and events that never needed triage are left out.
  3. **One save, one re-solve.** The batch writes every staged config and
     requests ONE refresh, however many events it carries.
  4. **Failures are named, never swallowed.** One event's Google Calendar
     write failing leaves the others saved and comes back keyed to that
     event, so the dialog can keep it open.

Run from chauffeur/:  python tests/test_triage_inbox.py
"""
import datetime

from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR)

from services import storage

NOW = datetime.datetime.now().replace(microsecond=0)


def _ev(eid, start, needs_triage=True, recurring=None, minutes=60):
    return {
        'id': eid, 'title': eid.title(), 'start': start.isoformat(),
        'end': (start + datetime.timedelta(minutes=minutes)).isoformat(),
        'calendar_ids': ['cal_kid'], 'source_event_ids': [f'cal_kid::{eid}'],
        'recurring_event_id': recurring, 'needs_triage': needs_triage,
    }


def _seed(events):
    storage.event_configs_table.truncate()
    storage.set_cached_schedule({
        'events': events, 'passengers': [{'id': 'p1', 'name': 'Lily'}],
        'drivers': [], 'calendar_metadata': {}, 'driver_events': {},
    })


def scenario_lists_the_whole_horizon_in_time_order():
    import main
    far = NOW + datetime.timedelta(days=21)
    soon = NOW + datetime.timedelta(hours=3)
    _seed([_ev('far', far), _ev('soon', soon)])
    got = main.list_triage_events(request=None)
    ids = [e['id'] for e in got['events']]
    check(ids == ['soon', 'far'],
          "three weeks out is still setup work, listed in time order: %r" % ids)
    check(got['built'] is True, "a built cache says so")
    check(got['passengers'] and got['passengers'][0]['id'] == 'p1',
          "the form's passengers ride along")


def scenario_leaves_out_what_is_not_setup_work():
    import main
    later = NOW + datetime.timedelta(days=1)
    _seed([
        _ev('done', NOW - datetime.timedelta(hours=3)),         # already ended
        _ev('fine', later, needs_triage=False),                  # never needed it
        _ev('savedsince', later),                                # config after solve
        _ev('seriesinst', later, recurring='series1'),           # series config after solve
        _ev('open', later),
    ])
    storage.set_event_config('savedsince', {'passenger_ids': ['p1']})
    storage.set_event_config('series1', {'passenger_ids': ['p1']})
    ids = [e['id'] for e in main.list_triage_events(request=None)['events']]
    check(ids == ['open'], "only the open event is setup work: %r" % ids)


def scenario_an_unbuilt_schedule_says_so():
    import main
    storage.set_cached_schedule({})
    got = main.list_triage_events(request=None)
    check(got['events'] == [] and got['built'] is False,
          "an empty cache is 'not built yet', not 'nothing to do': %r" % got)


def scenario_one_save_is_one_resolve():
    import main
    calls = []
    real = main.trigger_background_refresh
    main.trigger_background_refresh = lambda *a, **k: calls.append(a)
    try:
        storage.event_configs_table.truncate()
        res = main.save_event_configs_batch({'items': [
            {'key': f'e{i}', 'google_id': f'g{i}', 'config': {'passenger_ids': ['p1']}}
            for i in range(5)]})
    finally:
        main.trigger_background_refresh = real
    check(res['saved'] == 5 and res['failed'] == 0, "all five saved: %r" % res)
    check(len(calls) == 1, "five events, one re-solve: %r" % calls)
    check(all(storage.get_event_config(f'g{i}') for i in range(5)),
          "every config is stored")
    check(calls[0][2] is False, "no hand-over moved, so no forced refresh: %r" % (calls[0],))


def scenario_a_failed_calendar_write_is_named_and_the_rest_land():
    import main
    from services import calendar as cal_svc
    real_refresh = main.trigger_background_refresh
    real_update = cal_svc.update_event_details
    calls, writes = [], []
    main.trigger_background_refresh = lambda *a, **k: calls.append(a)

    def fake_update(src, details, strict=False):
        writes.append((tuple(src), details, strict))
        if src[0].endswith('bad'):
            raise RuntimeError('quota exceeded')
    cal_svc.update_event_details = fake_update
    try:
        storage.event_configs_table.truncate()
        res = main.save_event_configs_batch({'items': [
            {'key': 'ok', 'google_id': 'gok', 'config': {'driver_ids': []},
             'details': {'source_event_ids': ['cal::gok'], 'start': 'S', 'end': 'E'}},
            {'key': 'bad', 'google_id': 'gbad', 'config': {'driver_ids': []},
             'details': {'source_event_ids': ['cal::gbad'], 'start': 'S', 'end': 'E'}},
        ]})
    finally:
        main.trigger_background_refresh = real_refresh
        cal_svc.update_event_details = real_update
    by = {r['key']: r for r in res['results']}
    check(by['ok']['ok'] and not by['bad']['ok'], "the failure is keyed to its event: %r" % res)
    check('Google Calendar' in by['bad']['error'] and 'quota exceeded' in by['bad']['error'],
          "the error says what did not land and why: %r" % by['bad'])
    check(all(w[2] for w in writes), "the batch writes the calendar in strict mode")
    check(storage.get_event_config('gok') and storage.get_event_config('gbad'),
          "the setup itself is kept even where the time write failed")
    check(len(calls) == 1, "still one re-solve: %r" % calls)


def scenario_a_staged_hand_over_forces_the_refresh():
    import main
    real_refresh = main.trigger_background_refresh
    real_assist = main._apply_assist_coverage
    calls, covered = [], []
    main.trigger_background_refresh = lambda *a, **k: calls.append(a)
    main._apply_assist_coverage = lambda eid, cid, scope, **k: covered.append((eid, cid, scope))
    try:
        res = main.save_event_configs_batch({'items': [
            {'key': 'e1', 'google_id': 'g1', 'config': {'driver_ids': []},
             'assist': {'event_id': 'e1', 'contact_id': 'c1', 'scope': 'series'}}]})
    finally:
        main.trigger_background_refresh = real_refresh
        main._apply_assist_coverage = real_assist
    check(res['saved'] == 1, "saved: %r" % res)
    check(covered == [('e1', 'c1', 'series')], "the hand-over lands as staged: %r" % covered)
    check(len(calls) == 1 and calls[0][2] is True,
          "a hand-over changes no event, so the one refresh is forced: %r" % calls)


def scenario_the_batch_route_is_not_swallowed_by_the_config_route():
    import main
    paths = [getattr(r, 'path', '') for r in main.app.routes
             if 'POST' in (getattr(r, 'methods', None) or set())]
    check('/api/events/config/batch' in paths, "the batch route exists")
    check(paths.index('/api/events/config/batch') < paths.index('/api/events/config/{google_id}'),
          "registered first, or POST .../batch would save a config for an event called 'batch'")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print("  ok  %s" % fn.__name__)
    print("\n%d/%d triage-inbox scenarios passed" % (len(SCENARIOS), len(SCENARIOS)))
