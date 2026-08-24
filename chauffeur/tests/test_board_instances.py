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
                check(o.get('source') in ('ha_entities', 'ha_cameras', 'ha_players'),
                      f"{w['key']}.{o['key']} draws from '{o.get('source')}', "
                      f"which ha_options() does not supply")
                # And the list it names is really in there, in BOTH shapes the
                # function returns — the degraded one is the shape a household
                # without Home Assistant actually gets, and a picker reading an
                # absent key there is undefined, which draws as nothing rather
                # than as "no Home Assistant".
                key = o['source'].replace('ha_', '')
                check(key in home_board.ha_options(),
                      f"ha_options() has no '{key}' for {w['key']}.{o['key']}")


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
           'tasks': 6, 'moments': 6, 'trips': 4, 'weather': 5, 'lists': 12}
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
                      ('map', 'Map'), ('meals', 'Meals'), ('lists', 'Lists'),
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
    shopping = next(w for w in home_board.WIDGETS if w['key'] == 'lists')
    check(shopping.get('heading', shopping['label']) == 'Lists',
          "the lists tile's backfill is something other than its own name")


def scenario_the_picker_separates_home_assistant_from_the_household():
    """The Add-tile picker groups on `requires`, which the catalog already sets
    for the HA tiles. A list written in the template would be a second place to
    forget, and the way it would fail is a new HA tile filed silently under the
    family's own."""
    cat = home_board.catalog()
    ha = [w['key'] for w in cat['widgets'] if w.get('requires')]
    # Music is in this group for the same reason the other four are, not as an
    # exception to it: without Home Assistant there is no Music Assistant to
    # reach, so the palette says so rather than letting somebody add a card
    # that could never draw.
    check(set(ha) == {'ha', 'ha_image', 'ha_dashboard', 'ha_card', 'music'},
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


def scenario_the_boards_tab_is_where_the_other_tabs_are():
    """A tab pane nested inside something hidden is a tab that opens on
    nothing, and it fails SILENTLY — the button highlights, the page stays
    blank, and there is no error to go looking for.

    The Boards pane first shipped inside the Mapbox sync modal, because it was
    inserted at the last matching run of closing tags before the page's script
    rather than at the end of the pane it belongs beside.

    This used to compare NESTING DEPTH against the other panes, which was only
    ever a proxy — and a proxy that quietly expired. Boards sits one level
    shallower than General/People/Rules, and the check passed because the
    Themes pane happened to sit at that same shallow level; when Themes was
    removed in v2.353.0 the assertion started failing on markup that renders
    perfectly (verified in a browser — the pane paints ~2300px tall). A test
    that fails when an unrelated tab is deleted is testing the wrong thing.

    So it asserts the ACTUAL property instead: no ancestor of the Boards pane
    hides itself. That is what "buried in the Mapbox modal" meant, it is what
    makes the tab open on nothing, and it does not care how many wrappers
    anybody nests a pane inside.
    """
    import re
    # Include-expanded: the pane itself lives in components/boards_admin.html,
    # and where it ENDS UP is the whole question.
    cfg = tpl_source.read('config.html')
    stack, ancestors, found = [], None, False
    for m in re.finditer(r'<div\b[^>]*?>|</div>', cfg, re.S):
        tag = m.group(0)
        if tag.startswith('</'):
            if stack:
                stack.pop()
            continue
        pane = re.search(r"""x-show="activeTab === '(\w+)'\"""", tag)
        if pane and pane.group(1) == 'boards' and not found:
            found, ancestors = True, list(stack)
        if not tag.rstrip().endswith('/>'):
            stack.append(tag)
    check(found, "there is no Boards tab pane at all")
    # An ancestor that hides itself hides the pane with it. `x-show` on a MODAL
    # is the shape that shipped; `hidden` is the same thing spelled in CSS. The
    # pane's own x-show is not in this list — `stack` holds what was already
    # open when it was reached.
    # `(?<![-\w])hidden` rather than `\bhidden\b`: Tailwind's `overflow-hidden`
    # is on half the wrappers on this page and is not a visibility class.
    buried = [a[:90] for a in ancestors
              if re.search(r'x-show=|class="[^"]*(?<![-\w])hidden(?![-\w])', a)]
    check(not buried,
          f"the Boards pane is inside something that hides itself: {buried} — "
          f"a tab that opens on a blank page and says nothing about why, "
          f"which is exactly how it first shipped")

    # And it must be able to SEE `activeTab`, which lives on the body scope.
    check('x-data="boardsAdmin()"' in cfg or 'boardsAdmin()' in cfg,
          "the Boards pane has no component behind it")


def scenario_the_board_is_configured_over_the_board():
    """Name, icon, address, picture and the grid, in an overlay over the board
    they describe — a column count only means something next to the tiles it is
    dividing. And nothing of it is left in the form, which is being dismantled
    rather than reorganised."""
    with open(os.path.join(TPL, 'home.html'), encoding='utf-8') as fh:
        tpl = fh.read()
    ov = tpl[tpl.index("<!-- ── The BOARD's settings, over the board."):]
    ov = ov[:ov.index('<!-- The card picker')]
    for needs, why in (("setPageField('name'", 'name'),
                       ("setPageField('icon'", 'icon'),
                       ('setPageSlug(', 'address'),
                       ("setPageField('background'", 'picture'),
                       ("setPageField('columns'", 'columns'),
                       ("setPageField('row_height'", 'row height'),
                       ("setPageField('gap'", 'gutter'),
                       ('removePage()', 'delete/reset')):
        check(needs in ov, f"the board settings overlay cannot set {why}")

    # And there is no form left to keep any of it. `#panel-setup` is gone
    # entirely (v2.232.0) rather than emptied, which is the strongest form of
    # "nothing was left behind": there is nowhere for it to be left.
    check('id="panel-setup"' not in tpl,
          "the panel setup block is back — every board setting lives on the "
          "board or on the Boards tab now, and a form under the board is a "
          "second place to do all of it")

    # A new board is NAMED first and slugged from that name. This household
    # has a board called "House Monitor" living at /board/new-board, because
    # the slug was derived from a placeholder nobody chose.
    add = tpl[tpl.index('async addPage()'):]
    add = add[:add.index('\n                },')]
    check('promptInput(' in add and 'freshSlug(fresh.name)' in add,
          "a new board still takes its address from a placeholder name")


def scenario_adding_a_tile_shows_the_tile():
    """Add and remove are not gated on Save.

    The grid draws SERVER-built tiles ordered by the draft, so a tile the draft
    had just gained had nothing to draw and one it had just lost carried on
    drawing — and both only resolved when you scrolled down and saved. That
    made Save the button that showed you what you had already done, which is an
    editor admitting it is really a form.
    """
    import main
    from services import storage
    # Chrome, deliberately: rule 1 drops an unconfigured feature's tile, and
    # this scenario is about the preview honouring the DRAFT, not about which
    # features happen to be set up in a test environment.
    got = main.home_board_preview(main.BoardPreviewRequest(
        widgets=[{'id': 'heading', 'type': 'heading',
                  'config': {'title': 'Ours'}},
                 {'id': 'clock', 'type': 'clock', 'config': {}}],
        page='home'))
    check([t['type'] for t in got['tiles']] == ['heading', 'clock'],
          f"the preview is not the draft it was given: {got['tiles']}")
    # It BUILDS, so the new tile arrives drawn rather than as a placeholder.
    check(all('data' in t or t.get('cards') for t in got['tiles']),
          "the preview returns tiles with nothing in them")
    # And it writes nothing — Cancel has to be able to put the draft back.
    before = json.dumps(storage.get_settings().get('panel_pages'))
    main.home_board_preview(main.BoardPreviewRequest(widgets=[], page='home'))
    check(json.dumps(storage.get_settings().get('panel_pages')) == before,
          "previewing a draft wrote it to settings")

    # The editor has to actually USE it, and has to redraw after add/remove.
    with open(os.path.join(TPL, 'home.html'), encoding='utf-8') as fh:
        tpl = fh.read()
    check('api/home_board/preview' in tpl,
          "the editor still builds its board from what is SAVED while editing")
    for fn in ('async addInstance(', 'async removeInstance(',
               'async addPickedCard('):
        body = tpl[tpl.index(fn):]
        body = body[:body.index('\n                },')]
        check('this.load()' in body,
              f"{fn.strip()} does not redraw, so its change waits for Save")


def scenario_the_tile_is_edited_on_the_tile():
    """A tile's settings belong on the tile, not in a row of a list below the
    wall — the same argument dragging already won for size.

    The bar this has to clear is that the overlay carries EVERYTHING the row
    does. Deleting the list is the next step, and a list deleted before its
    replacement is complete is functionality dropped by accident.
    """
    # The RAW file, not tpl_source: this scenario is about how the page is
    # ASSEMBLED, and tpl_source inlines each template only once, so an
    # include's contents disappear at its second use — which is exactly the
    # two-surfaces-one-partial arrangement being asserted here.
    with open(os.path.join(TPL, 'home.html'), encoding='utf-8') as fh:
        tpl = fh.read()
    check('openTileEditor(' in tpl and 'tile-edit' in tpl,
          "no way to open a tile's settings from the tile")
    ov = tpl[tpl.index("<!-- ── A TILE's settings"):]
    ov = ov[:ov.index('<!-- ── `#panel-setup` was here')]
    for needs, why in (
            ("spanOf(tileEd().id, 'cols')", 'width'),
            ("spanOf(tileEd().id, 'rows')", 'height'),
            ("setSpan(tileEd().id, 'auto'", 'fit'),
            ("setSpan(tileEd().id, 'fill'", 'fill'),
            ('isHidden(tileEd())', 'hidden'),
            ('isRequired(tileEd())', 'always-show'),
            ('removeEditingTile()', 'remove')):
        check(needs in ov,
              f"the tile overlay cannot set {why}, so it is not yet a "
              f"replacement for the row in the list")
    # The type's own options, through the SAME declaration renderer every
    # other surface uses rather than a form written twice.
    check("OW = 'tileEd()'" in ov and 'board_options.html' in ov,
          "the tile overlay hand-rolls its options instead of rendering the "
          "type's declaration through the shared renderer")

    # And ONE palette, included in BOTH places — over the board while
    # arranging, and in the form below it. Two copies of a list whose rows
    # carry availability rules and per-type counts is two lists that drift,
    # and the one that drifts is always the one you are not looking at.
    check(os.path.exists(os.path.join(TPL, 'components', 'board_picker.html')),
          "the tile palette is not a shared partial")
    used = tpl.count("{% include 'components/board_picker.html' %}")
    check(used == 2,
          f"the palette is included {used} times, not twice — for a TILE over "
          f"the board and for a CARD over a container tile. The copy in the "
          f"setup form is gone: that block is being dismantled, and a control "
          f"left behind in it is a second place to do a job the board does")
    # And nowhere else: the setup form that used to carry a third copy is
    # gone entirely (v2.232.0).
    check('id="panel-setup"' not in tpl,
          "the panel setup block is back, and with it a third tile palette")
    # Parameterised by Jinja at compile time, the same way board_options.html
    # serves three contexts — a runtime flag would make one partial that
    # branches instead of one partial used three ways.
    for ctx in ("ADD = 'addInstance'", "ADD = 'addPickedCard'"):
        check(ctx in tpl, f"the palette has no {ctx} context")


def scenario_a_board_can_be_copied_handed_over_and_pasted_back():
    """The three ways a board moves, and all three exist because the shipped
    boards are read-only: Duplicate is how a household changes one, and export
    is how WE author one — the add-on's filesystem is rebuilt on every update
    and is not the repo, so the instance can only ever hand the board over."""
    got = _run_editor()
    if got is None:
        return
    p = got['porting']
    check(p['copyName'] == 'Chores copy', f"the copy is unnamed: {p['copyName']}")
    check(p['copySlug'] not in ('chores', 'home'),
          f"the copy took a slug the server drops: {p['copySlug']}")
    check(p['copyKeptRequire'],
          "the copy lost the flags the board it copied was carrying")
    check(p['sourceUntouched'],
          "editing the copy edited the shipped board it came from — that "
          "object is module state serving every other page on this install")
    # The slug guard. A household naming a board `Chores` used to get slug
    # `chores`, which since v2.229.0 the server drops: the board would simply
    # disappear on save, which is the worst way to report a name collision.
    check(p['collide'] not in ('chores',),
          f"a board named Chores minted the shipped slug: {p['collide']}")
    check(p['homeCollide'] != 'home',
          f"a board named Home took the reserved slug: {p['homeCollide']}")
    check(p['typed'] != 'map',
          f"a shipped slug typed by hand was accepted: {p['typed']}")
    # Out and back in, losslessly.
    check(p['roundTrip'] == ['drives'],
          f"the export is not the board: {p['roundTrip']}")
    check(p['backTypes'] == ['drives'],
          f"the import lost the tiles: {p['backTypes']}")
    check(p['backSlug'] != 'home',
          f"an imported board claimed the reserved home slug: {p['backSlug']}")
    check(p['rejected'], "a JSON array was accepted as a board")


def scenario_a_parked_tile_costs_the_wall_nothing_but_comes_back():
    """Hiding is a person's decision, so it must be reversible — which means
    the tile has to still BE somewhere. It ships as a stub: no builder runs, so
    a parked tile cannot cost a query or break the payload the other cards are
    waiting on, and the editor can still draw it and hand it back.

    The line this must not cross: rule 1 hides a feature nobody set up, and
    that is the system acting invisibly. This is the opposite kind of thing.
    """
    board = home_board.build(
        '[{"type": "map", "config": {}, "hidden": true},'
        ' {"type": "calendar", "config": {}}]')
    by = {t['type']: t for t in board['tiles']}
    check('map' in by, "a parked tile vanished, so nobody can un-park it")
    check(by['map'].get('hidden') is True,
          f"the parked tile does not say it is parked: {by['map']}")
    check(by['map'].get('cards') == [],
          f"a parked tile built its cards anyway: {by['map']}")
    check(by['calendar'].get('hidden') is not True,
          "hiding one tile parked its neighbour")

    # A builder that would blow up proves nothing ran.
    boom = home_board.build('[{"type": "map", "config": {}, "hidden": true}]',
                            now=None)
    check(boom['tiles'][0].get('hidden') is True,
          "the parked tile was built rather than stubbed")

    # And it survives the round trip through the page normaliser, which is
    # where `require` was being silently dropped.
    page = home_board._page_from(
        {'slug': 'x', 'name': 'X', 'v': 5,
         'widgets': [{'id': 'map', 'type': 'map', 'config': {}, 'hidden': True}]},
        {}, set())
    check(page['widgets'][0].get('hidden') is True,
          f"normalize_instances dropped `hidden`: {page['widgets'][0]}")


def scenario_the_day_count_belongs_to_the_card_not_the_board():
    """This used to assert the opposite, and the opposite was a leftover.

    `days` defaulted to null so an unconfigured tile tracked a board-wide
    `panel_agenda_days` setting. That was right when a board had one calendar.
    It stopped being right when tiles became instances — two calendars on one
    board, one showing three days and one a fortnight, is the whole point — and
    a board-wide number is then a second place to set what each card owns.
    Removed in v2.229.2; the option carries a literal default now.
    """
    opt = next(o for w in home_board.WIDGETS if w['key'] == 'calendar'
               for o in w['options'] if o['key'] == 'days')
    check(opt['default'] == home_board.AGENDA_DAYS,
          f"the calendar's day count has no literal default ({opt['default']!r}), "
          f"so it is still reaching for a board-wide setting")
    check(not hasattr(home_board, 'agenda_days'),
          "the board-wide day count resolver is back")
    # And the point of the removal: two calendars on one board, disagreeing.
    board = home_board.build(
        '[{"type": "calendar", "config": {"days": 3}},'
        ' {"type": "calendar", "config": {"days": 14}}]')
    got = [(t['data'].get('grid') or {}).get('days') for t in board['tiles']]
    check(got == [3, 14],
          f"two calendars on one board cannot disagree about how far to look: {got}")


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
// Lives in components/control_center.html, which home.html includes and this
// harness deliberately does not: the point of running the board script alone
// is that it has no page around it. Stubbed rather than guarded in the app,
// because in a browser it is always there.
globalThis.showGlobalAlert = function () {};
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

// ── `require` — "this board is ABOUT this tile", so an empty one says so
// instead of vanishing. Only the shipped boards set it, and it has to survive
// BOTH of the editor's normalisers: loadSetup runs every page through
// toInstances before anybody edits, and _cleanPages is the shape that gets
// saved. Dropping it in either place takes the empty state off all ten shipped
// boards, and a board only reveals the loss on the day it has nothing to show.
const normalised = b.toInstances([
  { id: 'chores_lanes', type: 'chores_lanes', config: {}, require: true },
  { id: 'calendar', type: 'calendar', config: {}, hidden: true },
  { id: 'map', type: 'map', config: {} },
]);
b.draft.panel_pages.push({
  slug: 'chores', name: 'Chores', icon: 'C', v: 5, widgets: normalised,
  spans: {}, columns: 12, row_height: 240, gap: 16, background: '',
});
const savedRequire = b._cleanPages()
  .find(p => p.slug === 'chores').widgets.map(w => w.require || false);

console.log(JSON.stringify({
  requireLoaded: normalised.map(w => w.require || false),
  requireSaved: savedRequire,
  hiddenLoaded: normalised.map(w => w.hidden || false),
  hiddenSaved: b._cleanPages().find(p => p.slug === 'chores')
      .widgets.map(w => w.hidden || false),
  // Parked and un-parked, as the checkbox drives it. Absent rather than
  // false when off: a board carrying `hidden: false` on every tile is a
  // board describing decisions nobody made.
  hideToggle: (function () {
    const w = { id: 'x', type: 'map', config: {} };
    b.setHidden(w, true);
    const on = w.hidden === true;
    b.setHidden(w, false);
    return [on, Object.prototype.hasOwnProperty.call(w, 'hidden')];
  })(),
  requireToggle: (function () {
    const w = { id: 'y', type: 'map', config: {} };
    b.setRequired(w, true);
    const on = w.require === true;
    b.setRequired(w, false);
    return [on, Object.prototype.hasOwnProperty.call(w, 'require')];
  })(),
  // Only types with an empty state to say, and never chrome.
  requirable: ['map', 'heading', 'custom', 'chores_lanes']
      .map(t => b.canRequire(t)),

  // ── Duplicate / export / import.
  porting: (function () {
    // This block rearranges the whole draft, and the keys after it in this
    // object are still reading the one the scenarios above set up. Snapshot
    // and put it back — an earlier version of this quietly broke the
    // span-cleanup scenario from three keys away.
    const kept = { pages: b.draft.panel_pages, at: b.pageIndex,
                   cat: b.catalog, ship: b.shipped };
    b.catalog = Object.assign({}, b.catalog, {
      builtin_pages: ['chores', 'map', 'errands'] });
    b.draft.panel_pages = [
      { slug: 'home', name: 'Home', icon: 'H', v: 5, columns: 12,
        row_height: 240, gap: 16, background: '', spans: {},
        widgets: [{ id: 'drives', type: 'drives', config: {} }] },
    ];
    b.pageIndex = 0;
    b.shipped = [{ slug: 'chores', name: 'Chores', icon: 'C', v: 5,
      columns: 12, row_height: 240, gap: 16, background: 'ours',
      spans: { chores_lanes: { cols: 12 } },
      widgets: [{ id: 'chores_lanes', type: 'chores_lanes', config: {},
                  require: true }] }];

    // Copying a SHIPPED board must not hand out the shipped object.
    b.duplicateShipped('chores');
    const copy = b.draft.panel_pages[b.pageIndex];
    copy.widgets[0].config.title = 'mine';
    copy.spans.chores_lanes.cols = 3;
    const sourceUntouched = b.shipped[0].widgets[0].config.title === undefined
      && b.shipped[0].spans.chores_lanes.cols === 12;

    // A name a household might reasonably pick, whose slug IS a shipped
    // board's. The server drops those, so the editor must not mint one.
    b.draft.panel_pages.push({ slug: '', name: 'Chores', v: 5, widgets: [],
                               spans: {}, columns: 12, row_height: 240,
                               gap: 16, background: '' });
    const collide = b.freshSlug('Chores');
    const homeCollide = b.freshSlug('Home');

    // Typed by hand into the address field.
    b.pageIndex = b.draft.panel_pages.length - 1;
    b.setPageSlug('map');
    const typed = b.page().slug;

    // Out and back in.
    b.pageIndex = 0;
    b.exportPage();
    const text = b.exporting;
    b.importing = text;
    b.importPage();
    const back = b.draft.panel_pages[b.pageIndex];
    b.importing = '[1,2,3]';
    let rejected = true;
    const before = b.draft.panel_pages.length;
    b.importPage();
    rejected = b.draft.panel_pages.length === before;

    b.draft.panel_pages = kept.pages;
    b.pageIndex = kept.at;
    b.catalog = kept.cat;
    b.shipped = kept.ship;

    return {
      copyName: copy.name,
      copySlug: copy.slug,
      copyKeptRequire: copy.widgets[0].require === true,
      sourceUntouched: sourceUntouched,
      collide: collide,
      homeCollide: homeCollide,
      typed: typed,
      roundTrip: JSON.parse(text).widgets.map(w => w.type),
      backTypes: back.widgets.map(w => w.type),
      backSlug: back.slug,
      rejected: rejected,
    };
  })(),
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


def scenario_a_shipped_boards_empty_state_survives_the_editor():
    got = _run_editor()
    if got is None:
        return
    check(got['requireLoaded'] == [True, False, False],
          f"toInstances dropped `require`: {got['requireLoaded']} — merely "
          f"OPENING the editor strips every shipped board's empty state, so a "
          f"quiet Chores board goes blank instead of saying it is quiet")
    check(got['requireSaved'] == [True, False, False],
          f"_cleanPages dropped `require`: {got['requireSaved']} — the flag "
          f"survives loading but not saving, so the strip lands the first time "
          f"anybody nudges a tile")


def scenario_a_parked_tile_survives_the_editor_and_says_it_is_parked():
    """`hidden` is a person keeping a tile they are not ready to delete, and it
    goes through the same two normalisers `require` does — which dropped
    `require` silently and would have dropped this one the same way."""
    got = _run_editor()
    if got is None:
        return
    check(got['hiddenLoaded'] == [False, True, False],
          f"toInstances dropped `hidden`: {got['hiddenLoaded']} — opening the "
          f"editor un-parks every parked tile")
    check(got['hiddenSaved'] == [False, True, False],
          f"_cleanPages dropped `hidden`: {got['hiddenSaved']}")
    check(got['hideToggle'] == [True, False],
          f"hiding is not a clean on/off: {got['hideToggle']} — off must "
          f"REMOVE the key, not store `hidden: false` on every tile")
    check(got['requireToggle'] == [True, False],
          f"requiring is not a clean on/off: {got['requireToggle']}")
    # map has an empty state; heading is chrome; custom is a container.
    check(got['requirable'] == [True, False, False, True],
          f"the editor offers 'always show' on the wrong types: "
          f"{got['requirable']} for map/heading/custom/chores_lanes")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} board-instance scenarios passed")
