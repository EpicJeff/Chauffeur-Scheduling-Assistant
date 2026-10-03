"""Ride groups, in a real browser against the served Schedule page.

The user's case: Ava swims 9:00-10:00 and Ben dives 10:05-11:05 at the same
pool. One driver can chain them, but the route sends that driver HOME for Ben
between the two and shows him late. The fix is a hand decision about these
occurrences: drop one event onto the other.

Pinned:
  * the late leg offers "Ride together" in the event panel;
  * dropping one event's card on another asks Group Events / Assign to
    <driver> / Cancel -- an accidental drop is still a reassignment;
  * Group Events writes the group, the re-solve routes one trip (no fetch
    leg, nobody late), and both cards wear the 🔗 chip;
  * the chip ungroups;
  * Assign on that dialog is the ordinary override.

Run from chauffeur/:  python tests/test_ride_groups_live.py
"""
import datetime as _dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import check
from services import storage

TODAY = _dt.date.today()
HOME = '1 Home St'
POOL = '3 Pool Rd'
TOKENS = {}
SHOTS = os.environ.get('CHAUFFEUR_SHOTS')


def _travel(o, d, departure_time=None, return_traffic=False):
    same = not o or not d or o.lower() == d.lower()
    mins = 0 if same else 15
    return (mins, 0) if return_traffic else mins


def _refresh():
    import main
    main.refresh_schedule_logic(TODAY.isoformat(), TODAY.isoformat(), force_refresh=True)


def _serve():
    from live_app import live_app
    from services import calendar as cal_svc
    from services import maps
    from models.schemas import Event
    import solver.matcher as matcher
    import main

    at = lambda h, m=0: _dt.datetime.combine(TODAY, _dt.time(h, m))
    evs = [dict(id='swim', title='Swim', start=at(9), end=at(10), location=POOL,
                description='', calendar_ids=['cal_ava'], source_event_ids=['swim']),
           dict(id='dive', title='Dive', start=at(10, 5), end=at(11, 5), location=POOL,
                description='', calendar_ids=['cal_ben'], source_event_ids=['dive'])]

    def seed():
        for t in ('drivers_table', 'passengers_table', 'members_table',
                  'daily_schedules_table', 'custom_schedules_table',
                  'settings_table', 'event_configs_table', 'rules_table',
                  'overrides_table', 'ride_groups_table'):
            tbl = getattr(storage, t, None)
            if tbl is not None:
                tbl.truncate()
        storage.settings_table.insert({'calendar_ids': ['cal_house'],
                                       'days_to_build': 1, 'home_location': HOME})
        for i, (did, name) in enumerate((('d1', 'Jeff'), ('d2', 'Vovo'))):
            storage.add_driver({'id': did, 'name': name, 'color_code': '#4ade80',
                                'group': 'primary', 'priority_index': i + 1,
                                'calendar_ids': [], 'home_location': HOME})
        storage.add_passenger({'id': 'pa', 'name': 'Ava', 'calendar_ids': ['cal_ava'], 'hashtags': []})
        storage.add_passenger({'id': 'pb', 'name': 'Ben', 'calendar_ids': ['cal_ben'], 'hashtags': []})
        storage.add_member({'id': 'mj', 'name': 'Jeff', 'role': 'parent', 'driver_id': 'd1'})
        TOKENS['parent'] = storage.create_member_token('mj')
        storage.event_configs_table.insert({'google_id': 'swim', 'passenger_ids': ['pa']})
        storage.event_configs_table.insert({'google_id': 'dive', 'passenger_ids': ['pb']})
        storage.add_override({'event_id': 'swim', 'driver_id': 'd1'})
        storage.add_override({'event_id': 'dive', 'driver_id': 'd1'})
        cal_svc.fetch_upcoming_events = lambda *a, **k: [Event(**e) for e in evs]
        matcher._raw_get_travel_time_minutes = _travel
        maps.get_travel_time_minutes = _travel
        # The page's own refresh runs the real logic synchronously, so the
        # test can reload and read the result.
        main.trigger_background_refresh = lambda *a, **k: _refresh()
        _refresh()

    return live_app(seed)


def _open(page, served):
    page.goto(served.url('api/account/setup'))
    page.evaluate('(t) => { localStorage.clear();'
                  ' localStorage.setItem("chauffeur_admin_token", t);'
                  ' localStorage.setItem("chauffeur_admin_token_for", "mj"); }',
                  TOKENS['parent'])
    page.goto(served.url('dashboard_v2'), wait_until='networkidle')
    page.wait_for_function('() => typeof currentData !== "undefined" && currentData'
                           ' && document.getElementById("event-dive")', timeout=20000)


def _shot(page, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        page.screenshot(path=os.path.join(SHOTS, name + '.png'))


def _drop(page, dragged, target, source, column='d1'):
    """What the browser's drop delivers: `dragged` (from `source`'s column)
    lands on `target`'s card in `column`. Returns without awaiting: the
    dialog is still open."""
    page.evaluate('''([dragged, target, source, column]) => {
        const card = document.getElementById('event-' + target);
        window.__dropDone = drop({
            preventDefault() {},
            target: card.firstElementChild || card,
            dataTransfer: { getData: k => k === 'text' ? dragged : source },
        }, column);
    }''', [dragged, target, source, column])
    page.wait_for_selector('#cc-confirm-modal:not(.hidden)', timeout=5000)


def _edge(page):
    return page.evaluate('() => (currentData.route_edges.d1 || {}).swim || null')


def scenario_drop_one_event_on_another_to_ride_together():
    served = _serve()
    if served is None:
        return
    try:
        with served.browser() as page:
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.set_viewport_size({'width': 1280, 'height': 900})
            _open(page, served)

            edge = _edge(page)
            check(edge and edge.get('pickup_waypoint') and edge.get('late_mins', 0) > 0
                  and edge.get('ride_together', {}).get('event_id') == 'swim',
                  "ungrouped, the route goes home for Ben and is late, and says so: %r" % edge)

            page.evaluate('() => openEventModal("dive", "")')
            page.wait_for_selector('#ride-suggestion-section:not(.hidden)', timeout=5000)
            body = page.inner_text('#ride-suggestion-body')
            check('Ride together with Swim' in body and 'late' in body,
                  "the event panel offers riding together: %r" % body)
            _shot(page, 'ride_suggestion')
            page.evaluate('() => closeEventModal()')

            # Drop Dive onto Swim (same column): Group / Cancel, no Assign.
            _drop(page, 'dive', 'swim', 'd1')
            labels = page.eval_on_selector_all('#cc-confirm-actions button', 'bs => bs.map(b => b.innerText.trim())')
            check(labels == ['Cancel', 'Group Events'],
                  "same column: nothing to assign to, so Group or Cancel: %r" % labels)
            page.click('#cc-confirm-actions button:has-text("Cancel")')
            page.evaluate('() => window.__dropDone')
            check(storage.get_ride_group_rows() == [], "Cancel writes nothing")

            # Dragged from Vovo's column onto Swim in Jeff's: all three choices.
            _drop(page, 'dive', 'swim', 'd2')
            labels = page.eval_on_selector_all('#cc-confirm-actions button', 'bs => bs.map(b => b.innerText.trim())')
            check(labels == ['Cancel', 'Assign to Jeff', 'Group Events'],
                  "a drop on another event offers Group / Assign to <driver>: %r" % labels)
            _shot(page, 'drop_dialog')
            page.evaluate('() => { window.__alerts = []; window.showGlobalAlert = m => window.__alerts.push(m); }')
            page.click('#cc-confirm-actions button:has-text("Group Events")')
            page.evaluate('() => window.__dropDone')
            alerts = page.evaluate('() => window.__alerts')
            check(alerts == [], "grouping raised no alert: %r" % alerts)
            rows = storage.get_ride_group_rows()
            check(len(rows) == 2 and len({r['group_id'] for r in rows}) == 1,
                  "Group Events wrote one group of two: %r" % rows)

            _open(page, served)
            edge = _edge(page)
            check(edge and not edge.get('pickup_waypoint') and not edge.get('late_mins')
                  and not edge.get('ride_together'),
                  "grouped, one trip: no fetch leg, nobody late: %r" % edge)
            chips = page.evaluate('''() => ['swim', 'dive'].map(id => {
                const b = document.querySelector('#event-' + id + ' button[onclick^="openRideGroupChip"]');
                return b ? b.title : null; })''')
            check(chips[0] and 'Dive' in chips[0] and chips[1] and 'Swim' in chips[1],
                  "both cards wear the chip naming the other: %r" % chips)
            _shot(page, 'grouped_cards')

            # The chip ungroups.
            page.click('#event-dive button[onclick^="openRideGroupChip"]')
            page.wait_for_selector('#cc-confirm-modal:not(.hidden)', timeout=5000)
            page.click('#cc-confirm-execute-btn')
            page.wait_for_function('() => true')
            for _ in range(50):
                if not storage.get_ride_group_rows():
                    break
                page.wait_for_timeout(100)
            check(storage.get_ride_group_rows() == [],
                  "Ungroup from the chip dissolves the pair: %r" % storage.get_ride_group_rows())

            # An accidental drop is still a reassignment.
            _open(page, served)
            page.evaluate('() => { window.promptConfirm = async () => true; }')
            storage.overrides_table.truncate()
            _drop(page, 'dive', 'swim', 'd2')
            page.click('#cc-confirm-actions button:has-text("Assign to Jeff")')
            page.evaluate('() => window.__dropDone')
            saved = [o for o in storage.get_all_overrides()
                     if o.get('event_id') == 'dive' and o.get('driver_id') == 'd1']
            check(saved and storage.get_ride_group_rows() == [],
                  "Assign is the ordinary override, and groups nothing")
            check(not errors, "the page threw: %s" % errors)
    finally:
        served.stop()


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print("  ok  %s" % fn.__name__)
    print("\n%d/%d ride-group live scenarios passed" % (len(SCENARIOS), len(SCENARIOS)))
