"""The family packing card's BUILDER: `home_board._tile_packing` and the
inline quiet-day sentence it hands off to the card's own macro.

Split out of `test_packing_card.py` in Task 6's fix round: that file grew a
playwright chromium harness (its own imports, its own `SCRATCH`/`_boot`/
`_chromium` fixtures, no `home_board`/`storage` in sight), and these five
scenarios are plain Python unit tests of the builder function — no browser,
no jsdom, nothing playwright-shaped about them. They came from base
commit d284293's `tests/test_packing_card.py` and were dropped, unreplaced,
when that file was rewritten into the playwright harness; this file restores
them verbatim (see the fix report for task 6 for the finding).

Rule 1 used to split in two: no prep kits at all meant the household never
set packing up (no tile — the same as any other unconfigured feature); prep
kits but a quiet day was a REAL answer, and got a sentence rather than
vanishing, because a card that disappears cannot be told from one that broke.

The family_day_plan (task 3, docs/family_day_design.md "What changes
underneath") flips the FIRST half: the card is no longer a packing feature
somebody opts into, it is the wall's day surface, built on the calendar —
which is core, not opt-in. So a household with zero prep kits still gets the
tile; kits only change what (if anything) a block has to pack. The SECOND
half survives, just retargeted: the quiet-day sentence is no longer "kits
exist but nothing to pack" but "no blocks on the calendar at all" — the
day-level empty state. Rule 2 is untouched: interactive depth means the card
fetches its own data, so the builder ships only mount config — a payload
rebuilding under the finger doing the ticking cannot carry counts.

Run from chauffeur/:  python tests/test_packing_card_builder.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('CHAUFFEUR_DATA_DIR',
                      tempfile.mkdtemp(prefix='chauffeur_packing_card_builder_'))

import tpl_source  # noqa: E402
from services import home_board  # noqa: E402
from services import storage  # noqa: E402

TPL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   'templates')


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def scenario_a_household_with_no_kits_still_gets_the_day():
    """Inverts the old `scenario_a_household_with_no_kits_gets_no_card`
    (rule 1 flip #1, docs/family_day_design.md "What changes underneath").
    That scenario proved a household with no prep kits at all got NO card —
    the packing feature was opt-in, and nobody had opted in. This card is no
    longer a packing feature; it is the wall's day surface, and the calendar
    underneath it is core, not opt-in — a household with zero kits still has
    a day. So the builder now always mounts, kits or none; what a household
    has (or has not) set up for packing only changes whether any BLOCK has
    something to pack, never whether the day itself draws."""
    orig = storage.get_prep_kits
    try:
        storage.get_prep_kits = lambda: []
        built = home_board._tile_packing(None, config={})
        check(built is not None,
              "a household with no prep kits at all should still get the day tile")
        check(built == {'interactive': True, 'members': [], 'days': 1},
              f"the day tile with no config should still carry its mount config: {built}")
    finally:
        storage.get_prep_kits = orig


def scenario_a_quiet_day_says_so_rather_than_vanishing():
    """Never hide what is merely quiet — the half of rule 1 that survives the
    flip above, just retargeted. The tile always mounts now, so what is left
    to pin is the SENTENCE `REQUIRED_EMPTY` carries for the board's own
    pinned/editing machinery to show when the self-fetch comes back with no
    blocks at all: not "kits exist but nothing to pack" (packing is no longer
    the card's question — the day is), but the day-level quiet answer,
    "Nothing on the calendar today." A card that disappears is
    indistinguishable from a card that broke."""
    built = home_board._tile_packing(None, config={})
    check(built is not None, "the day tile should always mount")
    check(home_board.REQUIRED_EMPTY.get('packing')
          == "Nothing on the calendar today.",
          f"the required-empty sentence is missing or wrong: "
          f"{home_board.REQUIRED_EMPTY.get('packing')!r}")


def scenario_the_card_carries_only_its_mount_config():
    """Rule 2: interactive depth means the card fetches its own data. The
    builder ships MOUNT CONFIG ONLY — how to draw, never what to draw. A
    payload rebuilding under the finger doing the ticking cannot carry
    counts, so no block, item or claim may ever appear here. (`days` joined
    interactive and members in F2: it says how far ahead to look, which is
    still a question about the mount and not an answer about the day.)"""
    orig = storage.get_prep_kits
    try:
        storage.get_prep_kits = lambda: [{'id': 'k1', 'name': 'Soccer bag',
                                          'items': ['Water bottle']}]
        built = home_board._tile_packing(
            None, config={'interactive': False, 'members': ['m1', 'm2']})
        check(built == {'interactive': False, 'members': ['m1', 'm2'], 'days': 1},
              f"the packing mount config is not the expected shape: {built}")
        check(not any(k in built for k in ('blocks', 'days_payload', 'groups',
                                           'items', 'packed', 'needed')),
              f"the builder leaked DATA into a self-fetching card: {built}")
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


def scenario_the_quiet_day_sentence_is_gated_on_a_resolved_empty_fetch():
    """Fix round finding #2 (task 6's predecessor), retargeted for the
    family_day_plan's day-level sentence: the builder-level quiet-day check
    above only proves `_tile_packing` keeps the tile and that
    `REQUIRED_EMPTY['packing']` holds a string — neither exercises the card's
    OWN quiet-day rendering, which is where a household actually sees (or
    fails to see) the sentence. This pins that the macro draws "Nothing on
    the calendar today." inline, gated on the resolved BLOCKS list being
    empty (not shown whenever there IS something on the day) and nested
    inside the first-fetch-resolved gate (`pkLoaded`, flipped once
    `loadPacking()` settles either way), so a quiet day says so and a
    still-loading card never flashes the sentence ahead of real data. It
    fails if the inline empty state is deleted or its gating is loosened."""
    full_src = tpl_source.read('components/packing_card.html')
    # The macro body only — the file's own top comment explains the design in
    # prose and names the same sentence, which would otherwise satisfy a
    # naive substring check without the markup ever drawing it.
    src = full_src[full_src.index('{% macro rows()'):]
    sentence = "Nothing on the calendar today."
    check(sentence in src,
          "the card's own macro no longer draws the quiet-day sentence "
          "inline — REQUIRED_EMPTY alone does not reach the wall")

    # Gated on the resolved-empty blocks list, not drawn unconditionally.
    gate_idx = src.index('x-if="!blocks.length"')
    sentence_idx = src.index(sentence)
    gate_close_idx = src.index('</template>', gate_idx)
    check(gate_idx < sentence_idx < gate_close_idx,
          "the quiet-day sentence is not gated on the resolved-empty blocks "
          "list, so it would draw even on a day with something on it")

    # And nested inside the gate that waits for the first fetch to resolve.
    loaded_idx = src.index('x-if="pkLoaded"')
    check(loaded_idx < gate_idx,
          "the quiet-day sentence is not nested inside the pkLoaded gate, so "
          "it could flash before the first fetch resolves")

    script = src[src.index('function packingCard'):]
    check('pkLoaded: false' in script,
          "pkLoaded is not declared as reactive state on the card")
    check('this.pkLoaded = true' in script,
          "the first fetch resolving (success or failure) never flips "
          "pkLoaded, so the card would draw nothing forever")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} packing card builder scenarios passed")
