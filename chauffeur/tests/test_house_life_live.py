"""Household objects and the bounded Study visit, through the served browser."""
import os
from urllib.parse import urlparse, parse_qs
from test_house_live import live_app, _seed, check
from services import storage
from models.schemas import Chore, RoutineItem, PrepKit


def scenario_house_life():
    served = live_app()
    shots = os.environ.get('HOUSE_LIFE_SHOTS')
    if shots:
        os.makedirs(shots, exist_ok=True)
    _seed()
    storage.add_member({'id': 'house-parent', 'name': 'Jordan', 'role': 'parent'})
    storage.set_member_pin('house-parent', '1234')
    personal = storage.create_member_token('house-parent')
    storage.add_chore(Chore(title='Feed the pets', owner='k1', state='claimed', claimed_by='k1').model_dump())
    storage.add_routine(RoutineItem(member_id='k1', title='Brush teeth', time_of_day='07:00').model_dump())
    storage.add_household_task({'id': 'house-task', 'title': 'Replace the air filter', 'due_date': '2020-01-01', 'status': 'open'})
    storage.add_prep_kit(PrepKit(id='house-kit', name='Soccer bag', items=['Water bottle'], keywords=['soccer'], per_person=False).model_dump())
    # the study's lean-in cards: a thread pins the connections board, a
    # waiting proposal lands in the intake tray
    storage.add_thread({'title': 'Call the plumber back', 'kind': 'vendor'})
    storage.add_proposal({'title': 'Dentist reminder for Maya'})
    import time as _time
    storage.set_trip_metadata('trip-1', {'id': 'trip-1', 'title': 'Lake weekend', 'location': 'Bear Lake',
                                         'mock_start_date': _time.time() + 9 * 86400, 'audience': 'household'})
    with served.browser() as page:
        def packs(route):
            response = route.fetch()
            data = response.json()
            data['mudroom'] = {'bags': 2, 'packing_known': True, 'calm': False, 'packs': [
                {'name': 'Practice', 'packed': 1, 'needed': 3, 'ready': False, 'attention': True},
                {'name': 'School', 'packed': 2, 'needed': 2, 'ready': True, 'attention': False}]}
            route.fulfill(response=response, json=data)
        page.route('**/api/house/state*', packs)
        page.goto(served.url('house?quality=low&panel=true'))
        page.wait_for_function('window.chfHouseState && chfHouseState() && window.Alpine')
        check(page.locator('.house-life-dock').count() == 0,
              'household features live on objects, not a shortcut drawer')
        page.wait_for_selector('.house-hint[data-attention*="packing"] .house-attention-badge')
        check(int(page.locator('.house-hint[data-attention*="packing"] .house-attention-badge').inner_text()) >= 2,
              'exterior mudroom marker aggregates unfinished packing and room work')
        if shots:
            page.screenshot(path=os.path.join(shots, 'exterior-attention.png'))
        for key, content in [('chores', 'Feed the pets'), ('routines', 'Brush teeth'),
                             ('programs', 'practice'), ('tasks', 'Replace the air filter'),
                             ('errands', 'Manage with parent PIN'), ('packing', 'Soccer practice')]:
            page.evaluate('(key) => chfHouseFindFeature(key)', key)
            page.wait_for_function('chfNavProbe({settled:true})')
            page.wait_for_selector('.house-hint[data-house-action="' + key + '"]')
            if shots:
                page.screenshot(path=os.path.join(shots, key + '-object.png'))
            point = page.evaluate('(key) => chfNavProbe({action:key})', key)
            if not point:
                raw = page.evaluate("""(key) => {
                  const original = document.elementFromPoint;
                  document.elementFromPoint = () => document.querySelector('#room canvas');
                  try { return chfNavProbe({action:key}); }
                  finally { document.elementFromPoint = original; }
                }""", key)
                covering = page.evaluate('(p) => p && document.elementFromPoint(p.cx,p.cy)?.className', raw)
                check(point, key + ' has a visible feature object; projected=' +
                      str(raw) + ' covering=' + str(covering))
            page.mouse.click(point['cx'], point['cy'])
            page.wait_for_function('(text) => document.querySelector(".house-life-body").innerText.includes(text)', arg=content)
            if shots:
                page.screenshot(path=os.path.join(shots, key + '.png'))
            if key == 'routines':
                widths = page.locator('.house-life-lanes > .grid > div').evaluate_all(
                    '(lanes) => lanes.map((lane) => lane.getBoundingClientRect().width)')
                check(widths and min(widths) >= 360,
                      'family lanes retain a readable minimum width: ' + str(widths))
            if key == 'packing':
                page.locator('.house-life-body .fd-pack-btn').first.click()
                page.locator('#pack-dialog-root [data-pack-item]').first.click()
                page.wait_for_selector('#pack-dialog-root .fd-chip-done')
                page.locator('#pack-dialog-root [data-pack-close]').click()
            page.locator('.house-life-panel header button').click()
            page.wait_for_selector('.house-life-shade', state='hidden')
            check(page.evaluate('chfHouseMode()') != 'exterior', 'feature opens in its room context')
        # CUTAWAY OWNERSHIP (v2.499.41): these two used to be asserted
        # ABSENT here. They were absent for one reason -- the kitchen
        # camera stood EAST of the main block at x 14.6 and reached the
        # room by ghosting the east partition, taking the slider and the
        # back-room door in that wall with it. The kitchen is viewed
        # from the STREET now (HOME_POS 4.64, 13.8, 23.0), so the wall
        # stands and its two openings stand on it: from the kitchen you
        # look AT the slider, not through it. Asserted as the mask rather
        # than as a screen probe -- the back-room door sits at the very
        # edge of this frame, which is a framing fact, not a cutaway one.
        # STUDY REFIT (2026-09-16): the slider is east_room_door now --
        # a plain interior door in the same opening, same registration.
        # VIEW-VOLUME MASKING (task 3): the pin reads maskedFraction --
        # the kitchen's mask (its box ends at x 6.5; the partition is at
        # 6.44..6.85, beside the pyramid, behind the box's south face)
        # takes nothing off any of the three.
        for piece in ('east_room_door', 'living_back_room_door', 'east_partition'):
            check(page.evaluate(
                "(n) => chfShellFabric().find(f => f.name === n).maskedFraction.kitchen", piece) == 0,
                piece + " must stand from the kitchen: the east partition is "
                "the study's enclosure, not the kitchen's")
        # IN-ROOM MARKERS ARE BUTTONS (v2.499.162). User report: "Home
        # ledger" in the living room did nothing -- the marker was a drawing
        # over a tiny book, so only its exact centre reached the object, a
        # tap 25px up walked into the kitchen, and the label was dead. Tap
        # the ring OFF-centre and the label: both must open the feature.
        page.evaluate("chfHouseEnterRoom('living')")
        page.wait_for_function("chfHouseMode() === 'living' && chfNavProbe({settled:true})")
        page.wait_for_selector('.house-hint[data-house-action="tasks"]', state='visible')
        for where in ('ring', 'label'):
            m = page.evaluate("""(w) => { const e = document.querySelector('.house-hint[data-house-action="tasks"]');
                const r = (w === 'label' ? e.querySelector('.house-hint-label') : e).getBoundingClientRect();
                return {x: r.left + r.width / 2 + (w === 'ring' ? 25 : 0), y: r.top + r.height / 2 - (w === 'ring' ? 20 : 0)}; }""", where)
            page.mouse.click(m['x'], m['y'])
            page.wait_for_function("document.body.classList.contains('house-card-open')", timeout=8000)
            check(page.evaluate("chfHouseMode()") == 'living', 'a marker tap never walks to another room')
            check('Household tasks' in page.inner_text('.house-life-panel'),
                  'the Home ledger marker opens tasks from its ' + where)
            page.locator('.house-life-panel header button').click()
            page.wait_for_selector('.house-life-shade', state='hidden')
            page.wait_for_selector('.house-hint[data-house-action="tasks"]', state='visible')
        # and the program book's marker no longer covers the ledger's label
        boxes = page.evaluate("""() => ['tasks','programs'].map(k => {
            const e = document.querySelector('.house-hint[data-house-action="'+k+'"]');
            const r = e.getBoundingClientRect(), l = e.querySelector('.house-hint-label').getBoundingClientRect();
            return {top: r.top, bottom: l.bottom}; })""")
        check(boxes[0]['bottom'] <= boxes[1]['top'] or boxes[1]['bottom'] <= boxes[0]['top'],
              'neighbouring markers do not overlap: ' + str(boxes))
        page.evaluate("chfHouseFindFeature('study')")
        page.wait_for_function('chfNavProbe({settled:true})')
        point = page.evaluate("chfNavProbe({action:'study'})")
        if not point:
            raw = page.evaluate("""() => {
              const original = document.elementFromPoint;
              document.elementFromPoint = () => document.querySelector('#room canvas');
              try { return chfNavProbe({action:'study'}); }
              finally { document.elementFromPoint = original; }
            }""")
            covering = page.evaluate('(p) => p && document.elementFromPoint(p.cx,p.cy)?.className', raw)
            check(point, 'Study door is not reachable; projected=' +
                  str(raw) + ' covering=' + str(covering))
        check(point['cx'] > page.viewport_size['width'] * .55,
              'Study door appears on the room side opposite the exterior door')
        check(point['cx'] < page.viewport_size['width'] * .92,
              'Living-room framing keeps the Study door comfortably visible')
        for fixture in ('back-room-door',):
            fixture_point = page.evaluate('(key) => chfNavProbe({feature:key})', fixture)
            check(fixture_point, fixture + ' is visible on the living-room east wall')
        check(page.evaluate("chfShellFabric().find(f => f.name === 'east_room_door').maskedFraction.living === 0"),
              "the east room's door is visible from the living room")
        # STUDY REFIT: the glazing this used to pin moved to the study's
        # own doors, and the rule moved with it -- both sides of that
        # glass are indoors, so it never takes the exterior night glow.
        check(page.evaluate("chfShellFabric().find(f => f.name === 'living_study_door').interiorGlow === 0"),
              "the study's glass doors do not emit the exterior night glow")
        if shots:
            page.screenshot(path=os.path.join(shots, 'living-east-wall.png'))
        page.mouse.click(point['cx'], point['cy'])
        page.wait_for_selector('#cc-input-field', state='visible')
        page.fill('#cc-input-field', '1234')
        page.click('#cc-input-ok-btn')
        page.wait_for_function("chfHouseMode() === 'study' && chfNavProbe({settled:true})")
        check(urlparse(page.url).path.endswith('/house'),
              'Study opens inside the house without loading a separate world')
        visit = page.evaluate('chfHouseParent().token')
        check(storage.get_member_by_token(visit)['id'] == 'house-parent', 'temporary visit carries parent identity')
        study_zones = ('study_board', 'study_desk', 'study_tray',
                       'study_stickies', 'study_calendar', 'study_window',
                       'study_contracts', 'study_binders',
                       'study_gauges', 'study_monitor', 'study_map')
        for zone in study_zones:
            check(page.evaluate('(key) => chfNavProbe({zone:key})', zone),
                  zone + ' uses the house interaction registry')
        page.wait_for_selector('.house-hint[data-target="study_monitor"]', state='visible')
        check('Living room' in page.locator('#house-back').inner_text(),
              'Study uses the house back affordance')
        if shots:
            page.screenshot(path=os.path.join(shots, 'integrated-study.png'))
        # LEAN-IN CARDS (v2.499.158): a list-shaped zone wears an HTML card
        # built off the token-fetched furniture (never api/home_board); an
        # instrument zone shows the room's own painted detail instead; and
        # the zone tip clears the panel shelf rather than hiding under it.
        target = page.evaluate("chfNavProbe({zone:'study_tray'})")
        page.mouse.click(target['cx'], target['cy'])
        page.wait_for_function("(() => { const p=chfNavProbe({settled:true}); return p && p.focused === 'study_tray'; })()")
        page.wait_for_selector('#overlay-study >> text=Dentist reminder for Maya', timeout=8000)
        check(page.is_visible('#focus-overlay'), 'the intake tray wears its card')
        check(page.evaluate("document.getElementById('overlay-open').getAttribute('href')").endswith('intake'),
              'the card opens the intake page')
        tray_state = page.evaluate("chfStudyDetail('study_tray')")
        check(tray_state['visible'] == 0, 'the painted detail stays down under the card')
        # FACE-ON: the kitchen's convention -- the eye approaches along the
        # card face's normal. An up-facing sheet is read steeply (~63
        # degrees), a wall face dead on.
        check(tray_state['facing'] > 0.85, 'the in-tray is read square-on: ' + str(tray_state))
        check(page.evaluate("chfStudyCard('study_board').rows[0].text") == 'Call the plumber back',
              'the board card carries the thread by its own title')
        clear = page.evaluate("""() => {
          const t = document.getElementById('tip').getBoundingClientRect();
          const s = document.getElementById('panel-shelf');
          return {tipBottom: t.bottom, shelfTop: s ? s.getBoundingClientRect().top : innerHeight,
                  text: document.getElementById('tip').textContent};
        }""")
        check(clear['tipBottom'] <= clear['shelfTop'] + 0.5,
              'the zone tip clears the panel shelf: ' + str(clear))
        if shots:
            page.screenshot(path=os.path.join(shots, 'study-tray-card.png'))
        page.keyboard.press('Escape')
        page.wait_for_function("(() => { const p=chfNavProbe({settled:true}); return p && !p.focused && p.mode === 'study'; })()")
        page.wait_for_selector('#focus-overlay', state='hidden', timeout=8000)
        check(page.evaluate("document.getElementById('overlay-study').textContent") == '',
              'leaning out empties the card')
        # the map hangs CLEAR of the room's chair rail (its bottom rail used
        # to sit 0.15 inside it): the zone's world box against the rail the
        # adapter builds at y 1.62, .11 thick, plus the .08 clearance
        mp = page.evaluate("chfStudyZone('study_map')")
        check(mp and mp[2] >= 1.62 + .055 + .08 - 1e-3,
              'the wall map clears the chair rail: min y ' + str(mp and mp[2]))
        # the map is a CARD (its painted labels were the janky part) and an
        # empty card zone says so instead of showing nothing
        target = page.evaluate("chfNavProbe({zone:'study_map'})")
        page.mouse.click(target['cx'], target['cy'])
        page.wait_for_function("(() => { const p=chfNavProbe({settled:true}); return p && p.focused === 'study_map'; })()")
        page.wait_for_selector('#overlay-study >> text=Lake weekend', timeout=8000)
        check('Bear Lake' in page.inner_text('#overlay-study'), 'the trip card carries the location')
        check(page.evaluate("chfStudyDetail('study_map')")['visible'] == 0, 'the map paint stays down under its card')
        if shots:
            page.screenshot(path=os.path.join(shots, 'study-map-card.png'))
        page.keyboard.press('Escape')
        page.wait_for_function("(() => { const p=chfNavProbe({settled:true}); return p && !p.focused && p.mode === 'study'; })()")
        target = page.evaluate("chfNavProbe({zone:'study_contracts'})")
        page.mouse.click(target['cx'], target['cy'])
        page.wait_for_function("(() => { const p=chfNavProbe({settled:true}); return p && p.focused === 'study_contracts'; })()")
        page.wait_for_selector('#overlay-study >> text=No open deals', timeout=8000)
        check(page.is_visible('#focus-overlay'), 'an empty card zone wears an honest empty card')
        if shots:
            page.screenshot(path=os.path.join(shots, 'study-empty-card.png'))
        page.keyboard.press('Escape')
        page.wait_for_function("(() => { const p=chfNavProbe({settled:true}); return p && !p.focused && p.mode === 'study'; })()")
        # the baseline card hangs on the window GLASS (a face tall enough for
        # six signs), read square-on, not on the little sill card
        target = page.evaluate("chfNavProbe({zone:'study_window'})")
        page.mouse.click(target['cx'], target['cy'])
        page.wait_for_function("(() => { const p=chfNavProbe({settled:true}); return p && p.focused === 'study_window'; })()")
        page.wait_for_selector('#overlay-study >> text=Family baseline', timeout=8000)
        win = page.evaluate("""() => {
          const o = document.getElementById('focus-overlay').getBoundingClientRect();
          const d = chfStudyDetail('study_window');
          return {h: o.height, w: o.width, facing: d.facing};
        }""")
        check(win['facing'] > 0.9 and win['h'] > 60, 'the baseline card stands square on the glass: ' + str(win))
        if shots:
            page.screenshot(path=os.path.join(shots, 'study-window-card.png'))
        page.keyboard.press('Escape')
        page.wait_for_function("(() => { const p=chfNavProbe({settled:true}); return p && !p.focused && p.mode === 'study'; })()")
        # the monitor's graph is DRAWN in the house (it never was: stepGraph
        # lived in the standalone frame loop) and animates while leaned into
        draws0 = page.evaluate("chfStudyDetail('study_monitor')")['graphDraws']
        check(draws0 > 0, 'the monitor graph drew at least once in the room: ' + str(draws0))
        target = page.evaluate("chfNavProbe({zone:'study_monitor'})")
        page.mouse.click(target['cx'], target['cy'])
        page.wait_for_function("(() => { const p=chfNavProbe({settled:true}); return p && p.focused === 'study_monitor'; })()")
        ds = page.evaluate("chfStudyDetail('study_monitor')")
        check(ds and ds['panels'] > 0 and ds['painted'] == ds['panels'] and ds['visible'] == ds['panels'],
              'the monitor shows its own painted labels when leaned into: ' + str(ds))
        check(ds['facing'] > 0.95, 'the monitor is read dead on: ' + str(ds))
        page.wait_for_function("(n) => chfStudyDetail('study_monitor').graphDraws > n + 3", arg=draws0, timeout=8000)
        check(not page.is_visible('#focus-overlay'), 'an instrument zone wears no card')
        if shots:
            page.screenshot(path=os.path.join(shots, 'study-monitor-detail.png'))
        target = page.evaluate("chfNavProbe({zone:'study_monitor'})")
        page.mouse.click(target['cx'], target['cy'])
        page.wait_for_url(lambda url: urlparse(url).path.endswith('/mind'))
        page.wait_for_selector('#house-return')
        page.locator('#house-return').click()
        page.wait_for_url(lambda url: urlparse(url).path.endswith('/house') and 'panel=true' in url)
        check(parse_qs(urlparse(page.url).query).get('quality') == ['low'], 'return preserves house preferences')
        page.wait_for_function("sessionStorage.getItem('chauffeur_house_parent') === null")
        page.wait_for_timeout(300)
        check(storage.get_member_by_token(visit) is None, 'return revokes parent visit')
        check(storage.get_member_by_token(personal) is not None, 'personal sign-in survives')
        page.go_back()
        page.wait_for_url(lambda url: urlparse(url).path.endswith('/house'))
        check(not page.evaluate('chfHouseParent()'), 'browser back cannot revive parent visit')
        check(not served.errors(), 'no browser errors: ' + str(served.errors()))


def scenario_study_monitor_labels_meet_their_clusters_in_a_mirrored_house():
    """Each monitor label sits on its own nebula, mirrored plan included.

    The label panel is a text panel, so on a mirrored house counterFlip()
    turns it back to read forward -- while the graph screen behind it is
    reflected with the room. Anchors computed in the panel's own canvas
    then landed at the mirror image of their clusters (user report, with
    a screenshot: Lily's label on the far side of the glass from Lily's
    cluster). The pin is world space: the point each label was anchored
    at and the point its cluster is drawn at must be the same point.
    """
    import copy
    from services import house_facade as hf
    served = live_app()
    _seed()
    # scenario_house_life seeds the same parent into the same data dir
    if not storage.get_member('house-parent'):
        storage.add_member({'id': 'house-parent', 'name': 'Jordan', 'role': 'parent'})
    storage.set_member_pin('house-parent', '1234')
    spec = copy.deepcopy(hf.CANONICAL)
    spec['mirror'] = True
    spec, _notes = hf.normalize(spec)
    names = ['Jeff', 'Lily', 'James', 'Grandpa', 'Celma', 'Addison']
    with served.browser() as page:
        def study(route):
            response = route.fetch()
            data = response.json()
            data.setdefault('furniture', {})['monitor'] = {'clusters': [
                {'name': n, 'count': (i * 2) % 7} for i, n in enumerate(names)]}
            route.fulfill(response=response, json=data)
        page.route('**/api/study/state*', study)
        page.goto(served.url('house?quality=low&draft=' + hf.issue_draft(spec)))
        page.wait_for_function('window.chfHouseState && chfHouseState() && window.Alpine')
        check(page.evaluate('chfMirror().mirror'), 'the house is mirrored')
        page.evaluate("chfHouseEnterRoom('living')")
        page.wait_for_function('chfNavProbe({settled:true})')
        page.evaluate("window.dispatchEvent(new CustomEvent('chf-house-open', {detail: 'study'}))")
        page.wait_for_selector('#cc-input-field', state='visible')
        page.fill('#cc-input-field', '1234')
        page.click('#cc-input-ok-btn')
        page.wait_for_function("chfHouseMode() === 'study' && chfNavProbe({settled:true})")
        page.evaluate("chfKitchenFocus('study_monitor')")
        page.wait_for_function("(chfStudyLabelAnchors('study_monitor') || []).length === %d"
                               % len(names), timeout=20000)
        rows = page.evaluate("chfStudyLabelAnchors('study_monitor')")
        for name, r in zip(names, rows):
            off = sum((a - b) ** 2 for a, b in zip(r['cluster'], r['label'])) ** 0.5
            check(off < 0.01, '%s: label anchored %.3f units from its cluster '
                  '(cluster %r, label %r)' % (name, off, r['cluster'], r['label']))
        # leave the study the way a family does, which ends the parent
        # visit -- a live one outlasts this page and leaves the next
        # scenario's study door with no PIN prompt to show
        page.evaluate('chfHouseExit()')
        page.wait_for_function("sessionStorage.getItem('chauffeur_house_parent') === null")
        check(not served.errors(), 'no browser errors: ' + str(served.errors()))


if __name__ == '__main__':
    scenario_house_life()
    scenario_study_monitor_labels_meet_their_clusters_in_a_mirrored_house()
    print('House life browser passed')
