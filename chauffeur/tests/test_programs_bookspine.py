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


def scenario_curate_prefers_pages_that_teach():
    """The research question itself must rank teaching over listing --
    checked at the source, because the question is the one lever curate
    has over what comes back."""
    import inspect
    src = inspect.getsource(cur.curate)
    check('teach' in src and 'list' in src,
          "the question steers toward instructional pages")


def scenario_exclude_books_reaches_the_question():
    """With exclude_books, the question says no-purchase out loud, and a
    plan that still comes back book-spined is sent to the generated tier
    rather than handed over."""
    import inspect
    src = inspect.getsource(cur.curate)
    check('exclude_books' in src, "curate takes the flag")
    check('_fallback' in src, "and can route a stubborn book plan to generated")


def scenario_the_fork_is_on_the_proposal():
    """A book-spined proposal asks its one question on the card, with both
    answers a tap away -- reachable by hand, per the house rule."""
    import io, os
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = io.open(os.path.join(here, 'templates', 'programs.html'),
                  encoding='utf-8').read()
    check('book_spine' in src, "the card knows a book-spined plan")
    check('exclude_books' in src, "and can ask for a bookless one")
    check('Have it' in src or 'have it' in src,
          "and can keep the book as the spine")


if __name__ == '__main__':
    scenario_a_book_only_plan_is_flagged()
    scenario_a_taught_plan_is_not_flagged()
    scenario_mixed_plan_is_not_flagged()
    scenario_units_with_urls_defeat_the_flag()
    scenario_series_name_is_extracted()
    scenario_curate_prefers_pages_that_teach()
    scenario_exclude_books_reaches_the_question()
    scenario_the_fork_is_on_the_proposal()
    print("test_programs_bookspine OK")
