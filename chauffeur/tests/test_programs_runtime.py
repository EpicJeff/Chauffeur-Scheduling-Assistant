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
    scenario_the_wall_card_is_a_registered_widget()
    scenario_the_wall_card_celebrates_and_does_not_measure()
    print("test_programs_runtime OK")
