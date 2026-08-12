"""A tile that holds cards, and can be ABOUT somebody.

Every other tile on the board answers "show me X", so a board built only out of
them can be read exactly one way — by content type. The question a family
actually asks is usually about a PERSON: what has Emma got on, what is she
meant to do, where is she. Three tiles each filtered to Emma and kept adjacent
by hand is not that; it is three tiles that have to be re-aimed one at a time.

A group is one tile holding cards with a subject the cards inherit. What has to
hold for that to be worth having:

  * a card is the SAME instance a tile is, built by the same builder — anything
    else is a second renderer per type, and two drawings of one thing always
    drift;
  * the subject reaches every card that can be filtered by person, and NEVER
    silently overwrites a card that names its own people;
  * a card that cannot be filtered is knowable as such, because a subject that
    quietly does nothing on half the cards is worse than no subject at all;
  * a card's id cannot collide with a tile's, since both draw the same markup
    and the same element ids;
  * a group cannot contain a group.

Run from chauffeur/:  python tests/test_board_groups.py
"""
import datetime
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('CHAUFFEUR_DATA_DIR',
                      tempfile.mkdtemp(prefix='chauffeur_groups_'))

from services import home_board  # noqa: E402

NOW = datetime.datetime(2026, 9, 7, 17, 30)


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


class _Spy:
    """Stands in for a tile builder and records the config it was handed —
    which is the only way to see inheritance happen."""

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


def _group(cards, subject='', inst_id='group'):
    return home_board._tile_group(
        NOW, config={'subject': subject, 'cards': cards}, inst_id=inst_id)


def scenario_a_card_is_built_by_the_tiles_own_builder():
    """The whole design in one line. A chores card aimed at one child IS the
    chores tile, filtered — if it were anything else there would be two
    drawings of chores to keep in step for the life of the app."""
    spy = _Spy({'items': [1, 2]})
    data = _with_builders({'chores': spy}, lambda: _group([{'type': 'chores'}]))
    check(len(spy.seen) == 1, "the group did not build its card at all")
    check(data['cards'][0]['data'] == {'items': [1, 2]},
          f"a card carries something other than its builder's payload: {data['cards'][0]}")
    check(data['cards'][0]['type'] == 'chores',
          "a card lost the type it was drawn from")


def scenario_the_subject_reaches_the_cards_that_can_be_aimed():
    """What makes a group one thing rather than three coincidentally-filtered
    tiles: the person is said ONCE."""
    chores, weather = _Spy(), _Spy()
    _with_builders(
        {'chores': chores, 'weather': weather},
        lambda: _group([{'type': 'chores'}, {'type': 'weather'}], subject='m1'))
    check(chores.seen[0].get('members') == ['m1'],
          f"the subject did not reach a card that filters by person: {chores.seen[0]}")
    # And it is not smuggled into one that cannot use it, where it would sit in
    # the config looking like a filter that had been applied.
    check('members' not in weather.seen[0],
          f"a subject was written onto a card that cannot honour it: {weather.seen[0]}")


def scenario_a_card_that_names_its_own_people_keeps_them():
    """"Everyone's calendar, next to Emma's chores" is a real layout, and it is
    only possible if re-aiming the group leaves a deliberately-pointed card
    alone."""
    cal = _Spy()
    _with_builders({'calendar': cal}, lambda: _group(
        [{'type': 'calendar', 'config': {'members': ['m2', 'm3']}}], subject='m1'))
    check(cal.seen[0]['members'] == ['m2', 'm3'],
          f"the group overwrote a card's own people: {cal.seen[0]}")


def scenario_which_cards_can_be_aimed_comes_from_their_own_declaration():
    """Derived, not listed a second time. A type that gains a people filter
    starts honouring the subject the same day, and one that loses it stops —
    a hand-maintained list is the thing that would go stale silently.
    """
    for key in ('chores', 'routines', 'calendar', 'tasks', 'kids', 'map'):
        check(home_board.honours_subject(key), f"{key} stopped honouring a subject")
    for key in ('weather', 'web', 'intake', 'ha_card'):
        check(not home_board.honours_subject(key),
              f"{key} claims to honour a subject it has no filter for")
    # And the editor is told, so it can say so on the card it is offering.
    meta = next(w for w in home_board.catalog()['widgets'] if w['key'] == 'chores')
    check(meta.get('subject') is True, "the catalog does not say a card can be aimed")


def scenario_a_cards_id_cannot_collide_with_a_tiles():
    """A card draws the tile body — element ids and all. A `calendar` card
    inside a group answering to the same id as the `calendar` tile beside it is
    one map rendered into the other's canvas."""
    data = _with_builders({'calendar': _Spy()}, lambda: _group(
        [{'type': 'calendar'}], inst_id='group-2'))
    check(data['cards'][0]['id'] == 'group-2-calendar',
          f"a card's id is not namespaced by its group: {data['cards'][0]['id']}")


def scenario_a_group_cannot_hold_a_group():
    """Not because it could not be made to work — because a wall panel is read
    from across a room, and a layout nested three deep is not read at all."""
    kept = home_board.normalize_group_cards(
        [{'type': 'group'}, {'type': 'chores'}])
    check([c['type'] for c in kept] == ['chores'],
          f"a group was allowed inside a group: {kept}")


def scenario_a_quiet_card_leaves_no_hole_and_an_empty_group_says_so():
    """Rule 1, one level down: a builder with nothing to say is not drawn. But
    a group with nothing in it at all is a tile somebody added on purpose, and
    a tile that vanishes cannot be told from one that is broken."""
    data = _with_builders({'chores': _Spy(None), 'weather': _Spy({'t': 1})},
                          lambda: _group([{'type': 'chores'}, {'type': 'weather'}]))
    check([c['type'] for c in data['cards']] == ['weather'],
          f"a card with nothing to say still took a cell: {data['cards']}")
    check(_group([])['empty'], "an empty group renders as nothing at all")


def scenario_a_group_about_somebody_is_called_after_them():
    """"Group" on the wall above Emma's chores and Emma's calendar is a label
    that says less than the tile beneath it."""
    real = home_board.storage.get_all_members
    home_board.storage.get_all_members = lambda: [{'id': 'm1', 'name': 'Emma'}]
    try:
        data = _with_builders({'chores': _Spy()},
                              lambda: _group([{'type': 'chores'}], subject='m1'))
    finally:
        home_board.storage.get_all_members = real
    check(data.get('label') == 'Emma',
          f"a group about somebody did not take their name: {data.get('label')}")


def scenario_a_card_is_sized_in_twelfths_of_its_group():
    """The same unit a card inside a Home Assistant stack uses, so the number
    means one thing on this page rather than two."""
    data = _with_builders({'chores': _Spy()}, lambda: _group(
        [{'type': 'chores', 'config': {'cols': 6, 'rows': 3}},
         {'type': 'chores'}]))
    check(data['cards'][0]['cols'] == 6 and data['cards'][0]['rows'] == 3,
          f"a card's size did not survive: {data['cards'][0]}")
    check(data['cards'][1]['cols'] == 12 and data['cards'][1]['rows'] == 0,
          f"an unsized card is not full width by default: {data['cards'][1]}")
    # Nonsense is clamped rather than passed to the grid, where a span of 900
    # is a layout nobody can undo from the board.
    wild = _with_builders({'chores': _Spy()}, lambda: _group(
        [{'type': 'chores', 'config': {'cols': 900}}]))
    check(wild['cards'][0]['cols'] == 12, "a card's width is not clamped")


def scenario_a_broken_card_does_not_take_the_group_down():
    """One card throwing has to cost that card and nothing else. A group is
    several features in one tile, which is several more chances to throw."""
    def boom(now, config=None, **_):
        raise RuntimeError('boom')
    data = _with_builders({'chores': boom, 'weather': _Spy({'t': 1})},
                          lambda: _group([{'type': 'chores'}, {'type': 'weather'}]))
    check([c['type'] for c in data['cards']] == ['weather'],
          f"a throwing card took its neighbours with it: {data}")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} group scenarios passed")
