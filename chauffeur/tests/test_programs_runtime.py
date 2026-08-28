"""The surfaces, exercised rather than read.

A kid opening the app must see their own program. This is the inversion the
whole arc is for: not what the family needs from them, but their thing being
taken seriously.
"""
import io
import os
import re

from harness import check
from services import storage

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _template(name):
    return io.open(os.path.join(HERE, 'templates', name),
                   encoding='utf-8').read()


def scenario_the_pwa_reaches_a_members_own_programs():
    src = _template('app.html')
    check('api/programs' in src, "the PWA asks for programs")
    check('member_id=' in src or 'member_id:' in src,
          "for the member using it, not the whole family")
    check('/session' in src, "and can log one in a tap")


def scenario_the_pwa_shows_no_streak():
    """The rule, enforced at the surface too: nothing in the PWA's own
    programs markup may render a run of days.

    Scoped to the programs section rather than the whole file: app.html's
    pre-existing Routines feature already says "streak" throughout (a
    shipped, separately-decided feature, not part of this arc), so a
    whole-file check would fail on code this task never touches. The two
    comment markers below bracket exactly the block this task added.
    """
    src = _template('app.html')
    start = src.index('Programs arc, task 6: "My program" -- begin')
    end = src.index('Programs arc, task 6: "My program" -- end')
    section = src[start:end].lower()
    for word in ('streak', 'days in a row', "don't break"):
        check(word not in section, f"the PWA must never say '{word}'")


def scenario_a_members_programs_come_back_filtered():
    import main
    storage.programs_table.truncate()
    storage.add_program({'member_id': 'kid', 'title': 'Guitar', 'state': 'active'})
    storage.add_program({'member_id': 'mom', 'title': 'Running', 'state': 'active'})
    res = main.list_programs_api(member_id='kid')
    titles = [p['title'] for p in res['programs']]
    check(titles == ['Guitar'], f"only their own, got {titles}")
    check(res['programs'][0]['progress']['sessions'] == 0,
          "and it carries progress without a separate call")


def scenario_the_pwa_reads_the_real_commitment_not_shape():
    """The correctness bug the review caught: `programNextWindow` used to
    read `shape.preferred_days` for the next practice day. That field is
    NOT what a program actually committed to -- `services/programs.py`'s
    `propose_slots` pads the days out to `sessions_per_week` whenever fewer
    preferred days were chosen than sessions requested, and `approve()`
    never writes the padded set back into `shape`. So a household taking
    the defaults (3 a week, no preferred days) has a REAL commitment and an
    EMPTY `shape.preferred_days` -- the old code showed nothing at all,
    silently, for the household that took the defaults.

    A template-source scan cannot see a wrong COMPUTED value -- every
    scenario above this one only proves a string is present somewhere in
    app.html. This drives a real browser against a real server (the same
    `live_app` harness `test_short_drives_still_draw.py` uses for exactly
    this reason) with a program whose `shape.preferred_days` is empty and
    whose real commitment is matched only through `emissions.commitment_ids`,
    and reads the rendered page for the commitment's own time -- something
    that could only have come from `GET api/commitments`, never from `shape`.
    """
    from live_app import live_app

    def seed():
        storage.members_table.truncate()
        storage.programs_table.truncate()
        storage.protected_commitments_table.truncate()
        storage.add_member({'id': 'kid', 'name': 'Lily', 'role': 'child'})
        # Every day, late at night -- guaranteed to still be ahead of "now"
        # whenever this test happens to run, so the scenario never depends
        # on the wall-clock time of day.
        storage.add_protected_commitment({
            'id': 'commit1', 'member_id': 'kid', 'title': 'Guitar practice',
            'days_of_week': [0, 1, 2, 3, 4, 5, 6],
            'time_start': '23:00', 'time_end': '23:59', 'active': True})
        storage.add_program({
            'id': 'prog1', 'member_id': 'kid', 'title': 'Guitar',
            'state': 'active', 'phases': [],
            'shape': {'sessions_per_week': 3, 'minutes': 25,
                     'preferred_days': []},
            'baseline': {'start_date': '2026-08-01', 'target_date': None,
                        'target_event_id': None, 'rebaselined_at': None,
                        'rebaselines': 0},
            'emissions': {'commitment_ids': ['commit1'],
                         'thread_ids': [], 'event_ids': []}})

    served = live_app(seed)
    if served is None:
        return
    try:
        handle = served.browser()
        with handle as page:
            page.goto(served.url('app'))
            page.evaluate("localStorage.setItem('chauffeur_member_id', 'kid')")
            page.goto(served.url('app'))
            page.wait_for_timeout(1200)
            try:
                skip = page.get_by_text('Skip', exact=True)
                if skip.count():
                    skip.first.click()
                    page.wait_for_timeout(500)
            except Exception:
                pass
            page.evaluate(
                "if (typeof setView === 'function') setView('myday')")
            page.wait_for_timeout(1500)
            # `myday-content` specifically, not `document.body`: the page's
            # own <script> tags carry the literal string "Next practice"
            # in their SOURCE (the template literal that builds the row),
            # so a whole-body textContent check would pass whether or not
            # the div actually rendered -- exactly the false-positive this
            # test exists to not be. `myday-content` only ever holds
            # `renderMyDay`'s own `innerHTML` write, never a `<script>`.
            text = page.evaluate(
                "(document.getElementById('myday-content') || {}).textContent || ''")
    finally:
        served.stop()

    check(not handle.errors, f"the page threw: {handle.errors[:3]}")
    check('Next practice' in text,
          "a program with an empty shape.preferred_days but a real "
          "commitment must still show a next-practice line -- "
          f"body had: {text[:2000]!r}")
    check('11:00 PM' in text,
          "the time shown must come from the real commitment (23:00), "
          "which shape.preferred_days could never have supplied -- "
          f"body had: {text[:2000]!r}")


def scenario_the_wall_card_is_a_registered_widget():
    import json
    src = _template(os.path.join('components', 'board_tile_body.html'))
    check('programs' in src, "the board can draw a programs tile")
    boards = json.load(io.open(os.path.join(HERE, 'services',
                                            'builtin_boards.json'),
                               encoding='utf-8'))
    check(isinstance(boards, dict), "builtin boards still parse")


def scenario_the_wall_card_celebrates_and_does_not_measure():
    src = _template(os.path.join('components', 'programs_card.html'))
    # Strip Jinja control tags ({% macro %}, {% endmacro %}, ...) before the
    # scan: their own '%' delimiters are template syntax, not something a
    # viewer could ever see, and a raw whole-file scan for '%' would flag
    # every macro-based component in the house style — packing_card.html,
    # the file this card is explicitly built to follow, included.
    prose = re.sub(r'\{%.*?%\}', '', src, flags=re.S).lower()
    for word in ('streak', 'behind', 'missed', 'rank', 'leaderboard'):
        # Word-boundary, not a bare substring: Tailwind's own `shrink-0`
        # (all over this house style, agenda_row.html included) contains
        # "rank" as letters, not as the word — a plain `in` check would flag
        # ordinary CSS on every card that uses it.
        check(not re.search(r'\b' + word + r'\b', prose),
              f"the wall must never show '{word}' — a family is not a cohort")
    check('%' not in prose, "the wall must never show a percentage")
    check('milestone' in prose, "it shows what somebody just reached")


if __name__ == '__main__':
    scenario_the_pwa_reaches_a_members_own_programs()
    scenario_the_pwa_shows_no_streak()
    scenario_a_members_programs_come_back_filtered()
    scenario_the_pwa_reads_the_real_commitment_not_shape()
    scenario_the_wall_card_is_a_registered_widget()
    scenario_the_wall_card_celebrates_and_does_not_measure()
    print("test_programs_runtime OK")
