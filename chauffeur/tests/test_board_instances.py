"""Configurable board tiles: the config actually reaches the tile, and the
editor actually writes the config.

The arc's whole promise is "two calendar tiles, set to different things". That
promise has two halves and they fail differently:

  - the SERVER half — a builder that ignores its config is a setting that does
    nothing, and the household finds out by staring at an unchanged wall;
  - the EDITOR half — a form that writes a config the builder does not read, or
    writes a full config of numbers nobody chose, is the same bug from the
    other end.

So the builders are exercised through `home_board.build` with real config, and
the editor's own helpers are RUN in node against a stub, because `setCfg`'s
"a value equal to the default stops being stored" rule is the kind of thing
that looks obviously right and is obviously wrong the first time somebody opens
an options panel and closes it again.

Run from chauffeur/:  python tests/test_board_instances.py
"""
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('CHAUFFEUR_DATA_DIR',
                      tempfile.mkdtemp(prefix='chauffeur_instances_'))

TPL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   'templates')

import tpl_source  # noqa: E402
from services import home_board  # noqa: E402


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


# --- the declaration itself ------------------------------------------------

def scenario_every_declared_option_is_a_shape_the_editor_can_draw():
    """The editor renders options from the declaration and knows six shapes.
    A seventh invented in home_board would render as nothing at all — a setting
    that exists, is offered, and cannot be set.

    `select` and `entity` are the same idea at two scales, and the split is
    not cosmetic: `select` draws every option as a chip, which is right for six
    members and unusable for the two thousand entities an ordinary Home
    Assistant has. `entity` is a text field with a datalist, fed lazily.

    The known set is READ OUT OF THE EDITOR rather than written down here. A
    hard-coded list turns this guard into a second place to remember, and the
    failure it exists to catch — a shape the editor cannot draw — is exactly
    what a stale list would let through."""
    tpl = tpl_source.read('home.html')
    known = set(re.findall(r"o\.type === '([a-z]+)'", tpl))
    check(len(known) >= 6, f"the editor's option shapes could not be read: {known}")
    for w in home_board.catalog()['widgets']:
        for o in w.get('options') or []:
            check(o.get('type') in known,
                  f"{w['key']}.{o.get('key')} is a '{o.get('type')}', which the "
                  f"editor cannot draw — known shapes are {sorted(known)}")
            check(o.get('key') and o.get('label'),
                  f"{w['key']} has an option with no key or no label: {o}")
            if o['type'] == 'choice':
                check(o.get('choices'), f"{w['key']}.{o['key']} is a choice with "
                                        f"no choices")
            if o['type'] == 'select':
                check(o.get('source') in home_board.option_sources(),
                      f"{w['key']}.{o['key']} draws from '{o.get('source')}', "
                      f"which option_sources() does not supply")
            if o['type'] == 'entity':
                # Fed by ha_options(), NOT by the catalog — the whole reason
                # this shape exists is to keep thousands of entities out of a
                # payload every browser loads.
                check(o.get('source') in ('ha_entities', 'ha_cameras'),
                      f"{w['key']}.{o['key']} draws from '{o.get('source')}', "
                      f"which ha_options() does not supply")


def scenario_every_declared_option_survives_its_own_builder():
    """The sweep. Every type, every option it declares, set to an extreme
    value at once — the maximum for a number, the opposite of the default for a
    switch, the last choice, and an id that matches nothing for a picker.

    This is the cheap test that catches the expensive mistake: an option added
    to `WIDGETS` and never read, or read under a different key, or read in a
    way that throws on an empty household. A tile whose builder raises is
    swallowed by `build()` and simply vanishes from the wall — the failure mode
    with no error anywhere, which is the one this board exists to avoid.
    """
    now = datetime.datetime.now()
    broke = []
    # Containers have no builder of their own — a custom tile IS its cards,
    # and `_build_tile` assembles it. The thing this scenario guards (a type
    # declaring an option its builder chokes on) applies to the cards.
    for w in home_board.WIDGETS:
        if w.get('container'):
            continue
        cfg = {}
        for o in w.get('options') or []:
            if o['type'] == 'int':
                cfg[o['key']] = o.get('max') or 3
            elif o['type'] == 'bool':
                cfg[o['key']] = not bool(o.get('default'))
            elif o['type'] == 'choice':
                cfg[o['key']] = o['choices'][-1]['value']
            elif o['type'] in ('select', 'entity'):
                cfg[o['key']] = (['no.such_entity'] if o.get('multi')
                                 else 'no.such_entity')
        try:
            home_board._BUILDERS[w['key']](
                now, runs=[], sched={}, settings={}, config=cfg,
                kid_digest_fn=lambda: {'kids': {}})
        except Exception as e:
            broke.append(f"{w['key']}: {type(e).__name__}: {e}")
    check(not broke,
          "these builders raised on their own declared options, so the tile "
          "would silently disappear from the board:\n    " + "\n    ".join(broke))


def scenario_a_configured_tile_is_still_the_tile_it_was():
    """Every option's default has to reproduce the behaviour that shipped
    before it existed. A tile that quietly shows six rows where it used to show
    five is a redesign of every board in the wild, delivered as a bug fix."""
    was = {'chores': 6, 'routines': 6, 'occasions': 3, 'errands': 5,
           'tasks': 6, 'moments': 6, 'trips': 4, 'weather': 5, 'shopping': 12}
    for type_, expected in was.items():
        opts = {o['key']: o for w in home_board.WIDGETS if w['key'] == type_
                for o in w['options']}
        opt = opts.get('count') or opts.get('days') or opts.get('items')
        check(opt is not None, f"{type_} lost the option that caps its rows")
        check(opt['default'] == expected,
              f"{type_}'s row cap now defaults to {opt['default']}, but the "
              f"tile has always shown {expected} — changing it here silently "
              f"redesigns every board that never configured this tile")


def scenario_every_type_can_at_least_be_named():
    """A board with three of the same tile is unreadable if all three are
    called the same thing, so `title` is offered on every type — appended in
    catalog() rather than declared fifteen times."""
    for w in home_board.catalog()['widgets']:
        keys = [o['key'] for o in w.get('options') or []]
        check('title' in keys, f"{w['key']} cannot be given a name")


def scenario_a_tile_is_named_for_the_page_it_summarises():
    """`label` is what the PICKER calls a tile, and it is the name of the page
    it summarises. It used to be the sentence the tile prints on the wall —
    which reads beautifully on a board and answers nothing in a list of
    nineteen, where the question is "which of these is the map".

    The sentences were not deleted, they moved to `heading`. Losing them would
    have been a silent redesign of every board in the wild.
    """
    by_key = {w['key']: w for w in home_board.WIDGETS}
    for key, name in (('drives', 'Driving schedule'), ('calendar', 'Calendar'),
                      ('map', 'Map'), ('meals', 'Meals'), ('shopping', 'Lists'),
                      ('chores', 'Chores'), ('routines', 'Routines'),
                      ('moments', 'Moments'), ('ha', 'Entities'),
                      ('ha_image', 'Camera or image'),
                      ('ha_dashboard', 'Dashboard'), ('ha_card', 'Card')):
        check(by_key[key]['label'] == name,
              f"{key} is called {by_key[key]['label']!r} in the picker, "
              f"expected {name!r}")
    for key, said in (('drives', 'The rest of the day'),
                      ('map', 'Where everyone is'),
                      ('meals', "Tonight's plate"),
                      ('calendar', "What's coming")):
        check(by_key[key].get('heading') == said,
              f"{key} lost the sentence it prints on the wall: "
              f"{by_key[key].get('heading')!r}")


def scenario_the_wall_says_the_title_and_blank_means_blank():
    """Since v2.210 the wall prints the TYPED title and nothing else — the
    type's wall sentence stopped being a fallback (it could never be removed)
    and became a v<3 migration backfill instead. A tile from a URL override
    goes through no migration, so untitled there means blank."""
    # The calendar rather than the map: the map needs Home Assistant to have
    # anything to say, and a tile that returns nothing has no label to check.
    board = home_board.build('[{"type": "calendar"}]')
    check(board['tiles'] and board['tiles'][0]['label'] == '',
          f"an untitled tile still prints a fallback: {board['tiles'][0]['label']!r}")
    board = home_board.build('[{"type": "calendar", "config": {"title": "Emma"}}]')
    check(board['tiles'][0]['label'] == 'Emma',
          f"a configured title was not printed: {board['tiles'][0]['label']!r}")
    # The wall sentences still exist — they are what the migration writes
    # into a v<3 board's title fields, so they must stay sensible.
    shopping = next(w for w in home_board.WIDGETS if w['key'] == 'shopping')
    check(shopping.get('heading', shopping['label']) == 'Lists',
          "the lists tile's backfill is something other than its own name")


def scenario_the_picker_separates_home_assistant_from_the_household():
    """The Add-tile picker groups on `requires`, which the catalog already sets
    for the HA tiles. A list written in the template would be a second place to
    forget, and the way it would fail is a new HA tile filed silently under the
    family's own."""
    cat = home_board.catalog()
    ha = [w['key'] for w in cat['widgets'] if w.get('requires')]
    check(set(ha) == {'ha', 'ha_image', 'ha_dashboard', 'ha_card'},
          f"the Home Assistant group is wrong: {ha}")
    for w in cat['widgets']:
        check(w.get('blurb'), f"{w['key']} has no blurb, so the picker row is "
                              f"a name with nothing under it")


def scenario_a_title_in_the_config_names_the_tile():
    board = home_board.build(
        '[{"type": "calendar", "config": {"title": "Emma\'s week"}}]')
    tile = board['tiles'][0]
    check(tile['label'] == "Emma's week",
          f"the instance's own title lost to the catalog's: {tile['label']!r}")


# --- the builders honour what they are given -------------------------------

def scenario_the_calendar_tile_reads_its_own_day_count():
    """Not the household setting — the instance's. Two calendar tiles wanting
    three days and a fortnight is the case the arc exists for.

    Since v2.207 the agenda is a component mount, so the day count rides in
    the mount config for the component to honour, rather than in how many day
    cards the payload happens to hold."""
    short = home_board.build('[{"type": "calendar", "config": {"days": 2}}]')
    long_ = home_board.build('[{"type": "calendar", "config": {"days": 9}}]')
    for board, n in ((short, 2), (long_, 9)):
        data = board['tiles'][0]['data']
        check((data.get('grid') or {}).get('days') == n,
              f"a {n}-day tile did not say so: {data}")


def scenario_a_blank_day_count_still_follows_the_board():
    """`days` defaults to null, not to a number, so a tile nobody has
    configured tracks `panel_agenda_days` — including when the household
    changes it later."""
    opt = next(o for w in home_board.WIDGETS if w['key'] == 'calendar'
               for o in w['options'] if o['key'] == 'days')
    check(opt['default'] is None,
          "the calendar's day count has a literal default, so a tile pinned to "
          "it silently stops following the board setting")


def scenario_the_views_are_different_shapes_not_the_same_one():
    """Since v2.207 the agenda is the COMPONENT's view — the payload carries a
    mount config, not day cards — while the list is still built here, because
    one line per event for a narrow tile is genuinely a different drawing."""
    agenda = home_board.build('[{"type": "calendar", "config": {"view": "agenda"}}]')
    listed = home_board.build('[{"type": "calendar", "config": {"view": "list"}}]')
    a, l = agenda['tiles'][0]['data'], listed['tiles'][0]['data']
    check((a.get('grid') or {}).get('view') == 'agenda',
          f"the agenda view is not a component mount: {a.keys()}")
    if not l.get('empty'):
        check(l.get('view') == 'list' and 'rows' in l,
              f"the list view is not a list: {l.keys()}")


def scenario_a_driving_tile_asked_for_a_week_draws_a_week_of_timelines():
    """This was got wrong once and the wrong version shipped for a version.

    `renderSchedule` seeds its day map from currentStartDate..currentEndDate
    and then loops `sortedDates.forEach`, drawing one COMPLETE timeline section
    per day — which is exactly how the Schedule page shows a week in kiosk
    mode. Multi-day was never a missing feature; the tile was narrowing it away
    by passing `dateFilter`, which is the option that collapses that loop back
    to a single day.

    So a multi-day timeline tile has to send the RANGE, and the client has to
    withhold `dateFilter`. Both halves are asserted, because either one alone
    silently renders today and looks like the setting doing nothing."""
    # The slice directly, so this holds on an empty household too: a household
    # with no drivers has no drives tile at all, and that is a different rule.
    day = datetime.date(2026, 9, 7)
    sched = {'events': [
        {'id': 'a', 'start': f'{day}T09:00:00', 'end': f'{day}T10:00:00'},
        {'id': 'b', 'start': f'{day + datetime.timedelta(days=3)}T09:00:00',
         'end': f'{day + datetime.timedelta(days=3)}T10:00:00'},
        {'id': 'far', 'start': f'{day + datetime.timedelta(days=30)}T09:00:00',
         'end': f'{day + datetime.timedelta(days=30)}T10:00:00'},
    ]}
    one = home_board._schedule_slice(day, sched, days=1)
    five = home_board._schedule_slice(day, sched, days=5)
    check([e['id'] for e in one['events']] == ['a'],
          f"a one-day slice stopped being one day: {one['events']}")
    check([e['id'] for e in five['events']] == ['a', 'b'],
          f"a five-day slice did not span five days (and must still exclude "
          f"the one a month out): {[e['id'] for e in five['events']]}")

    tpl = tpl_source.read('home.html')
    block = tpl[tpl.index('renderTimelineInto(tile)'):]
    block = block[:block.index('scrollTimelineToNext(tile.id')]
    check('tile.data.start_date' in block and 'tile.data.end_date' in block,
          "the client no longer sets the timeline's date RANGE, so every "
          "driving tile is one day again whatever it was configured for")
    check('> 1 ? null :' in block,
          "the client passes dateFilter unconditionally again — that is the "
          "option that narrows renderSchedule back to a single day, and it is "
          "exactly what made multi-day look impossible")


def scenario_the_compact_list_is_a_width_answer_not_a_span_answer():
    """The list view is for a tile too narrow to read an hour rail in. It is
    NOT the multi-day mechanism — that is the timeline's own loop — and the
    day count has to work in both."""
    board = home_board.build('[{"type": "drives", "config": {"view": "list", "days": 3}}]')
    data = board['tiles'][0]['data']
    check(data.get('view') == 'list' or data.get('empty'),
          f"a list-view driving tile still returned a timeline: {data.keys()}")
    days_opt = next(o for w in home_board.WIDGETS if w['key'] == 'drives'
                    for o in w['options'] if o['key'] == 'days')
    check('list' not in (days_opt.get('help') or '').lower(),
          "the drives day count still claims to be list-view only, which is "
          "the mistake this scenario exists to keep out")


def scenario_an_empty_multi_select_means_everyone():
    """On every tile that takes one. A filter that shows nothing until you have
    ticked somebody reads as broken rather than as unconfigured."""
    check(home_board._cfg_ids({}, 'members') == [], "absent is not empty")
    check(home_board._cfg_ids({'members': []}, 'members') == [],
          "an empty list is not empty")
    check(home_board._cfg_ids({'members': 'nope'}, 'members') == [],
          "a non-list value should be ignored, not crash the tile")


def scenario_a_deleted_list_says_so_rather_than_showing_all_of_them():
    """A tile pinned to a list somebody later deleted. Falling back to every
    list would look like the setting doing nothing; hiding the tile would look
    like the board being broken."""
    data = home_board._tile_shopping(None, config={'list': 'gone-for-good'})
    # No lists at all -> the feature is unused and the tile is None; that is
    # the pre-existing rule and not what this is about.
    if data is not None:
        check(data.get('empty') == "That list is gone.",
              f"a pinned-but-deleted list rendered as {data}")


def scenario_the_prefetch_reaches_as_far_as_the_deepest_tile():
    """Each day is merged in from its own cache row. A tile configured for a
    fortnight against a five-day prefetch renders nine empty days and looks
    like a quiet calendar rather than like a board that did not read far
    enough."""
    src = open(os.path.join(os.path.dirname(TPL), 'services', 'home_board.py'),
               encoding='utf-8').read()
    block = src[src.index('sched = storage.get_cached_schedule() or {}'):]
    block = block[:block.index('runs = todays_runs')]
    check('max(' in block and "'days'" in block,
          "the board still prefetches to the household setting rather than to "
          "the deepest tile's own day count")


# --- the editor writes what the builder reads ------------------------------

HARNESS = r"""
globalThis.window = {
  location: { search: '', pathname: '/home' },
  matchMedia: function () { return { matches: false }; }
};
globalThis.document = {
  documentElement: { getAttribute: function () { return 'dark'; } },
  getElementById: function () { return null; },
  addEventListener: function () {}
};
globalThis.setInterval = function () { return 0; };
"""

PROBE = r"""
const b = homeBoard();
b.catalog = __CATALOG__;
// A board is a PAGE now, so the editor is seeded with one rather than with a
// bare widget list. Everything below still exercises the same helpers; they
// simply address the page being edited instead of a single household board.
b.draft.panel_pages = [{
  slug: 'home', name: 'Home', icon: 'H',
  widgets: [], spans: {}, columns: 12, row_height: 240, background: '',
}];
b.pageIndex = 0;

const opt = (type, key) =>
  b.optionsFor(type).find(o => o.key === key);

// Two calendars, added the way the palette adds them.
b.addInstance('calendar');
b.addInstance('calendar');
const [one, two] = b.page().widgets;

// Set the second to a list of one person's next 3 days.
b.setCfg(two, opt('calendar', 'view'), 'list');
b.setCfg(two, opt('calendar', 'days'), '3');
b.toggleCfgId(two, opt('calendar', 'members'), 'member-a');
b.setCfg(two, opt('calendar', 'title'), 'Emma');

// Then put one of them back to exactly the default.
const drives = (b.addInstance('drives'), b.page().widgets[2]);
b.setCfg(drives, opt('drives', 'errands'), false);
b.setCfg(drives, opt('drives', 'errands'), true);   // back to the default

// And a number typed out of range.
b.setCfg(one, opt('calendar', 'days'), '99');

console.log(JSON.stringify({
  ids: b.page().widgets.map(w => w.id),
  untouched: one.config,
  configured: two.config,
  backToDefault: drives.config,
  clamped: one.config.days,
  labels: b.page().widgets.map(w => b.instanceLabel(w)),
  counts: { calendar: b.countOfType('calendar'), map: b.countOfType('map') },
  // A tile with no options must not offer a gear.
  gearless: b.optionsFor('intake').filter(o => o.key !== 'title').length,
  // Removing an instance takes its size with it.
  spansAfterRemove: (function () {
    b.page().spans = { 'calendar-2': { cols: 6 } };
    b.removeInstance(1);
    return b.page().spans;
  })(),
}));
"""


def _run_editor():
    node = shutil.which('node')
    if not node:
        print('  SKIP  node not installed')
        return None
    src = tpl_source.read('home.html')
    body = next(b for b in re.findall(r'<script>(.*?)</script>', src, re.S)
                if 'function homeBoard()' in b)
    probe = PROBE.replace('__CATALOG__', json.dumps(home_board.catalog()))
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, 'run.mjs')
        with open(f, 'w', encoding='utf-8') as fh:
            fh.write(HARNESS + body + probe)
        proc = subprocess.run([node, f], capture_output=True, text=True)
    check(proc.returncode == 0, f"the board script threw:\n{proc.stderr[-2000:]}")
    return json.loads(proc.stdout.strip().splitlines()[-1])


def scenario_the_editor_gives_two_of_a_kind_separate_identities():
    got = _run_editor()
    if got is None:
        return
    check(got['ids'][:2] == ['calendar', 'calendar-2'],
          f"two calendar tiles did not get distinct ids: {got['ids']}")
    # Counted before the removal below — object literal properties evaluate in
    # order, and the palette's badge is what this is standing in for.
    check(got['counts']['calendar'] == 2 and got['counts']['map'] == 0,
          f"the palette's per-type count is wrong: {got['counts']}")
    check(got['labels'][0] != got['labels'][1],
          f"two rows of the same type read identically: {got['labels']}")


def scenario_an_untouched_tile_stores_nothing():
    """Opening an options panel and closing it must not write out a config.
    Stored numbers stop tracking the board default the moment they exist, so a
    tile nobody configured has to stay genuinely unconfigured."""
    got = _run_editor()
    if got is None:
        return
    check(got['backToDefault'] == {},
          f"a value set back to its default is still stored: {got['backToDefault']}")


def scenario_the_editor_writes_the_keys_the_builder_reads():
    got = _run_editor()
    if got is None:
        return
    cfg = got['configured']
    check(cfg.get('view') == 'list', f"view not written: {cfg}")
    check(cfg.get('days') == 3, f"days not written as a number: {cfg}")
    check(cfg.get('members') == ['member-a'], f"members not written: {cfg}")
    check(cfg.get('title') == 'Emma', f"title not written: {cfg}")
    # The builder side of the same contract.
    board = home_board.build(json.dumps([{'type': 'calendar', 'config': cfg}]))
    check(board['tiles'][0]['label'] == 'Emma',
          "the editor wrote a title the builder did not use")


def scenario_a_number_typed_out_of_range_is_clamped_before_it_is_stored():
    got = _run_editor()
    if got is None:
        return
    check(got['clamped'] == 14,
          f"99 days was stored as {got['clamped']} — the builder clamps too, "
          f"but a stored 99 makes the editor disagree with the board")


def scenario_removing_an_instance_takes_its_size_with_it():
    got = _run_editor()
    if got is None:
        return
    check(got['spansAfterRemove'] == {},
          f"a removed tile left its size behind: {got['spansAfterRemove']} — "
          f"the next instance given that id would inherit it")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} board-instance scenarios passed")
