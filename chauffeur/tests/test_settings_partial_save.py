"""The write half of settings decentralisation: a page may save ONLY its own keys.

`POST /api/settings` merges with `exclude_unset=True` and says so in a comment
— "clients send only the fields they manage (the config page doesn't know
about intake creds; /intake doesn't know about solver toggles)". That contract
had a hole for as long as it existed: `Settings.calendar_ids` was a REQUIRED
field, so FastAPI rejected every partial body with 422 before the merge was
ever reached.

Found while building the wall-panel setup (v2.110.0), which POSTs three keys
and nothing else. It was never specific to the panel: the meals page's "how we
eat" panel and the kitchen panel post their own keys too, and every one of
those saves was failing. Decentralising settings onto the pages that own them
only works if those pages can actually write.

Two properties, and they pull in opposite directions, which is why both are
pinned:

  1. A partial body VALIDATES — otherwise no decentralised page can save.
  2. An omitted field stays OUT of the dump — otherwise the default silently
     clobbers stored values, which is a far worse bug than the one being
     fixed. (A blind replace here once wiped intake mailbox credentials on
     every config-page save; that is what `exclude_unset` is defending.)

Run from chauffeur/:  python tests/test_settings_partial_save.py
"""
from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR)

from models.schemas import Settings


# One payload per decentralised surface that writes settings, named so a
# failure says WHICH page just lost its save.
PARTIAL_SAVES = {
    'the wall panel setup (/home)': {
        'panel_widgets': ['shopping', 'occasions'],
        'panel_tabs': ['home', 'schedule', 'chores'],
        'panel_idle_return_seconds': 300,
    },
    'how we eat (/shopping)': {
        'household_headcount': 4, 'car_dining': 'full', 'venue_dining': 'full',
        'grocery_plan_lead_days': 2, 'meal_week_enabled': True,
    },
    'the kitchen (/shopping)': {
        'kitchen_ovens': 2, 'kitchen_burners': 4, 'kitchen_cooks': 1,
    },
    'email intake (/intake)': {
        'ingest_email_enabled': True, 'ingest_email_host': 'imap.gmail.com',
    },
}


def scenario_every_decentralised_page_can_save_only_its_own_keys():
    """Property 1. A required field anywhere on Settings breaks all of these
    at once, which is exactly how this shipped."""
    for page, body in PARTIAL_SAVES.items():
        try:
            Settings(**body)
        except Exception as e:
            raise AssertionError(f"{page} can no longer save its own keys: {e}")


def scenario_an_omitted_field_never_reaches_the_merge():
    """Property 2. The endpoint merges `model_dump(exclude_unset=True)` into
    the stored settings, so anything a page did not send must be absent from
    the dump — a default that travels is a default that overwrites."""
    for page, body in PARTIAL_SAVES.items():
        dumped = Settings(**body).model_dump(exclude_unset=True)
        check(set(dumped) == set(body),
              f"{page} sent {sorted(body)} but the dump carries {sorted(dumped)}")


def scenario_a_partial_save_cannot_empty_the_calendar_list():
    """The specific regression. `calendar_ids` was made optional to unblock
    partial saves; if it ever starts travelling as [] on a body that omits it,
    one save from the meals page unhooks the family's calendars from the
    solver."""
    dumped = Settings(**{'panel_idle_return_seconds': 120}).model_dump(exclude_unset=True)
    check('calendar_ids' not in dumped,
          "an omitted calendar_ids reached the merge and would have blanked it")


def scenario_a_deliberate_empty_list_still_travels():
    """The other direction: clearing the calendars ON PURPOSE has to work, so
    `exclude_unset` must key off what was SENT, not off emptiness."""
    dumped = Settings(**{'calendar_ids': []}).model_dump(exclude_unset=True)
    check(dumped == {'calendar_ids': []},
          f"an explicitly emptied list must still be saved, got {dumped}")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} partial-save scenarios passed")
