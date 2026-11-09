"""A person's roof choices stick, and roof flags reach the build status and the
plan (brief .superpowers/sdd/2026-11-08-house-editor-roofs-from-photos/
task-6-brief.md; spec docs/superpowers/specs/2026-11-08-house-editor-roofs-
from-photos-design.md section 6; plan Review Focus 3 and 5).

These are the build-level tests the brief puts in test_twin_build_roof_blocks.py.
That file is being worked on for Task 5, so they live here and reuse its
harness (household drawings, four tagged photos, the stub reader keyed by kind).

- A card edit to a derived roof section (src.step 'roof_blocks') is stored as
  a choice in building['roof']['choices']: {rect: the block's rect, kind?,
  ridge?, ends?, pitch?, plate?, overhang?, src: {person: True}}. The next
  rebuild applies it: the block keeps the person's form, its one roof is not
  doubled, and it is never flagged.
- A building built before this change, with a person-edited roof section
  (src.person), is rebuilt: the section stays a person section, and its block
  takes that section's form as its choice.
- Flags: the build status carries roof_flags: [{block_rect, text}], and the
  plan carries the same in building['roof']['flags'].

The reader answers every block's four sides plainly except the third
garage's right side, so the build makes exactly one flag (checked against
services.twin_roof_derive.derive_roof at 93fc46fd, with and without plan
evidence).

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_twin_roof_choices.py
"""
import copy
import json
import os
import sys
import tempfile
import traceback

if not os.environ.get('CHAUFFEUR_DATA_DIR', '').startswith(tempfile.gettempdir()):
    os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_twin_roof_choices_')
os.environ.pop('HA_BASE_URL', None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services import twin_build as tb  # noqa: E402
from services import twin_edit  # noqa: E402
from services import twin_plan  # noqa: E402
from services import twin_store as ts  # noqa: E402
import test_twin_build_roof_blocks as rb  # noqa: E402
from test_twin_build import check  # noqa: E402

# The household's blocks as services.twin_blocks makes them from the recorded draft.
MIDDLE = [14.33, 13.33, 37.33, 52]
LEFT_WING = [0, 14.33, 14.33, 54]
RIGHT_UPPER = [37.33, 19.33, 59, 43]
THIRD_GARAGE = [59, 22, 70, 42]
RIDGE_X = (MIDDLE, LEFT_WING, RIGHT_UPPER, THIRD_GARAGE)
BLOCK_TOL = 1.5      # the build's blocks come from the settled draft, not the raw read
PORCH_IDS = set(rb.PORCH_ROOFS)

SIDES_X = {'front': {'kind': 'slope'}, 'rear': {'kind': 'slope'},
           'left': {'kind': 'gable_end'}, 'right': {'kind': 'gable_end'}}
SIDES_Y = {'front': {'kind': 'gable_end'}, 'rear': {'kind': 'gable_end'},
           'left': {'kind': 'slope'}, 'right': {'kind': 'slope'}}


def _near(rect, want, tol=1.0):
    return rb._near(rect, want, tol)


def _observation(rect):
    """Every side seen, ridges as built, except the third garage's right end."""
    if _near(rect, THIRD_GARAGE, BLOCK_TOL):
        return {'sides': {**copy.deepcopy(SIDES_X), 'right': {'kind': 'hidden'}}, 'pitch': 8}
    if any(_near(rect, want, BLOCK_TOL) for want in RIDGE_X):
        return {'sides': copy.deepcopy(SIDES_X), 'pitch': 8}
    return {'sides': copy.deepcopy(SIDES_Y), 'pitch': 8}


class OneFlagReader(rb.BlocksReader):
    """Task 5's household reader; each photo shows every block from its own
    side, and the observations leave one end unseen."""

    def __call__(self, kind, images, context, *, run, step, **_options):
        answer = super().__call__(kind, images, context, run=run, step=step)
        if kind == 'photo_map':
            label = self.labels.get(images[-1].get('b64')) if images else None
            if label not in rb.PHOTO_MAPS:
                return answer
            side = rb.PHOTO_MAPS[label][0]
            return {'from_side': side, 'blocks': [{'id': b['id'], 'sides': [side]}
                                                  for b in context.get('blocks') or []]}
        if kind == 'roof_observe':
            return {'blocks': {b['id']: _observation(b['rect']) for b in context.get('blocks') or []}}
        return answer


# --- helpers -------------------------------------------------------------------

def _roof(house):
    return [(s['id'], s['kind'], s.get('ridge'), [round(v, 2) for v in s['rect']], s.get('ends'),
             s.get('pitch'), (s.get('src') or {}).get('step'), bool((s.get('src') or {}).get('person')))
            for s in house['roof']['sections']]


def _over(house, rect):
    """The roofs drawn over a block: every section but the porch roofs whose rect is the block's."""
    return [s for s in house['roof']['sections'] if s['id'] not in PORCH_IDS and _near(s['rect'], rect, BLOCK_TOL)]


def _derived(house, rect):
    found = [s for s in house['roof']['sections'] if (s.get('src') or {}).get('step') == 'roof_blocks'
             and _near(s.get('block') or [0, 0, 0, 0], rect, BLOCK_TOL) and _near(s['rect'], rect, BLOCK_TOL)]
    check(len(found) == 1, ('test setup (Task 5): the build derives one roof section over the block, '
                            'src.step roof_blocks, block: its rect', rect, _roof(house)))
    return found[0]


def _choices(house, rect):
    choices = house['roof'].get('choices')
    check(isinstance(choices, list), ('the plan keeps the person\'s roof choices in building["roof"]["choices"]',
                                      sorted(house['roof'])))
    return [c for c in choices if isinstance(c, dict) and _near(c.get('rect') or [0, 0, 0, 0], rect)]


def _flag_shape(flags, why):
    check(isinstance(flags, list), (why, 'roof flags are a list', flags))
    for f in flags:
        check(isinstance(f, dict) and {'block_rect', 'text'} <= set(f) and isinstance(f['text'], str)
              and isinstance(f['block_rect'], (list, tuple)) and len(f['block_rect']) == 4
              and all(isinstance(v, (int, float)) for v in f['block_rect']),
              (why, 'each roof flag is {block_rect, text}', f))
    return sorted((tuple(round(v, 2) for v in f['block_rect']), f['text']) for f in flags)


def _status_flags(st):
    return st.get('roof_flags')


def _plan_flags(house):
    return house['roof'].get('flags')


def _one_flag_build(labels):
    b, st = rb._build(OneFlagReader(labels))
    flags = rb._flags(st)
    check(len(flags) == 1 and _near(flags[0]['block_rect'], THIRD_GARAGE, BLOCK_TOL),
          ('test setup (Task 5): the build flags only the third garage', flags))
    return b, st


def _is_hip(section):
    return section['kind'] == 'hip' and all(rb._end(section, f"{section['ridge']}{i}") == 'hip' for i in (0, 1))


def _drawing_source():
    return next(r['source'] for r in ts.page_roles() if r.get('role') == 'roof')


# --- tests ---------------------------------------------------------------------

def test_flags_on_build_status_and_plan():
    labels = rb._main_house()
    b, st = _one_flag_build(labels)
    wanted = _flag_shape(rb._flags(st), 'the draft step')
    check(_flag_shape(_status_flags(st), 'the build status') == wanted,
          ('the build status carries roof_flags: [{block_rect, text}], the draft step\'s flags',
           sorted(k for k in st if k != 'events'), _status_flags(st)))
    check(_flag_shape(tb.status(b, since=10 ** 9).get('roof_flags'), 'a later poll') == wanted,
          'a poll for new events still carries the flags')
    check(_flag_shape(_plan_flags(rb._house()), 'the plan') == wanted,
          ('the plan carries the same flags in building["roof"]["flags"]', _plan_flags(rb._house())))
    renormalized, _ = twin_plan.normalize(ts.current())
    again = next(x for x in renormalized['buildings'] if x['id'] == 'house')
    check(_flag_shape(_plan_flags(again), 'normalize') == wanted, 'the flags survive normalize')


def test_card_edit_becomes_choice():
    """Review Focus 3: the card sets a derived roof to a hip and its pitch; the rebuild keeps both."""
    labels = rb._main_house()
    _one_flag_build(labels)
    section = _derived(rb._house(), LEFT_WING)
    check((section['kind'], section.get('ridge')) == ('gable', 'x'),
          ('test setup: the left wing is derived as a side gable', section))
    sid = section['id']
    twin_edit.save({'op': 'set', 'building': 'house', 'piece': sid, 'field': 'kind', 'value': 'hip'}, 'p1')
    twin_edit.save({'op': 'set', 'building': 'house', 'piece': sid, 'field': 'pitch', 'value': 6}, 'p1')

    house = rb._house()
    mine = _choices(house, section['block'])
    check(len(mine) == 1, ('the two card edits are one choice on the block, keyed by its rect',
                           house['roof'].get('choices')))
    choice = mine[0]
    check(choice.get('kind') == 'hip' and choice.get('pitch') == 6 and (choice.get('src') or {}).get('person') is True,
          ('the choice holds the person\'s kind and pitch, marked as theirs', choice))
    check('ends' not in choice or all(style == 'hip' for style in choice['ends'].values()),
          ('a hip choice never carries the gable ends the photos gave', choice))
    edited = next(s for s in house['roof']['sections'] if s['id'] == sid)
    check(_is_hip(edited), ('the edited roof is a hip at both ends, not a hip kind with gable ends', edited))

    _, st = rb._build(OneFlagReader(labels))
    house = rb._house()
    over = _over(house, LEFT_WING)
    check(len(over) == 1, ('the left wing has one roof after the rebuild, never the derived one beside a kept copy',
                           _roof(house)))
    roof = over[0]
    check(_is_hip(roof), ('the rebuild keeps the person\'s hip', roof['kind'], roof.get('ends')))
    check(roof.get('pitch') == 6 and roof.get('pitch_source') == 'person',
          ('the rebuild keeps the person\'s pitch', roof.get('pitch'), roof.get('pitch_source')))
    check(roof.get('state') != 'ghost', ('the chosen roof settles', roof.get('why')))
    check(len(_choices(house, LEFT_WING)) == 1, ('the choice is kept across the rebuild, once',
                                                 house['roof'].get('choices')))
    check(not rb._flag_for(rb._flags(st), LEFT_WING), 'a block with a choice is never flagged')


def _as_old_building(source):
    """The current house as the draft step left it before this change: the
    draft's own roof sections (src.step 'draft', read where they are), no
    derived sections, no choices or flags; the right upper's hip edited by a
    person (its pitch set to 7 on the card)."""
    plan = ts.current()
    house = next(b for b in plan['buildings'] if b['id'] == 'house')
    read, _ = twin_plan.normalize({'units': 'ft', 'buildings': [rb.recorded('draft-main-house.json')['building']]})
    sections = copy.deepcopy(read['buildings'][0]['roof']['sections'])
    for s in sections:
        s['src'] = {'sheet': source, 'page': 3, 'step': 'draft'}
        s['state'] = 'settled'
        s['read_geometry'] = {'rect': list(s['rect'])}
        s.pop('block', None)
        if s['id'] == 'r_right':
            s['pitch'], s['pitch_source'] = 7, 'person'
            s['src'] = {'person': True, 'sheet': source, 'page': 3}
    house['roof']['sections'] = sections
    house['roof'].pop('choices', None)
    house['roof'].pop('flags', None)
    ids = {s['id'] for s in sections}
    for e in house['roof'].get('extensions', []):
        if e.get('section') not in ids:
            e['section'] = 'r_garage'
    normalized, _ = twin_plan.normalize(plan)
    ts.push_round(normalized, 'build')
    old = next(s for s in rb._house()['roof']['sections'] if s['id'] == 'r_right')
    check(old['kind'] == 'hip' and old['pitch'] == 7 and old['src'].get('person') is True
          and _near(old['rect'], RIGHT_UPPER), ('test setup: the old person-edited hip is in place', old))
    check(not any((s.get('src') or {}).get('step') == 'roof_blocks' for s in rb._house()['roof']['sections']),
          'test setup: no derived section yet')
    return old


def test_old_person_sections_migrate():
    """Review Focus 5: an old building's person-edited roof section is kept, and its block takes its form."""
    labels = rb._main_house()
    rb._build(OneFlagReader(labels))
    old = _as_old_building(_drawing_source())

    _, st = rb._build(OneFlagReader(labels))
    house = rb._house()
    kept = [s for s in house['roof']['sections'] if s['id'] == 'r_right']
    check(len(kept) == 1 and (kept[0].get('src') or {}).get('person') is True,
          ('the person-edited section is kept as a person section', _roof(house)))
    check((kept[0]['kind'], kept[0].get('ridge'), kept[0]['pitch']) == ('hip', 'x', 7) and _near(kept[0]['rect'], old['rect']),
          ('the kept section keeps the person\'s form', kept[0]))

    mine = _choices(house, RIGHT_UPPER)
    check(len(mine) == 1, ('its block takes that section\'s form as its choice, keyed by the block\'s rect',
                           house['roof'].get('choices')))
    choice = mine[0]
    check(choice.get('kind') == 'hip' and choice.get('ridge', 'x') == 'x' and choice.get('pitch') == 7
          and (choice.get('src') or {}).get('person') is True,
          ('the choice is the section\'s form, marked as the person\'s', choice))
    check(not rb._flag_for(rb._flags(st), RIGHT_UPPER), 'the block with the migrated choice is not flagged')
    status = _status_flags(st)
    check(isinstance(status, list) and not rb._flag_for(status, RIGHT_UPPER), ('nor on the build status', status))

    over = _over(house, RIGHT_UPPER)
    check(all(s['kind'] == 'hip' and s.get('pitch') == 7 for s in over),
          ('nothing over the block contradicts the person\'s hip', _roof(house)))
    check(len(over) == 1, ('the block has one roof: the kept person section is not doubled by a derived copy',
                           [(s['id'], s['kind'], s.get('src')) for s in over]))

    # The migration runs once: a second rebuild keeps one choice and the section.
    rb._build(OneFlagReader(labels))
    house = rb._house()
    check(len(_choices(house, RIGHT_UPPER)) == 1, ('a later rebuild never adds a second choice',
                                                    house['roof'].get('choices')))
    check(len(_over(house, RIGHT_UPPER)) == 1, ('and the block still has one roof', _roof(house)))


def test_choice_clears_flag():
    labels = rb._main_house()
    b, st = _one_flag_build(labels)
    check(_plan_flags(rb._house()) and rb._flag_for(_plan_flags(rb._house()), THIRD_GARAGE),
          ('the plan carries the third garage\'s flag', _plan_flags(rb._house())))
    flag_text = rb._flags(st)[0]['text']
    section = _derived(rb._house(), THIRD_GARAGE)
    twin_edit.save({'op': 'set', 'building': 'house', 'piece': section['id'], 'field': 'pitch', 'value': 6}, 'p1')
    house = rb._house()
    check(len(_choices(house, section['block'])) == 1, ('the card edit is the block\'s choice',
                                                        house['roof'].get('choices')))
    flags = _plan_flags(house)
    check(isinstance(flags, list) and not rb._flag_for(flags, THIRD_GARAGE),
          ('the choice clears the block\'s flag from the plan at once, so its marker goes', flags))

    b2, st2 = rb._build(OneFlagReader(labels))
    check(not rb._flag_for(rb._flags(st2), THIRD_GARAGE),
          ('a rebuild never flags a block with a choice', rb._flags(st2)))
    status = _status_flags(st2)
    check(isinstance(status, list) and not rb._flag_for(status, THIRD_GARAGE), ('nor on the build status', status))
    flags = _plan_flags(rb._house())
    check(isinstance(flags, list) and not rb._flag_for(flags, THIRD_GARAGE), ('nor in the plan', flags))
    again = [e for e in st2['events'] if e['type'] == 'log' and e.get('text') == flag_text]
    check(not again, ('the cleared flag is not logged again', again))
    roof = _over(rb._house(), THIRD_GARAGE)
    check(len(roof) == 1 and roof[0].get('pitch') == 6, ('the third garage keeps the person\'s pitch', _roof(rb._house())))


TESTS = (
    test_flags_on_build_status_and_plan,
    test_card_edit_becomes_choice,
    test_old_person_sections_migrate,
    test_choice_clears_flag,
)


if __name__ == '__main__':
    failed = []
    for fn in TESTS:
        try:
            fn()
        except Exception as exc:
            failed.append(fn.__name__)
            print('  FAIL', fn.__name__, type(exc).__name__, ' '.join(str(exc).split())[:500])
            if not isinstance(exc, AssertionError):
                traceback.print_exc()
        else:
            print('  ok  ', fn.__name__)
    print(f'{len(TESTS) - len(failed)}/{len(TESTS)} passed')
    sys.exit(1 if failed else 0)
