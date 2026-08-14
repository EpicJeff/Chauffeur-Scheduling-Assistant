"""Tiles hold cards. Both kinds of tile do.

The content a board shows used to be welded to the chrome around it: a chores
list existed only inside the tile called Chores, so there was no way to put one
anywhere else, or to put anything beside it. Splitting the two gives a CARD
(content, nothing else) and a TILE (a container with a grid, and optionally a
heading over it).

There are two tiles and they are the same tile:

  * BUILT-IN — `{id, type: 'chores', config}`, which is exactly what every
    board has always stored. It is a locked container holding one card of that
    type. **This is the load-bearing claim of the whole design: because the
    stored shape did not change, no board anywhere needed migrating, and the
    surface a household already knows still works.**
  * CUSTOM — `{id, type: 'custom', config: {title, cards: [...]}}`. Starts
    empty, takes any number of cards, lays them out on its own twelve columns.

What has to hold: a card is built by the type's own builder and by nothing
else; rule 1 (nothing to say, nothing drawn) survives the move one level down;
a card's id cannot collide with a tile's; a container cannot hold a container;
and one card throwing costs that card alone.

Run from chauffeur/:  python tests/test_board_cards.py
"""
import datetime
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('CHAUFFEUR_DATA_DIR',
                      tempfile.mkdtemp(prefix='chauffeur_cards_'))

from services import home_board  # noqa: E402

NOW = datetime.datetime(2026, 9, 7, 17, 30)


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


class _Spy:
    """Stands in for a card builder and records the config it was handed."""

    _UNSET = object()

    def __init__(self, payload=_UNSET):
        self.seen = []
        # `None` is a real answer here — it is how a builder says "nothing to
        # say" — so it cannot double as "no argument given".
        self.payload = {'ok': True} if payload is self._UNSET else payload

    def __call__(self, now, config=None, **_):
        self.seen.append(dict(config or {}))
        return self.payload


def _with_builders(mapping, fn):
    real = dict(home_board._BUILDERS)
    home_board._BUILDERS.update(mapping)
    try:
        return fn()
    finally:
        home_board._BUILDERS.clear()
        home_board._BUILDERS.update(real)


def _tile(inst):
    return home_board._build_tile(inst, NOW)


def _custom(cards, title='', iid='custom'):
    return _tile({'id': iid, 'type': 'custom',
                  'config': {'title': title, 'cards': cards}})


def scenario_a_built_in_tile_is_a_locked_container_of_one_card():
    """The claim that made this a refactor rather than a migration. A board
    stored `{'type': 'chores'}` before cards existed and stores exactly that
    now; the tile is assembled around it at build time."""
    spy = _Spy({'points': 12})
    got = _with_builders({'chores': spy}, lambda: _tile(
        {'id': 'chores', 'type': 'chores', 'config': {'count': 4}}))
    check(got['locked'] is True, "a built-in tile is not locked")
    check(len(got['cards']) == 1, f"a built-in tile holds {len(got['cards'])} cards")
    card = got['cards'][0]
    check(card['type'] == 'chores' and card['data'] == {'points': 12},
          f"the card is not the tile's own content: {card}")
    check(spy.seen[0] == {'count': 4},
          f"the tile's config did not reach its card: {spy.seen}")
    # Its one card fills the tile, and wears no size of its own — the tile is
    # the surface, and a built-in tile that could be half-width inside itself
    # would be a second place to set the same thing.
    check(card['cols'] == 12 and card['rows'] == 0,
          f"a built-in tile's card does not fill it: {card['cols']}x{card['rows']}")


def scenario_a_built_in_tiles_data_is_still_its_own():
    """Everything that reasoned about `tile.data` before cards existed is still
    reasoning correctly, because a built-in tile having exactly one card is not
    an implementation detail — it is what a built-in tile IS."""
    got = _with_builders({'chores': _Spy({'points': 12})}, lambda: _tile(
        {'id': 'chores', 'type': 'chores', 'config': {}}))
    check(got['data'] == {'points': 12},
          f"a built-in tile stopped carrying its own data: {got.get('data')}")


def scenario_a_tile_whose_only_card_is_quiet_is_not_a_tile():
    """Rule 1, moved down a level and still holding: an unconfigured feature
    reserves no space on the wall."""
    got = _with_builders({'chores': _Spy(None)}, lambda: _tile(
        {'id': 'chores', 'type': 'chores', 'config': {}}))
    check(got is None, f"a tile with nothing to say was still drawn: {got}")


def scenario_a_custom_tile_holds_several_cards_built_the_same_way():
    """The point of the split. Same catalog, same builders, same drawing — a
    chores card in a tile somebody assembled is the chores tile's content."""
    chores, weather = _Spy({'points': 3}), _Spy({'high': 71})
    got = _with_builders({'chores': chores, 'weather': weather}, lambda: _custom(
        [{'type': 'chores'}, {'type': 'weather'}], title='Mornings'))
    check(got['locked'] is False, "a custom tile is locked")
    check([c['type'] for c in got['cards']] == ['chores', 'weather'],
          f"the cards are not the ones asked for: {got['cards']}")
    check(got['label'] == 'Mornings', f"a titled tile lost its title: {got['label']}")


def scenario_a_card_titled_and_a_card_named_are_different_questions():
    """`label` is what the EDITOR calls a card in a list of them, so it always
    has an answer — a list of five untitled cards has to be navigable. `title`
    is what gets DRAWN over it, and blank means draw nothing and take no room.

    Conflating them is what put "A Home Assistant card" over a Home Assistant
    card: a second label in a box that already had one, and a row of space the
    card wanted."""
    got = _with_builders({'ha_card': _Spy(), 'chores': _Spy()}, lambda: _custom(
        [{'type': 'ha_card'},
         {'type': 'chores', 'config': {'title': "Emma's jobs"}}]))
    plain, named = got['cards']
    check(plain['title'] == '' and plain['label'],
          f"an untitled card has a title to draw, or no name to be listed "
          f"under: {plain['title']!r} / {plain['label']!r}")
    check(named['title'] == "Emma's jobs" and named['label'] == "Emma's jobs",
          f"a titled card lost it: {named['title']!r}")


def scenario_a_custom_tile_can_drop_its_panel():
    """A card draws its own surface, so a tile drawing another behind it is a
    box inside a box — which is what two nested panels look like on a wall."""
    got = _with_builders({'chores': _Spy()}, lambda: _tile(
        {'id': 'mine', 'type': 'custom',
         'config': {'bare': True, 'cards': [{'type': 'chores'}]}}))
    check(got['bare'] is True, "the tile did not take its panel off")
    check(_custom([{'type': 'chores'}]).get('bare') is False,
          "a tile nobody asked to be bare lost its panel")


def scenario_an_untitled_custom_tile_is_a_plain_panel():
    """Blank means blank. Somebody wanting one surface under three cards is not
    asking for a heading reading "Custom"."""
    got = _with_builders({'chores': _Spy()}, lambda: _custom([{'type': 'chores'}]))
    check(got['label'] == '', f"an untitled tile invented a heading: {got['label']!r}")


def scenario_an_empty_custom_tile_says_so():
    """A container somebody added on purpose and has not filled is not an
    unconfigured feature. One that vanished could not be told from one that had
    broken, which is the same reason a quiet tile says it is quiet."""
    got = _custom([])
    check(got and got['cards'] == [], "an empty custom tile drew cards")
    check(got['data']['empty'], "an empty custom tile said nothing at all")


def scenario_a_quiet_card_leaves_no_cell():
    got = _with_builders({'chores': _Spy(None), 'weather': _Spy({'high': 71})},
                         lambda: _custom([{'type': 'chores'}, {'type': 'weather'}]))
    check([c['type'] for c in got['cards']] == ['weather'],
          f"a card with nothing to say still took a cell: {got['cards']}")


def scenario_a_cards_id_cannot_collide_with_a_tiles():
    """A card draws the tile body — element ids and all. A `calendar` card in a
    custom tile answering to the same id as the `calendar` tile beside it is
    one map rendered into the other's canvas."""
    got = _with_builders({'calendar': _Spy()}, lambda: _custom(
        [{'type': 'calendar'}], iid='mine'))
    check(got['cards'][0]['id'] == 'mine-calendar',
          f"a card's id is not namespaced by its tile: {got['cards'][0]['id']}")
    # A built-in tile's card keeps the TILE's id, because it is the tile — and
    # every element id on the board that predates cards still resolves.
    built = _with_builders({'calendar': _Spy()}, lambda: _tile(
        {'id': 'calendar-2', 'type': 'calendar', 'config': {}}))
    check(built['cards'][0]['id'] == 'calendar-2',
          f"a built-in tile's card was renamed under it: {built['cards'][0]['id']}")


def scenario_a_container_cannot_hold_a_container():
    """Not because it could not be made to work — because a wall panel is read
    from across a room, and the markup that draws a card is the markup that
    draws a tile and cannot include itself."""
    kept = home_board.normalize_cards([{'type': 'custom'}, {'type': 'chores'}])
    check([c['type'] for c in kept] == ['chores'],
          f"a container was allowed inside a container: {kept}")
    check(home_board.container_types() == {'custom'},
          f"the containers are not what the catalog says: {home_board.container_types()}")


def scenario_a_card_is_sized_in_twelfths_of_its_tile():
    """The same unit a card inside a Home Assistant stack uses, so the number
    means one thing on this page rather than two."""
    got = _with_builders({'chores': _Spy()}, lambda: _custom(
        [{'type': 'chores', 'config': {'cols': 6, 'rows': 3}}, {'type': 'chores'}]))
    check(got['cards'][0]['cols'] == 6 and got['cards'][0]['rows'] == 3,
          f"a card's size did not survive: {got['cards'][0]}")
    check(got['cards'][1]['cols'] == 12 and got['cards'][1]['rows'] == 0,
          f"an unsized card is not full width by default: {got['cards'][1]}")
    wild = _with_builders({'chores': _Spy()}, lambda: _custom(
        [{'type': 'chores', 'config': {'cols': 900}}]))
    check(wild['cards'][0]['cols'] == 12, "a card's width is not clamped")


def scenario_a_broken_card_does_not_take_the_tile_down():
    """One card throwing has to cost that card and nothing else. A custom tile
    is several features in one, which is several more chances to throw."""
    def boom(now, config=None, **_):
        raise RuntimeError('boom')
    got = _with_builders({'chores': boom, 'weather': _Spy({'high': 71})},
                         lambda: _custom([{'type': 'chores'}, {'type': 'weather'}]))
    check([c['type'] for c in got['cards']] == ['weather'],
          f"a throwing card took its neighbours with it: {got}")

def scenario_a_card_can_drop_its_own_panel():
    """The card-level twin of the custom tile's `bare` (user ask 2026-08-13):
    a household composing a custom tile out of existing cards should not get
    every one of them in its own box. The payload carries the flag and the
    cell wears the SAME `data-plain` no-surface state a nested stack's cell
    already wears — one plain state, not two."""
    got = _with_builders({'chores': _Spy({'points': 12}),
                          'weather': _Spy({'high': 71})}, lambda: _custom(
        [{'type': 'weather', 'config': {'bare': True}}, {'type': 'chores'}]))
    check(got['cards'][0]['bare'] is True and got['cards'][1]['bare'] is False,
          f"a card's bare flag did not survive the build: {got['cards']}")

    tpl = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       'templates')
    home = open(os.path.join(tpl, 'home.html'), encoding='utf-8').read()
    check(':data-plain="c.bare' in home,
          "the custom tile's cell ignores a card's bare flag")
    # And the option is reachable: the card gear is unconditional now, since
    # every card carries this toggle — a gear gated on the type's own option
    # list left a card with no options no road to it.
    # In the card's own overlay since v2.230.4, because the list it used to
    # live in is gone — cards are dragged, resized and opened on the board now.
    check("setCfg(editing, { key: 'bare'" in home,
          "the editor offers no way to make a card bare")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} tile-and-card scenarios passed")
