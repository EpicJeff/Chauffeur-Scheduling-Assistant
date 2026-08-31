"""A cited plan that only names books to buy is honest but hollow.

The detector errs toward flagging: a false flag costs one extra tap at
approval; a miss costs a family a plan whose first step is a purchase
nobody mentioned.
"""
from harness import check
from services import programs_curate as cur


def _phase(steps, units=None):
    return {'name': 'Start', 'what': 'begin', 'steps': steps,
            'units': units or []}


def scenario_a_book_only_plan_is_flagged():
    phases = [
        _phase(['Work through Piano Adventures Primer Level']),
        _phase(['Complete Piano Adventures Level 1']),
    ]
    check(cur.book_spine_of(phases) == 'Piano Adventures',
          f"got {cur.book_spine_of(phases)!r}")


def scenario_a_taught_plan_is_not_flagged():
    phases = [
        _phase(['Practice open chords G, C, D for 10 minutes',
                'Play one-minute changes between G and C'],
               units=[{'title': 'Stage 1', 'url': 'https://jg.example/s1'}]),
        _phase(['Learn the A-minor pentatonic scale']),
    ]
    check(cur.book_spine_of(phases) == '', "a plan that teaches is left alone")


def scenario_mixed_plan_is_not_flagged():
    """One book step among real steps is a resource, not a spine."""
    phases = [_phase(['Buy the Faber primer book',
                      'Practice C position five-finger scales daily',
                      'Play Ode to Joy hands separately'])]
    check(cur.book_spine_of(phases) == '', "a resource line is not a spine")


def scenario_units_with_urls_defeat_the_flag():
    """A phase whose units carry instructional urls has real content to
    read, whatever its steps say."""
    phases = [_phase(['Work through the Level 1 book'],
                     units=[{'title': 'Week 1',
                             'url': 'https://ex.example/lesson1'}])]
    check(cur.book_spine_of(phases) == '', "cited units mean readable content")


def scenario_series_name_is_extracted():
    phases = [_phase(['Work through Alfred Basic Level 1A workbook']),
              _phase(['Complete Alfred Basic Level 1B workbook'])]
    check(cur.book_spine_of(phases) == 'Alfred Basic',
          f"got {cur.book_spine_of(phases)!r}")


if __name__ == '__main__':
    scenario_a_book_only_plan_is_flagged()
    scenario_a_taught_plan_is_not_flagged()
    scenario_mixed_plan_is_not_flagged()
    scenario_units_with_urls_defeat_the_flag()
    scenario_series_name_is_extracted()
    print("test_programs_bookspine OK")
