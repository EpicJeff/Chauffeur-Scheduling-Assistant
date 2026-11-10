"""Rooms link to Home Assistant areas in the editor, in real Chromium (piece 3
Task 4 of docs/superpowers/plans/2026-11-10-house-ha-link-piece-3.md; brief
.superpowers/sdd/2026-11-10-house-ha-link-piece-3/task-4-brief.md; spec
docs/superpowers/specs/2026-11-09-house-connected-model-design.md section 7).

The house is the household's migrated house (tests/house_editor_model_harness.py
seeds it through twin_store.push_round). Before the push this file names three
rooms so the suggestions have something to match:
- main-house room:14e8bce1...  -> 'Garage' (it holds the garage opening df687e2c...)
- main-house room:691a32b2...  -> 'Den'    (no area matches it)
- pool-house room:5d7de10c...  -> 'Kitchen', its legacy ha_area 'Pool Lounge' cleared
Every scenario starts by putting the seeded model back (twin_store.update_model).

Home Assistant is faked in-process (tests/house_ha_fake.py) before the app
serves: areas Kitchen and Garage on the floor 'Ground floor', Office on
'Upstairs', Patio on no floor; devices: the garage door (a cover with
device_class garage) and a light in Garage, a light in Kitchen, a lamp in
Office, a light on the Patio.

What the editor must give (the brief):
- The room card holds a <select> labelled `Home Assistant area`: `No area`, then
  every area by name (value = area id) in an <optgroup> per floor. Picking one
  posts the model op {op: 'set', building, id: <room>, field: 'ha_area', value}
  to api/house/editor/op (applyOpNow); `No area` posts value ''.
- An unlinked room with a suggestion shows `Suggested: {area name}` and a `Use`
  button that posts the same op. Linking the Garage this way also places its
  garage door on the garage opening in the same round (Task 2: src {'auto': True}).
- A room whose area Home Assistant no longer has shows
  `This room's Home Assistant area is gone; pick another.`
- The building card lists `Areas with no room`, one button per unlinked area;
  tapping one opens promptChoice (#cc-choice-modal) over the building's rooms and
  posts set ha_area on the chosen room; Cancel posts nothing.
- With no Home Assistant the room card shows
  `Home Assistant is not connected, so areas and devices are hidden.` in place of
  the select, the building card has no unlinked list, and the editor still edits.

Hooks: window.__twinEditor.haLink is the createHaLink(...) object; its state()
is the last GET api/house/ha/link answer (null until the first one arrives).
Pieces are selected with the existing test hook window.__editor.clickPiece.

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_house_editor_model_live_t18.py
"""
import copy
import logging
import os
import sys
import tempfile
import time

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='chauffeur_house_editor_t18_'))
os.environ.pop('HA_BASE_URL', None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import house_editor_model_harness as H  # noqa: E402
import house_ha_fake  # noqa: E402

check = H.check
MAIN, POOL = 'main-house', 'pool-house'
GARAGE = 'room:14e8bce101b54e1aba698138e2a56ddb'
DEN = 'room:691a32b2fa634bfcbde221ca85594cdc'
KITCHEN = 'room:5d7de10ca48340ae85c407d22337c6f7'
CHANGING = 'room:aa3a66806205434ca794927a6d66dd22'
GARAGE_OPENING = 'opening:df687e2c4b2d421bbd8951525f4b82d8'

NO_HA = 'Home Assistant is not connected, so areas and devices are hidden.'
GONE = "This room's Home Assistant area is gone; pick another."

FAKE = house_ha_fake.FakeHA(
    areas=[{'area_id': 'kitchen', 'name': 'Kitchen', 'floor_id': 'ground'},
           {'area_id': 'garage', 'name': 'Garage', 'floor_id': 'ground'},
           {'area_id': 'office', 'name': 'Office', 'floor_id': 'upstairs'},
           {'area_id': 'patio', 'name': 'Patio', 'floor_id': None}],
    floors=[{'floor_id': 'ground', 'name': 'Ground floor', 'level': 0},
            {'floor_id': 'upstairs', 'name': 'Upstairs', 'level': 1}],
    devices=[{'id': 'dev-garage-door', 'name': 'Garage door', 'area_id': 'garage',
              'entities': [('cover.garage_door', 'closed', {'device_class': 'garage'})]},
             {'id': 'dev-garage-light', 'name': 'Garage light', 'area_id': 'garage',
              'entities': [('light.garage_light', 'off', {'supported_features': 8})]},
             {'id': 'dev-kitchen-light', 'name': 'Kitchen light', 'area_id': 'kitchen',
              'entities': [('light.kitchen_light', 'off', {'supported_features': 8})]},
             {'id': 'dev-office-lamp', 'name': 'Office lamp', 'area_id': 'office',
              'entities': [('light.office_lamp', 'off', {})]},
             {'id': 'dev-patio-light', 'name': 'Patio light', 'area_id': 'patio',
              'entities': [('light.patio_light', 'off', {})]}],
).install()
SEED = {}


def _names(plan):
    for bid, rid, name in ((MAIN, GARAGE, 'Garage'), (MAIN, DEN, 'Den'), (POOL, KITCHEN, 'Kitchen')):
        room = next(r for r in H.building(plan, bid)['rooms'] if r['id'] == rid)
        room['name'] = name
        room['ha_area'] = ''
    return plan


def _serve():
    served = H.serve(_names)
    if served is not None and 'model' not in SEED:
        SEED['model'] = copy.deepcopy(H.model())
    return served


def _reset(change=None):
    """Put the seeded house back as the current round (plus `change`), Home Assistant connected."""
    from services import twin_store
    FAKE.available = True

    def mutate(_before):
        model = copy.deepcopy(SEED['model'])
        if change:
            change(model)
        return model
    twin_store.update_model(mutate, 'edit', note='t18 reset')


# --- the stored house -----------------------------------------------------------

def _room(model, bid, rid):
    return next((r for r in H.building(model, bid)['rooms'] if r['id'] == rid), None)


def _placements(model, device_id):
    """Every place the device sits: ('anchor', building, anchor) or ('host', building, entry)."""
    out = []
    for b in model['buildings']:
        for a in b.get('anchors') or []:
            if a.get('device') == device_id:
                out.append(('anchor', b['id'], a))
        for d in b.get('devices') or []:
            if d.get('device') == device_id:
                out.append(('host', b['id'], d))
    return out


def _store():
    from services import twin_store
    return {'round': twin_store.current_id(), 'rounds': len(twin_store.rounds())}


def _facts():
    model = H.model()
    check(model is not None and model.get('schema') == 'chauffeur.twin.plan/3', 'the store holds a schema 3 model')
    for bid, rid, name in ((MAIN, GARAGE, 'Garage'), (MAIN, DEN, 'Den'), (POOL, KITCHEN, 'Kitchen')):
        room = _room(model, bid, rid)
        check(room is not None and room.get('name') == name and not room.get('ha_area'), ('the named room', bid, rid, room))
    opening = next((o for o in H.building(model, MAIN)['openings'] if o['id'] == GARAGE_OPENING), None)
    check(opening is not None and opening['kind'] == 'garage' and opening['wall'] in H.room_walls(model, MAIN, GARAGE),
          ('the Garage holds the garage opening', opening))
    return model


# --- page helpers ----------------------------------------------------------------

def _record_ops(page):
    """Every op the editor posts to /api/house/editor/op, in order."""
    posted = []

    def on_request(request):
        if request.method == 'POST' and request.url.split('?')[0].endswith('/api/house/editor/op'):
            try:
                body = request.post_data_json
            except Exception:
                body = None
            posted.append((body or {}).get('op') if isinstance(body, dict) else body)
    page.on('request', on_request)
    return posted


def _open(page, served):
    H.open_editor(page, served)
    try:
        page.wait_for_function('() => !!(window.__twinEditor && window.__twinEditor.haLink)', timeout=5000)
    except Exception:
        raise AssertionError('window.__twinEditor.haLink is missing: the editor exposes createHaLink(...) there under ?test=1')
    page.wait_for_function("""() => {
        const link = window.__twinEditor.haLink, state = link.state && link.state();
        return !!state && typeof state.available === 'boolean';
    }""", timeout=20000)


def _link_state(page):
    return page.evaluate('() => window.__twinEditor.haLink.state()')


def _select(page, pid, bid, title):
    """Select a piece through the editor's test hook. A focused room steps out
    first when the piece lies outside it (selection.js), so try up to three times."""
    for _ in range(3):
        page.evaluate('([p, b]) => window.__editor.clickPiece(p, b)', [pid, bid])
        H.settle(page)
        deadline = time.time() + 2
        while time.time() < deadline and H.card_title(page) != title:
            page.wait_for_timeout(100)
        if H.card_title(page) == title and H.editor_state(page, 'selection').get('id') == pid:
            return
    check(False, ('the card opens for', pid, H.card_title(page), H.editor_state(page, 'selection')))


def _card_text(page):
    return ' '.join(page.inner_text('#piece-card').split())


def _area_select(page):
    found = page.locator('#piece-card').get_by_label('Home Assistant area', exact=True)
    check(found.count() == 1, ('one control labelled Home Assistant area on the card', found.count(), _card_text(page)))
    check(found.evaluate('n => n.tagName') == 'SELECT', 'the Home Assistant area control is a <select>')
    return found


def _options(select):
    return select.evaluate("""s => [...s.options].map(o => ({ value: o.value, text: o.textContent.trim(), selected: o.selected,
        group: o.parentElement && o.parentElement.tagName === 'OPTGROUP' ? o.parentElement.label : null }))""")


def _committed(page, posted, before, count=1, timeout=20.0):
    """Wait for one new round; the editor posted `count` ops; return them."""
    from services import twin_store
    deadline = time.time() + timeout
    while time.time() < deadline and twin_store.current_id() == before['round']:
        page.wait_for_timeout(100)
    check(twin_store.current_id() != before['round'], ('nothing was stored (no new round)', posted, _alert(page)))
    page.wait_for_timeout(500)
    check(len(posted) == count, ('the editor posted', count, 'op(s)', posted))
    check(len(twin_store.rounds()) == before['rounds'] + 1, 'one action adds exactly one round')
    return list(posted)


def _alert(page):
    if not page.locator('#cc-alert-modal').is_visible():
        return None
    return page.inner_text('#cc-alert-message').strip()


def _is_set(op, bid, rid, value):
    return (isinstance(op, dict) and op.get('op') == 'set' and op.get('building') == bid and op.get('id') == rid
            and op.get('field') == 'ha_area' and op.get('value') == value)


def _wait(page, cond, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cond():
            return True
        page.wait_for_timeout(100)
    return cond()


def _no_errors(served):
    errors = H.unexpected(served.errors())
    check(not errors, errors)


class _LogWatch(logging.Handler):
    """Every ERROR the app's own code logs while the block runs (a traceback counts).
    uvicorn's own 'Exception in ASGI application' records are left out: a long poll
    the browser drops (api/v2/chat/stream) logs one with no bearing on the house, and
    a route that fails here already fails the scenario through its answer."""

    def __init__(self):
        super().__init__(level=logging.ERROR)
        self.records = []

    def emit(self, record):
        if not record.name.startswith('uvicorn'):
            self.records.append(record)

    def __enter__(self):
        logging.getLogger().addHandler(self)
        return self

    def __exit__(self, *exc):
        logging.getLogger().removeHandler(self)


# --- scenarios -------------------------------------------------------------------

def scenario_room_card_picks_an_area():
    s = _serve()
    if s is None:
        return

    def gone(model):
        _room(model, POOL, CHANGING)['ha_area'] = 'old_area'
    _reset(gone)
    _facts()
    with s.browser(launch_args=H.GPU_ARGS) as page:
        posted = _record_ops(page)
        _open(page, s)
        _select(page, DEN, MAIN, 'Den')
        select = _area_select(page)
        options = _options(select)
        check(options[0]['text'] == 'No area' and options[0]['value'] == '', ('the first option is No area', options))
        by_value = {o['value']: o for o in options}
        for value, text, group in (('kitchen', 'Kitchen', 'Ground floor'), ('garage', 'Garage', 'Ground floor'),
                                   ('office', 'Office', 'Upstairs')):
            check(by_value.get(value, {}).get('text') == text and by_value[value]['group'] == group,
                  ('every area by name, in its floor\'s group', value, options))
        check(by_value.get('patio', {}).get('text') == 'Patio'
              and by_value['patio']['group'] not in ('Ground floor', 'Upstairs'), ('an area with no floor', options))
        check(len(options) == 5, ('No area plus the four areas', options))
        check(select.input_value() == '', ('an unlinked room shows No area', select.input_value()))
        check('Suggested:' not in _card_text(page), ('no area matches the Den by name', _card_text(page)))

        # Pick Office: one set op, the room links, Office leaves the unlinked list.
        before = _store()
        select.select_option('office')
        ops = _committed(page, posted, before)
        check(_is_set(ops[0], MAIN, DEN, 'office'), ('the pick posts set ha_area', ops))
        check(_room(H.model(), MAIN, DEN)['ha_area'] == 'office', _room(H.model(), MAIN, DEN))
        check(_wait(page, lambda: 'office' not in {u['area_id'] for u in (_link_state(page) or {}).get('unlinked', [])}),
              ('the link is read again after the pick', _link_state(page)))
        check(_wait(page, lambda: _area_select(page).input_value() == 'office'),
              ('the card shows the linked area', _area_select(page).input_value()))

        # No area unlinks it.
        del posted[:]
        before = _store()
        _area_select(page).select_option('')
        ops = _committed(page, posted, before)
        check(_is_set(ops[0], MAIN, DEN, ''), ('No area posts the empty value', ops))
        check(_room(H.model(), MAIN, DEN)['ha_area'] == '', _room(H.model(), MAIN, DEN))

        # A room whose area Home Assistant no longer has.
        _select(page, CHANGING, POOL, 'CHANGING')
        check(GONE in _card_text(page), ('the gone-area line', _card_text(page)))
        _area_select(page)
        _no_errors(s)


def scenario_suggestion_use_links_and_places_the_garage_doors():
    s = _serve()
    if s is None:
        return
    _reset()
    _facts()
    with s.browser(launch_args=H.GPU_ARGS) as page:
        posted = _record_ops(page)
        _open(page, s)
        rows = {r['room']: r for r in (_link_state(page) or {}).get('rooms', [])}
        check(GARAGE in rows, ('the link lists the Garage', sorted(rows)))
        _select(page, GARAGE, MAIN, 'Garage')
        check('Suggested: Garage' in _card_text(page), ('the suggestion line', _card_text(page)))
        use = page.locator('#piece-card').get_by_role('button', name='Use', exact=True)
        check(use.count() == 1, ('one Use button', use.count()))
        check(_area_select(page).input_value() == '', 'the suggestion is shown, not applied')
        check(_room(H.model(), MAIN, GARAGE)['ha_area'] == '', 'nothing is stored before Use')

        before = _store()
        use.click()
        ops = _committed(page, posted, before)
        check(_is_set(ops[0], MAIN, GARAGE, 'garage'), ('Use posts set ha_area with the suggested area', ops))
        model = H.model()
        check(_room(model, MAIN, GARAGE)['ha_area'] == 'garage', _room(model, MAIN, GARAGE))
        door = _placements(model, 'dev-garage-door')
        check(len(door) == 1 and door[0][0] == 'host' and door[0][1] == MAIN, ('the garage door placed itself, once', door))
        entry = door[0][2]
        check(entry.get('host') == {'opening': GARAGE_OPENING, 'side': 'in'}, ('on the garage opening, inside', entry))
        check(entry.get('src') == {'auto': True}, ('placed by the link, not by a person', entry))
        check(_placements(model, 'dev-garage-light') == [], ('the light waits for a person', _placements(model, 'dev-garage-light')))

        check(_wait(page, lambda: 'Suggested:' not in _card_text(page)), ('a linked room has no suggestion', _card_text(page)))
        check(_wait(page, lambda: _area_select(page).input_value() == 'garage'), _area_select(page).input_value())
        _no_errors(s)


def scenario_unlinked_area_is_placed_on_a_room():
    s = _serve()
    if s is None:
        return
    _reset()
    _facts()
    with s.browser(launch_args=H.GPU_ARGS) as page:
        posted = _record_ops(page)
        _open(page, s)
        _select(page, MAIN, MAIN, 'Main House')
        check('Areas with no room' in _card_text(page), ('the building card lists unlinked areas', _card_text(page)))
        card = page.locator('#piece-card')
        for name in ('Kitchen', 'Garage', 'Office', 'Patio'):
            check(card.locator('button').filter(has_text=name).count() >= 1, ('an unlinked area is a button', name, _card_text(page)))

        # Cancel asks, posts nothing.
        before = _store()
        card.locator('button').filter(has_text='Patio').first.click()
        page.wait_for_selector('#cc-choice-modal', state='visible', timeout=5000)
        page.click('#cc-choice-cancel-btn')
        page.wait_for_timeout(1200)
        check(posted == [] and _store() == before, ('a cancelled choice stores nothing', posted))

        # Office onto the Den.
        card.locator('button').filter(has_text='Office').first.click()
        page.wait_for_selector('#cc-choice-modal', state='visible', timeout=5000)
        labels = [t.strip() for t in page.locator('#cc-choice-options button').all_inner_texts()]
        check(any('Den' in t for t in labels) and any('Garage' in t for t in labels),
              ('the building\'s rooms are offered', labels))
        den = page.locator('#cc-choice-options button').filter(has_text='Den')
        check(den.count() == 1, ('one choice names the Den', labels))
        den.click()
        ops = _committed(page, posted, before)
        check(_is_set(ops[0], MAIN, DEN, 'office'), ('the chosen room takes the area', ops))
        check(_room(H.model(), MAIN, DEN)['ha_area'] == 'office', _room(H.model(), MAIN, DEN))
        check(_wait(page, lambda: page.locator('#piece-card button').filter(has_text='Office').count() == 0),
              ('Office leaves the unlinked list', _card_text(page)))
        _no_errors(s)


def scenario_no_ha_editor_still_edits():
    s = _serve()
    if s is None:
        return
    _reset()
    _facts()
    FAKE.available = False
    try:
        with s.browser(launch_args=H.GPU_ARGS) as page, _LogWatch() as log:
            _open(page, s)
            check((_link_state(page) or {}).get('available') is False, ('the link says no Home Assistant', _link_state(page)))
            _select(page, DEN, MAIN, 'Den')
            check(NO_HA in _card_text(page), ('the no-HA line on the room card', _card_text(page)))
            check(page.locator('#piece-card').get_by_label('Home Assistant area', exact=True).count() == 0,
                  'no area pick-list with no Home Assistant')
            check(page.locator('#piece-card select').count() == 0, 'no select on the room card')
            check('Suggested:' not in _card_text(page), _card_text(page))

            # Editing still works: rename the room.
            before = _store()
            name = page.locator('#piece-card').get_by_label('Name', exact=True)
            name.fill('Study')
            name.press('Enter')
            from services import twin_store
            check(_wait(page, lambda: twin_store.current_id() != before['round'], 20), 'the rename is stored')
            check(_wait(page, lambda: _room(H.model(), MAIN, DEN)['name'] == 'Study'), _room(H.model(), MAIN, DEN))

            _select(page, MAIN, MAIN, 'Main House')
            check('Areas with no room' not in _card_text(page), ('no unlinked list with no Home Assistant', _card_text(page)))
            check(_alert(page) is None, ('nothing alerts', _alert(page)))
            _no_errors(s)
            check(log.records == [], ('nothing logs an error', [r.getMessage() for r in log.records]))
    finally:
        FAKE.available = True


SCENARIOS = [
    scenario_room_card_picks_an_area,
    scenario_suggestion_use_links_and_places_the_garage_doors,
    scenario_unlinked_area_is_placed_on_a_room,
    scenario_no_ha_editor_still_edits,
]


if __name__ == '__main__':
    H.run(SCENARIOS)
