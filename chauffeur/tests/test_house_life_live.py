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
        target = page.evaluate("chfNavProbe({zone:'study_monitor'})")
        page.mouse.click(target['cx'], target['cy'])
        page.wait_for_function("(() => { const p=chfNavProbe({settled:true}); return p && p.focused === 'study_monitor'; })()")
        ds = page.evaluate("chfStudyDetail('study_monitor')")
        check(ds and ds['panels'] > 0 and ds['painted'] == ds['panels'] and ds['visible'] == ds['panels'],
              'the monitor shows its own painted labels when leaned into: ' + str(ds))
        check(ds['facing'] > 0.95, 'the monitor is read dead on: ' + str(ds))
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


if __name__ == '__main__':
    scenario_house_life()
    print('House life browser passed')
