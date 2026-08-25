"""The family packing card: today's outings and what each needs packed, as a
board card. Interactive depth (rule 2 — the same reasoning the chores lanes
and routine lanes cards settled): a payload rebuilding under the finger doing
the ticking cannot carry counts, so the builder ships only mount config and
the card self-fetches `GET /api/packing/day` / posts `POST /api/packing/claim`.

Rule 1 splits in two, and both halves are load-bearing: no prep kits at all
means the household never set this up (no tile — the same as any other
unconfigured feature); prep kits but a quiet day is a REAL answer, and gets a
sentence rather than vanishing, because a card that disappears cannot be told
from one that broke.

Run from chauffeur/:  python tests/test_packing_card.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('CHAUFFEUR_DATA_DIR',
                      tempfile.mkdtemp(prefix='chauffeur_packing_card_'))

from services import home_board  # noqa: E402
from services import storage  # noqa: E402


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def scenario_a_household_with_no_kits_gets_no_card():
    """Rule 1's first half: hide what is not SET UP. No prep kits at all means
    the household has never used this, and the card vanishes the way any
    unconfigured feature's does."""
    orig = storage.get_prep_kits
    try:
        storage.get_prep_kits = lambda: []
        check(home_board._tile_packing(None, config={}) is None,
              "a household with no prep kits at all should get no card")
    finally:
        storage.get_prep_kits = orig


def scenario_a_quiet_day_says_so_rather_than_vanishing():
    """Rule 1's second half, and the half that was learned the hard way: never
    hide what is merely quiet. A household with kits and a day that needs
    nothing packed gets a sentence, because a card that disappears is
    indistinguishable from a card that broke."""
    orig = storage.get_prep_kits
    try:
        # The builder cannot know the day is quiet without doing the work
        # (rule 2 says it must not) — so kits existing at all is enough to
        # keep the card. "Nothing to pack for today's outings." is the
        # sentence REQUIRED_EMPTY carries for the board machinery to show
        # when the self-fetch itself comes back with no outings.
        storage.get_prep_kits = lambda: [{'id': 'k1', 'name': 'Soccer bag',
                                          'items': ['Water bottle']}]
        built = home_board._tile_packing(None, config={})
        check(built is not None,
              "a household with kits set up should keep its card on a quiet day")
        check(home_board.REQUIRED_EMPTY.get('packing')
              == "Nothing to pack for today's outings.",
              f"the required-empty sentence is missing or wrong: "
              f"{home_board.REQUIRED_EMPTY.get('packing')!r}")
    finally:
        storage.get_prep_kits = orig


def scenario_the_card_carries_only_its_mount_config():
    """Rule 2: interactive depth means the card fetches its own data. The
    builder ships `interactive` and the members filter and nothing else — a
    payload rebuilding under the finger doing the ticking cannot carry counts."""
    orig = storage.get_prep_kits
    try:
        storage.get_prep_kits = lambda: [{'id': 'k1', 'name': 'Soccer bag',
                                          'items': ['Water bottle']}]
        built = home_board._tile_packing(
            None, config={'interactive': False, 'members': ['m1', 'm2']})
        check(built == {'interactive': False, 'members': ['m1', 'm2']},
              f"the packing mount config carries more than interactive+members: {built}")
    finally:
        storage.get_prep_kits = orig


def scenario_interactive_defaults_on():
    """The card-conversion paradigm: an inert packing list is a poster. Off
    stays available for a wall that really is only a display."""
    orig = storage.get_prep_kits
    try:
        storage.get_prep_kits = lambda: [{'id': 'k1', 'name': 'Soccer bag',
                                          'items': ['Water bottle']}]
        built = home_board._tile_packing(None, config={})
        check(built['interactive'] is True,
              f"interactive should default on: {built}")
        built_blank = home_board._tile_packing(None, config=None)
        check(built_blank['interactive'] is True,
              f"interactive should default on with no config at all: {built_blank}")
    finally:
        storage.get_prep_kits = orig


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} packing card scenarios passed")
