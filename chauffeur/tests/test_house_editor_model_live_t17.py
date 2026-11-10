"""Flags and proposals on the model, in real Chromium (spec
docs/superpowers/specs/2026-11-09-house-connected-model-design.md sections 4.1,
4.6 (step 6 and 8 of the migration) and 6 ("Checks come one at a time"); plan
docs/superpowers/plans/2026-11-09-house-connected-model-pieces-1-2.md Part B
Task 17; brief .superpowers/sdd/2026-11-09-house-connected-model-pieces-1-2/
task-17-brief.md; rulings R2 (proposals ride only in `proposals`, the editor
draws them), R4 (Task 17 adds the `flag_ok` field to Task 9's `set`), R28
(migration separator flags are grouped one per level, and every migration
separator carries src.step 'migration' so the editor highlights them all when
the flag is opened), R29 (file layout) and R31 (assemble keeps wall ids)).

The house is the household's migrated house (tests/house_editor_model_harness.py
seeds it through twin_store.push_round), unchanged before the push.

The test hooks (window.__twinEditor, only under ?test=1). Task 10 gave
selection(); this file adds two, named here because the brief names none:

- flags() returns {count, markers, current, highlighted}:
    count        the number of model flags the editor lists (every building);
    markers      [{building, index, at: [x, y]}], one per flag drawn in the
                 scene, `index` the flag's index in that building's `flags`,
                 `at` its building-local plan point in feet;
    current      {building, index, text, piece} of the flag being shown, or null;
    highlighted  [wall ids] the scene highlights for the current flag.
- proposals() returns [{building, id, kind, against}], one per proposal drawn
  as a ghost.

A click on a proposal's ghost selects it: selection() reads
{kind: 'proposal', id: <the proposal's id>}.

What the person sees, from the brief: the count `N things to check` in the
panel (#editor-agent; `1 thing to check` for one), which walks the flags one
at a time each time it is clicked; a flag card with **Looks right** and
**Fix it**; a proposal card with **Use this** and **Dismiss**.

Pieces used (ids after migration; R31 keeps the read's wall ids):
- POOL_WALL  pool-house L1, wall:d60289b4c26b487db5145bdeb22d530e, y 17.33 from
             x 0 to 17.75, between the Pool Lounge (south) and a Room (north)
- MAIN_WALL  main-house L1, wall:738a2cbddd52469a968bac0b57b29ebc, y 26.33 from
             x 0 to 14.33, between two Rooms
Both are interior walls whose ends T into other walls and that nothing T's
into. The proposal fixture marks both person-owned in the stored model (the
person's edit, as Task 5's test does by hand), then pushes a new read in which
each sits 2 ft further north (+y). The Task 5 ownership rule makes each read a
proposal ({kind: 'wall', against: <the wall>}) whose ghost stands 2 ft beside
the person's wall.

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_house_editor_model_live_t17.py
"""
import json
import math
import os
import re
import sys
import tempfile
import time

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='chauffeur_house_editor_t17_'))
os.environ.pop('HA_BASE_URL', None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import house_editor_model_harness as H  # noqa: E402

check = H.check
POOL, MAIN = 'pool-house', 'main-house'
POOL_WALL = 'wall:d60289b4c26b487db5145bdeb22d530e'
MAIN_WALL = 'wall:738a2cbddd52469a968bac0b57b29ebc'
POOL_LOUNGE = 'room:5d7de10ca48340ae85c407d22337c6f7'
SHIFT = 2.0                 # the new read moves each wall this far north (+y)
TOL = 0.05

COUNT_RE = re.compile(r'^\s*(\d+) things? to check\s*$')
GROUPED_RE = re.compile(r'^I added (\d+) invisible walls on the (.+) to keep rooms apart; check them\.$')
SINGLE_RE = re.compile(r'^I added an invisible wall here to keep (two rooms|the .+ and the .+) apart; check it\.$')


def _serve():
    return H.serve()


# --- the model ---------------------------------------------------------------------

def _wall_ends(b, wall):
    joints = {j['id']: j['at'] for j in b['joints']}
    return [list(joints[j]) for j in wall['joints']]


def _on_segment(p, a, b, tol=0.1):
    ax, ay = a
    bx, by = b
    length2 = (bx - ax) ** 2 + (by - ay) ** 2
    t = 0 if length2 == 0 else max(0, min(1, ((p[0] - ax) * (bx - ax) + (p[1] - ay) * (by - ay)) / length2))
    return math.dist(p, (ax + t * (bx - ax), ay + t * (by - ay))) <= tol


def _is_separator_flag(flag):
    return bool(GROUPED_RE.match(flag.get('text', '')) or SINGLE_RE.match(flag.get('text', '')))


def _migration_separators(b, level):
    return [w for w in b['walls'] if w['level'] == level and w.get('kind') == 'separator'
            and (w.get('src') or {}).get('step') == 'migration']


def _all_flags(model):
    """Every model flag as (building, index, flag), buildings in model order."""
    return [(b['id'], i, f) for b in model['buildings'] for i, f in enumerate(b.get('flags') or [])]


def _check_grouped_separator_flags(model):
    """R28 on the stored model: one separator flag per level that has migration
    separators, with the grouped copy, placed at the first of them."""
    grouped = 0
    for b in model['buildings']:
        for level in b['levels']:
            seps = _migration_separators(b, level['id'])
            flags = [f for f in b.get('flags') or [] if f.get('level') == level['id'] and _is_separator_flag(f)]
            if not seps:
                check(not flags, ('no separator flag on a level without migration separators', b['id'], level['id'], flags))
                continue
            check(len(flags) == 1, ('R28: exactly one separator flag per level', b['id'], level['id'],
                                    len(seps), [f['text'] for f in flags]))
            text = flags[0]['text']
            if len(seps) == 1:
                check(SINGLE_RE.match(text), ('one separator keeps the single-wall copy', b['id'], level['id'], text))
            else:
                want = f"I added {len(seps)} invisible walls on the {level['name']} to keep rooms apart; check them."
                check(text == want, ('R28 grouped copy', b['id'], level['id'], text, want))
                grouped += 1
            a, c = _wall_ends(b, seps[0])
            check(_on_segment(flags[0]['at'], a, c), ('the flag sits at the first separator', flags[0]['at'], seps[0]['id'], a, c))
    check(grouped >= 1, 'R28: the household has at least one level with several migration separators, so one grouped flag')


def _facts():
    model = H.model()
    check(model is not None and model.get('schema') == 'chauffeur.twin.plan/3',
          'the store holds no schema 3 model (Task 6: twin_store.current_model)')
    flags = _all_flags(model)
    check(len(flags) >= 3, ('the migrated household has flags to check', len(flags)))
    return model, flags


# --- the page -----------------------------------------------------------------------

def _no_errors(served):
    errors = H.unexpected(served.errors())
    check(not errors, errors)


def _poll(read, until, timeout=5.0, page=None):
    deadline = time.time() + timeout
    while True:
        value = read()
        if until(value) or time.time() > deadline:
            return value
        if page is not None:
            page.wait_for_timeout(50)
        else:
            time.sleep(0.05)


def _flags(page):
    return H.editor_state(page, 'flags')


def _count(page):
    """The panel's count control, which must be visible and say `N thing(s) to check`."""
    node = page.locator('#editor-agent').get_by_text(COUNT_RE)
    check(node.count() == 1 and node.first.is_visible(), ('the panel shows one "N things to check"', node.count()))
    return node.first


def _count_number(page):
    match = COUNT_RE.match(_count(page).inner_text())
    return int(match.group(1))


def _count_says(page, n):
    word = 'thing' if n == 1 else 'things'
    node = page.locator('#editor-agent').get_by_text(f'{n} {word} to check', exact=True)
    return node.count() == 1 and node.first.is_visible()


def _button(page, label):
    return page.locator(f'button:text-is("{label}"):visible')


def _same(current, building, index):
    return bool(current) and current.get('building') == building and current.get('index') == index


def _centred(page, bid, x, y, z):
    """True when a building-local point projects into the middle half of the canvas."""
    sx, sy = H.screen_of_world(page, x, y, z, bid)
    box = page.evaluate('() => { const r = window.__twin.renderer3.domElement.getBoundingClientRect();'
                        ' return [r.left, r.top, r.width, r.height]; }')
    left, top, width, height = box
    return abs(sx - (left + width / 2)) <= width / 4 and abs(sy - (top + height / 2)) <= height / 4


def _ops_posted(page):
    """Record every op the page posts to /api/house/editor/op (the request bodies)."""
    posted = []

    def seen(request):
        if request.method == 'POST' and request.url.split('?')[0].endswith('/api/house/editor/op'):
            try:
                posted.append(request.post_data_json)
            except Exception:  # noqa: BLE001 -- a body that is not JSON is recorded as text
                posted.append(request.post_data)
    page.on('request', seen)
    return posted


def _the_op(body):
    return body.get('op') if isinstance(body, dict) and isinstance(body.get('op'), dict) else body


def _replay(page, body):
    """Post a recorded body again through the page's own fetch (the parent session)."""
    return page.evaluate("""async (body) => {
        const response = await fetch((window.chfBase ?? '../') + 'api/house/editor/op', {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
        return response.status;
    }""", body)


def _walk_to(page, building, index, total):
    """Click the count until the given flag is the one shown; returns the clicks it took."""
    for clicks in range(1, total + 1):
        _count(page).click()
        H.settle(page)
        current = _poll(lambda: _flags(page).get('current'), lambda c: c is not None, page=page)
        if _same(current, building, index):
            return clicks
    raise AssertionError(('walking the flags never reached', building, index, total))


# --- scenarios ------------------------------------------------------------------------

def scenario_migrated_household_lists_its_flags():
    s = _serve()
    if s is None:
        return
    model, flags = _facts()
    _check_grouped_separator_flags(model)
    levels = {b['id']: {lv['id']: lv for lv in b['levels']} for b in model['buildings']}
    pieces = {b['id']: {p['id']: kind for kind, name in (('wall', 'walls'), ('opening', 'openings'),
                                                         ('anchor', 'anchors'), ('item', 'items'))
                        for p in b.get(name) or []}
              for b in model['buildings']}
    with s.browser(launch_args=H.GPU_ARGS) as page:
        H.open_editor(page, s)
        total = len(flags)
        check(_count_says(page, total), ('the panel counts every flag on the model', total, _count(page).inner_text()))
        state = _flags(page)
        check(state.get('count') == total and state.get('current') is None, ('nothing shown before the count is clicked', state))

        # Every flag draws a marker at its point.
        markers = state.get('markers') or []
        check(len(markers) == total, ('one marker per flag', len(markers), total))
        for bid, index, flag in flags:
            marker = next((m for m in markers if m.get('building') == bid and m.get('index') == index), None)
            check(marker is not None, ('a marker for the flag', bid, index, flag['text']))
            check(math.dist(marker['at'][:2], flag['at'][:2]) <= TOL, ('the marker sits at the flag point', marker, flag['at']))

        # The count walks the flags one at a time, focusing the camera and selecting the piece.
        visited = []
        for _ in range(total):
            _count(page).click()
            H.settle(page)
            before = visited[-1] if visited else None
            current = _poll(lambda: _flags(page).get('current'),
                            lambda c: c is not None and (c.get('building'), c.get('index')) != before, page=page)
            check(current is not None, 'clicking the count shows a flag')
            key = (current['building'], current['index'])
            check(key not in visited, ('each click shows the next flag, never one already seen', key, visited))
            visited.append(key)
            bid, index = key
            flag = next(f for b, i, f in flags if b == bid and i == index)
            check(current.get('text') == flag['text'], ('the shown flag is the model flag', current, flag['text']))
            text = page.get_by_text(flag['text'], exact=True)
            check(text.count() >= 1 and text.first.is_visible(), ('the flag\'s words are on screen', flag['text']))
            check(_button(page, 'Looks right').count() == 1 and _button(page, 'Fix it').count() == 1,
                  ('the flag offers Looks right and Fix it', flag['text']))
            piece = flag.get('piece')
            if isinstance(piece, str) and piece in pieces[bid]:
                sel = _poll(lambda: H.editor_state(page, 'selection'), lambda v: bool(v) and v.get('id') == piece, page=page)
                check(sel and sel.get('id') == piece and sel.get('kind') == pieces[bid][piece],
                      ('walking to a flag selects its piece', flag['text'], piece, sel))
            level = levels[bid].get(flag.get('level'))
            if level is not None:
                at = flag['at']
                ok = _poll(lambda: _centred(page, bid, at[0], at[1], level['elevation']), bool, timeout=4.0, page=page)
                check(ok, ('the camera focuses the flag', bid, flag['text'], at,
                           H.screen_of_world(page, at[0], at[1], level['elevation'], bid)))
            if GROUPED_RE.match(flag['text']):
                b = H.building(model, bid)
                want = sorted(w['id'] for w in _migration_separators(b, flag['level']))
                got = sorted(_flags(page).get('highlighted') or [])
                check(got == want, ('R28: opening the grouped flag highlights every migration separator on its level',
                                    flag['text'], got, want))
        check(sorted(visited) == sorted((b, i) for b, i, _ in flags), ('the walk visits every flag once', visited))

        # Fix it selects the piece and keeps the flag.
        bid, index, flag = next(((b, i, f) for b, i, f in flags
                                 if isinstance(f.get('piece'), str) and f['piece'] in pieces[b]), (None, None, None))
        check(flag is not None, 'the household has a flag on a piece')
        _walk_to(page, bid, index, total)
        _button(page, 'Fix it').click()
        H.settle(page)
        sel = _poll(lambda: H.editor_state(page, 'selection'), lambda v: bool(v) and v.get('id') == flag['piece'], page=page)
        check(sel and sel.get('id') == flag['piece'], ('Fix it selects the piece', flag, sel))
        check(len(_all_flags(H.model())) == total and _count_says(page, total), 'Fix it keeps the flag')
        _no_errors(s)


def scenario_looks_right_clears_a_separator_flag():
    s = _serve()
    if s is None:
        return
    model, flags = _facts()
    target = next(((b, i, f) for b, i, f in flags if GROUPED_RE.match(f['text'])), None)
    check(target is not None, ('R28: the migrated household carries a grouped separator flag',
                               [f['text'] for _, _, f in flags]))
    bid, index, flag = target
    b0 = H.building(model, bid)
    flags_before = {b['id']: list(b.get('flags') or []) for b in model['buildings']}
    separators_before = sorted(w['id'] for w in b0['walls'] if w.get('kind') == 'separator')
    with s.browser(launch_args=H.GPU_ARGS) as page:
        posted = _ops_posted(page)
        H.open_editor(page, s)
        total = len(flags)
        check(_count_says(page, total), ('the count before', total))
        _walk_to(page, bid, index, total)
        check(page.get_by_text(flag['text'], exact=True).first.is_visible(), 'the separator flag is shown')
        want = sorted(w['id'] for w in _migration_separators(b0, flag['level']))
        check(sorted(_flags(page).get('highlighted') or []) == want,
              ('R28: the level\'s migration separators are highlighted together', _flags(page).get('highlighted'), want))

        _button(page, 'Looks right').click()
        H.settle(page)
        after = _poll(H.model, lambda m: len(_all_flags(m)) == total - 1, timeout=15.0)
        b1 = H.building(after, bid)
        expected = flags_before[bid][:index] + flags_before[bid][index + 1:]
        check(b1['flags'] == expected, ('Looks right removes exactly that flag', b1['flags'], expected))
        for other in after['buildings']:
            if other['id'] != bid:
                check(other['flags'] == flags_before[other['id']], ('the other building keeps its flags', other['id']))
        check(sorted(w['id'] for w in b1['walls'] if w.get('kind') == 'separator') == separators_before,
              'Looks right keeps the separators; it only clears the check')

        ops = [_the_op(body) for body in posted]
        sets = [op for op in ops if isinstance(op, dict) and op.get('op') == 'set' and op.get('field') == 'flag_ok']
        check(len(sets) == 1, ('Looks right posts one set with field flag_ok', posted))
        check(sets[0].get('building') == bid and flag['text'] in json.dumps(sets[0], ensure_ascii=False),
              ('the set names the building and carries the flag\'s text', sets[0]))

        _poll(lambda: _count_says(page, total - 1), bool, timeout=5.0, page=page)
        check(_count_says(page, total - 1), ('the count drops by one', _count(page).inner_text()))
        state = _flags(page)
        check(state.get('count') == total - 1 and len(state.get('markers') or []) == total - 1,
              ('its marker is gone', state.get('count'), len(state.get('markers') or [])))
        check(not _same(state.get('current'), bid, index) or (state['current'].get('text') != flag['text']),
              ('the cleared flag is no longer shown', state.get('current')))

        # The flag is removed by index AND text: the same request again now
        # points at a different flag (or none) and must remove nothing.
        status = _replay(page, posted[[i for i, op in enumerate(ops) if op is sets[0]][0]])
        again = H.model()
        check([b['flags'] for b in again['buildings']] == [b['flags'] for b in after['buildings']],
              ('a stale flag_ok removes nothing', status, H.building(again, bid)['flags']))
        _no_errors(s)


# --- proposals ------------------------------------------------------------------------

_PROPOSED = {}


def _proposal_id(proposal):
    """A proposal's id. Task 2's shape puts it on the proposal ({id, kind, piece,
    against}); the bridge in the tree writes `<wall id>:proposal` on its piece
    only. Either names it."""
    return proposal.get('id') or (proposal.get('piece') or {}).get('id')


def _proposals_seeded():
    """The person owns POOL_WALL and MAIN_WALL; a new read puts each 2 ft north.

    Returns {wall id: (building, proposal)} from the stored model (once per process).
    """
    if 'by_wall' in _PROPOSED:
        return _PROPOSED['by_wall']
    from services import twin_store
    targets = {POOL_WALL: POOL, MAIN_WALL: MAIN}

    def own(model):
        for b in model['buildings']:
            for wall in b['walls']:
                if wall['id'] in targets:
                    wall['src'] = {**(wall.get('src') or {}), 'person': True}
        return model
    twin_store.update_model(own, kind='edit', note='the person keeps these walls')

    read = H.household_plan()
    for b in read['buildings']:
        for wall in b['walls']:
            if wall['id'] in targets:
                wall['from'] = [wall['from'][0], wall['from'][1] + SHIFT]
                wall['to'] = [wall['to'][0], wall['to'][1] + SHIFT]
    twin_store.push_round(read, 'build')

    model = H.model()
    by_wall = {}
    for wid, bid in targets.items():
        b = H.building(model, bid)
        props = [p for p in b.get('proposals') or [] if p.get('kind') == 'wall' and p.get('against') == wid]
        check(len(props) == 1 and _proposal_id(props[0]), ('the new read is one proposal against the person\'s wall',
                                                            wid, b.get('proposals')))
        props[0] = {**props[0], 'id': _proposal_id(props[0])}
        wall = next(w for w in b['walls'] if w['id'] == wid)
        check((wall.get('src') or {}).get('person') is True, ('the person\'s wall stays live and theirs', wall))
        by_wall[wid] = (bid, props[0])
    _PROPOSED['by_wall'] = by_wall
    return by_wall


def _live_solid_on(b, y, x0, x1):
    """Live solid walls lying on the line y from x0 to x1 (either direction)."""
    found = []
    for wall in b['walls']:
        if wall.get('state') == 'proposal' or wall.get('kind') == 'separator':
            continue
        (ax, ay), (bx, by) = _wall_ends(b, wall)
        if (abs(ay - y) <= TOL and abs(by - y) <= TOL
                and abs(min(ax, bx) - x0) <= 0.1 and abs(max(ax, bx) - x1) <= 0.1):
            found.append(wall)
    return found


def _open_proposal(page, bid, level_key, proposal, x, y):
    """Floor view, a steep camera from the south, a click on the ghost at (x, y)."""
    H.choose_floor(page, level_key)
    H.look_at(page, bid, (x, y - 6.0, 30.0), (x, y, 5.0))
    drawn = _poll(lambda: H.editor_state(page, 'proposals'),
                  lambda v: any(p.get('id') == proposal['id'] for p in v or []), page=page)
    check(any(p.get('id') == proposal['id'] and p.get('building') == bid and p.get('kind') == 'wall'
              and p.get('against') == proposal['against'] for p in drawn or []),
          ('the proposal is drawn as a ghost', proposal['id'], drawn))
    H.click_world(page, x, y, 5.0, bid)
    sel = _poll(lambda: H.editor_state(page, 'selection'),
                lambda v: bool(v) and v.get('kind') == 'proposal' and v.get('id') == proposal['id'], page=page)
    check(sel and sel.get('kind') == 'proposal' and sel.get('id') == proposal['id'],
          ('a click on the ghost beside the person\'s wall selects the proposal', sel))
    check(_button(page, 'Use this').count() == 1 and _button(page, 'Dismiss').count() == 1,
          'the proposal card offers Use this and Dismiss')


def scenario_proposal_use_this_replaces_the_wall():
    s = _serve()
    if s is None:
        return
    _facts()
    bid, proposal = _proposals_seeded()[POOL_WALL]
    b0 = H.building(H.model(), bid)
    y0, ghost_y = 17.333, 17.333 + SHIFT
    check(len(_live_solid_on(b0, y0, 0, 17.75)) == 1, 'the person\'s wall stands at y 17.33 before the answer')
    check(not _live_solid_on(b0, ghost_y, 0, 17.75), 'the read is only a proposal, not a second live wall (R2)')
    with s.browser(launch_args=H.GPU_ARGS) as page:
        posted = _ops_posted(page)
        H.open_editor(page, s)
        _open_proposal(page, bid, f'{bid}:L1', proposal, 8.0, ghost_y)
        before = H.scene_signature(page)
        _button(page, 'Use this').click()
        H.settle(page)

        after = _poll(H.model, lambda m: not any(_proposal_id(p) == proposal['id']
                                                 for p in H.building(m, bid).get('proposals') or []), timeout=15.0)
        b1 = H.building(after, bid)
        check(not any(_proposal_id(p) == proposal['id'] for p in b1.get('proposals') or []), ('the proposal is gone', b1.get('proposals')))
        used = _live_solid_on(b1, ghost_y, 0, 17.75)
        check(len(used) == 1, ('the read\'s wall now stands 2 ft north', [(w['id'], _wall_ends(b1, w)) for w in b1['walls']]))
        check(used[0].get('state', 'settled') == 'settled' and (used[0].get('src') or {}).get('person') is True,
              ('using the proposal is the person\'s act', used[0]))
        check(not _live_solid_on(b1, y0, 0, 17.75), 'the person\'s old wall is replaced, not kept beside it')
        lounge = next(r for r in b1['rooms'] if r['id'] == POOL_LOUNGE)
        check(abs(max(p[1] for p in lounge['polygon']) - ghost_y) <= TOL,
              ('the Pool Lounge now reaches the moved wall', lounge['polygon']))

        ops = [_the_op(body) for body in posted]
        check({'op': 'accept_proposal', 'building': bid, 'id': proposal['id']} in
              [{k: op.get(k) for k in ('op', 'building', 'id')} for op in ops if isinstance(op, dict)],
              ('Use this posts accept_proposal', posted))
        H.wait_rebuilt(page, before)
        drawn = H.editor_state(page, 'proposals') or []
        check(not any(p.get('id') == proposal['id'] for p in drawn), ('the ghost is gone', drawn))
        sel = H.editor_state(page, 'selection')
        check(not (sel and sel.get('kind') == 'proposal' and sel.get('id') == proposal['id']),
              ('the used proposal is no longer selected', sel))
        _no_errors(s)


def scenario_proposal_dismiss_keeps_the_persons_wall():
    # Brief: the proposal card's Dismiss posts dismiss_proposal.
    s = _serve()
    if s is None:
        return
    _facts()
    bid, proposal = _proposals_seeded()[MAIN_WALL]
    y0, ghost_y = 26.333, 26.333 + SHIFT
    with s.browser(launch_args=H.GPU_ARGS) as page:
        posted = _ops_posted(page)
        H.open_editor(page, s)
        _open_proposal(page, bid, f'{bid}:L1', proposal, 7.0, ghost_y)
        before = H.scene_signature(page)
        _button(page, 'Dismiss').click()
        H.settle(page)

        after = _poll(H.model, lambda m: not any(_proposal_id(p) == proposal['id']
                                                 for p in H.building(m, bid).get('proposals') or []), timeout=15.0)
        b1 = H.building(after, bid)
        check(not any(_proposal_id(p) == proposal['id'] for p in b1.get('proposals') or []), ('the proposal is gone', b1.get('proposals')))
        kept = _live_solid_on(b1, y0, 0, 14.333)
        check(len(kept) == 1 and kept[0]['id'] == MAIN_WALL and (kept[0].get('src') or {}).get('person') is True,
              ('the person\'s wall stays where they left it', kept))
        check(not _live_solid_on(b1, ghost_y, 0, 14.333), 'nothing stands where the proposal was')

        ops = [_the_op(body) for body in posted]
        check({'op': 'dismiss_proposal', 'building': bid, 'id': proposal['id']} in
              [{k: op.get(k) for k in ('op', 'building', 'id')} for op in ops if isinstance(op, dict)],
              ('Dismiss posts dismiss_proposal', posted))
        H.wait_rebuilt(page, before)
        drawn = H.editor_state(page, 'proposals') or []
        check(not any(p.get('id') == proposal['id'] for p in drawn), ('the ghost is gone', drawn))
        _no_errors(s)


SCENARIOS = [
    scenario_migrated_household_lists_its_flags,
    scenario_looks_right_clears_a_separator_flag,
    scenario_proposal_use_this_replaces_the_wall,
    scenario_proposal_dismiss_keeps_the_persons_wall,
]


if __name__ == '__main__':
    H.run(SCENARIOS)
