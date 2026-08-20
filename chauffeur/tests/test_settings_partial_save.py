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


def scenario_a_surface_never_saves_settings_it_never_loaded():
    """The other half of "a page may save only its own keys", and the half
    that cost a household their wall.

    Both board editors keep the panel globals — theme, background, screensaver,
    idle return — in a draft that is INITIALISED to the defaults and only then
    filled in from the server. Every one of those defaults is a plausible
    value, so the server has nothing to refuse: `exclude_unset` protects the
    keys a client omits, and these were not omitted, they were sent wrong.

    The way it happened is an add-on update. The container stops, an open tab
    reloads into a 502, the load throws into a silent catch, and the draft
    stays on defaults — and the next edit posts them over the household's
    settings. Reported as the panel settings being wiped on every update.

    So the refusal has to be on the client, before the payload is built: a
    surface with an unloaded draft has nothing to say about ANY setting.
    """
    import os

    # The FILES, not `tpl_source.read` — that inlines every include, and three
    # different components on this page have an `async save()`.
    tpl = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       'templates')
    read = lambda n: open(os.path.join(tpl, n), encoding='utf-8').read()

    # The home board's editor: one guard at the top of save().
    home = read('home.html')
    guard = home.split('async save() {', 1)[1].split('fetch(', 1)[0]
    check('if (!this.setupLoaded)' in guard,
          "the board editor builds a payload from a draft that never loaded")

    # And the config page's board admin, which posts the same globals.
    admin = read(os.path.join('components', 'boards_admin.html'))
    check('panelLoaded: false' in admin,
          "the boards admin cannot tell loaded settings from its defaults")
    save = admin.split('savePanel() {', 1)[1].split(chr(10) + '        },', 1)[0]
    check('if (!this.panelLoaded)' in save and 'return;' in save,
          "savePanel posts its defaults over the household's settings")

    # Both retries exist, because refusing the save is only half an answer —
    # an editor that can never save again is its own bug.
    check('this.loadSetup();' in guard, "the board editor never retries the load")
    check('this.loadBoards();' in save, "the boards admin never retries the load")
    check('_setupTries' in home,
          "a failed loadSetup is final, so one bad reload disables the editor "
          "for the life of the page")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} partial-save scenarios passed")
