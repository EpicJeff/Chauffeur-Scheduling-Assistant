"""The philosophy / bios / solver-themes arc is gone, and stays gone.

The idea: describe your family in prose, add a bio per driver and passenger,
and an LLM would synthesise both scheduling rules AND a set of "solver themes"
— multiplier sets that reweighted the objective — then solve the day several
ways and pick one for you.

Two independent reasons it could never deliver, and the second is the one worth
remembering:

  1. A household has a handful of drivers and a handful of events. The space of
     valid assignments is small, so most reweightings land on the same answer.
  2. Even where it is not small, the terms a theme could touch were three to
     four orders of magnitude below the terms that decide an assignment. The
     driver-is-attending bonus is +50,000,000 and was NOT multiplied by
     anything; the largest theme-controllable term was the primary-driver bonus
     at 2,000. No multiplier in a sane range could move an outcome.

It was switched off in June 2026 (`if False:` around the evaluation) and
removed in v2.353.0. Rule authoring lives with the agent now — "have Jeff
always take Lily to Warriors events" becomes one rule you can read — which is
incremental, inspectable and reversible, none of which a bulk synthesis was.

This file is a REGROWTH GUARD. Every symbol below was load-bearing-looking and
is now absent, and the failure mode of a partial revert is silent: a `theme`
kwarg that nothing passes, a settings key nothing reads, a config tab that
opens on an empty list.

Run from chauffeur/:  python tests/test_no_solver_themes.py
"""
import inspect
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('CHAUFFEUR_DATA_DIR',
                      tempfile.mkdtemp(prefix='chauffeur_notheme_'))

import tpl_source  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TPL = os.path.join(ROOT, 'templates')


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def scenario_the_solver_takes_no_theme():
    """The objective is the objective. A `theme` kwarg that nothing passes is
    an invitation to start passing one again."""
    from solver import matcher
    sig = inspect.signature(matcher.solve_schedule)
    check('theme' not in sig.parameters,
          "solve_schedule still accepts a theme")
    src = inspect.getsource(matcher.solve_schedule)
    for mult in ('unassigned_penalty_mult', 'stickiness_bonus_mult',
                 'travel_time_penalty_mult', 'primary_driver_bonus_mult',
                 'same_loc_bonus_mult'):
        check(mult not in src, f"the solver still applies {mult}")


def scenario_home_location_is_a_named_parameter_now():
    """The `theme` dict was smuggling one real value — and never actually
    carrying it. `Theme` had five multiplier fields and no `home_location`, so
    all six reads inside the solver were None for the life of the feature.

    Kept as an explicit parameter with the same default, so the seam is
    visible instead of buried. This asserts the DEFAULT, not the wiring:
    connecting it changes switch travel times, which changes assignments, and
    that is a deliberate change somebody makes while looking at a re-solved
    week — not a side effect of a deletion.
    """
    from solver import matcher
    sig = inspect.signature(matcher.solve_schedule)
    check('home_location' in sig.parameters,
          "the home location has no way into the solver at all now")
    check(sig.parameters['home_location'].default is None,
          "home_location was wired up during a removal — re-solve a real week "
          "and look at the diff before changing this")


def scenario_nothing_stores_a_theme_or_a_philosophy():
    from services import storage
    from models import schemas
    for gone in ('themes_table', 'ai_feedback_table', 'get_all_themes',
                 'add_theme', 'update_theme', 'delete_theme',
                 'add_ai_feedback', 'get_recent_ai_feedback'):
        check(not hasattr(storage, gone), f"storage still exposes {gone}")
    check(not hasattr(schemas, 'Theme'), "the Theme model is back")
    fields = schemas.Settings.model_fields
    for gone in ('family_philosophy', 'enable_ai_themes'):
        check(gone not in fields, f"Settings still carries {gone}")
    # A bio existed only to be fed to the philosophy prompt and to the button
    # that polished the textarea it was typed into. Nothing ever displayed one.
    check('bio' not in schemas.Driver.model_fields, "Driver still has a bio")
    check('bio' not in schemas.Passenger.model_fields, "Passenger still has a bio")


def scenario_no_route_answers_for_any_of_it():
    import main
    paths = {getattr(r, 'path', '') for r in main.app.routes}
    for gone in ('/api/themes', '/api/themes/{doc_id}',
                 '/api/settings/generate_ai_rules', '/api/settings/refine_text',
                 '/api/settings/ai_feedback'):
        check(gone not in paths, f"{gone} still answers")


def scenario_the_llm_module_lost_the_three_functions():
    from services import llm
    for gone in ('generate_rules_from_philosophy', 'evaluate_schedule_options',
                 'refine_scheduling_text'):
        check(not hasattr(llm, gone), f"services.llm still defines {gone}")
    # …and the ones that are still wired stay. `agentic_chat_loop` is Argyle.
    for kept in ('agentic_chat_loop', 'test_llm_connection'):
        check(hasattr(llm, kept), f"services.llm lost {kept}, which is live")


def scenario_no_surface_offers_it():
    cfg = tpl_source.read('config.html')
    for gone in ("activeTab === 'themes'", 'familyPhilosophy', 'generateAIRules',
                 'refineText(', 'enableAiThemes', 'api/themes'):
        check(gone not in cfg, f"the config page still references {gone}")
    # The LLM CONNECTION settings stay — Argyle is configured here.
    check('testLLMConnection' in cfg and 'llmGeminiApiKey' in cfg,
          "the LLM connection settings went with the philosophy arc; Argyle "
          "needs them")

    dash = open(os.path.join(TPL, 'dashboard.html'), encoding='utf-8').read()
    for gone in ('ai-modal', 'openAIOptionsModal', 'ai-suggestion-banner',
                 'currentAiMetadata', 'submitAIFeedback'):
        check(gone not in dash, f"the dashboard still references {gone}")


def scenario_the_word_theme_still_means_the_panel_one():
    """The removal's one real hazard: this codebase used `theme` for two
    unrelated things, and only one of them was dead. `panel_theme` is the wall
    panel's light/dark, it is on every board and every kiosk page, and it must
    not have been caught in the sweep."""
    from models import schemas
    fields = schemas.Settings.model_fields
    for kept in ('panel_theme', 'panel_theme_sunset_offset_minutes',
                 'panel_theme_sunrise_offset_minutes'):
        check(kept in fields, f"panel theming lost {kept}")
    from services import home_board, storage
    real = storage.get_settings
    try:
        storage.get_settings = lambda *a, **k: {'panel_theme': 'light'}
        got = home_board.profile()
    finally:
        storage.get_settings = real
    check(got.get('theme') == 'light',
          f"the panel no longer resolves its own theme: {got.get('theme')!r}")
    check(callable(getattr(home_board, 'sun_theme', None)),
          "follow-the-sun theming went with the solver themes")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} no-solver-themes scenarios passed")
