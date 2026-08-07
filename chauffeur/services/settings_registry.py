"""Where every setting lives, and what it means.

The problem this solves, measured on 2026-08-07: `templates/config.html` had
grown to 5,631 lines carrying 83 `Settings` fields, all saved through one
whole-object POST. Every arc added to it and none ever took anything out.

The observation that shaped the fix: **the app has been decentralising
settings for a year without calling it that.** ICS feeds live on the driver
form. Pairings live on the dish row. Meal rules live in the "How we eat"
panel. Bus fields live on the member card. Every one of those went where the
family was already looking, and every one works. What is left in config.html
is the residue.

So the paradigm shift was half-finished, not unstarted. This registry is the
missing half: **a searchable index, so decentralisation does not destroy the
one thing a big config page was actually good at** — somewhere to look when
you half-remember a setting but not which page owns it.

Rules for adding an entry:

- Every key in `models.schemas.Settings` must appear here. `audit()` fails
  loudly on any that does not, and a test calls it — a registry that silently
  falls behind the model is worse than none, because the index would then lie
  about being complete.
- `page` + `anchor` point at the surface that OWNS the setting, which is not
  always the config page. Moving a setting to its feature is a change of two
  strings here plus the UI move.
- `help` is the sentence you would say out loud. It is what the index searches
  alongside the label, so it should contain the words a person would actually
  type.
"""

from typing import Dict, List, Optional

# group -> (icon, human title). Ordered as the index renders them.
GROUPS = [
    ('daily', '📅', 'The daily schedule'),
    ('household', '🏠', 'Household'),
    ('meals', '🍽️', 'Meals & shopping'),
    ('kitchen', '🍳', 'The kitchen'),
    ('kids', '🎒', 'Kids & school'),
    ('cars', '🚗', 'Cars'),
    ('digests', '📨', 'Digests & nudges'),
    ('intake', '📬', 'Email intake'),
    ('integrations', '🔌', 'Integrations'),
    ('ai', '✨', 'AI & the assistant'),
    ('maps', '🗺️', 'Maps & quotas'),
    ('solver', '⚙️', 'Solver behaviour'),
]

_CONFIG = 'config'


def _e(key, group, label, help_text, page=_CONFIG, anchor='general'):
    return {'key': key, 'group': group, 'label': label, 'help': help_text,
            'page': page, 'anchor': anchor}


# The declarations. Grouped by what a person is trying to DO, not by which
# model the field happens to sit on.
ENTRIES: List[dict] = [
    # --- the daily schedule
    _e('calendar_ids', 'daily', 'Family calendars',
       'Which Google calendars feed the schedule and the solver.'),
    _e('default_calendar_id', 'daily', 'Default calendar',
       'Where a newly created event lands when nothing else decides.'),
    _e('days_to_show', 'daily', 'Days shown', 'How far ahead the dashboard displays.'),
    _e('days_to_build', 'daily', 'Days solved', 'How far ahead the solver plans drivers.'),
    _e('time_format_24h', 'daily', '24-hour clock', 'Show times as 14:30 rather than 2:30pm.'),
    _e('home_location', 'household', 'Home address',
       'The address every route starts and ends at. Re-saving forces a fresh geocode.'),
    _e('family_philosophy', 'household', 'How this family works',
       'Free text the assistant reads for tone and standing preferences.'),
    _e('trip_hashtags', 'household', 'Trip hashtags',
       'Event hashtags that mark something as a trip rather than a normal day.'),
    _e('route_cache_duration_mins', 'household', 'Route cache',
       'How long a computed travel time is reused before being looked up again.'),

    # --- meals & shopping
    _e('car_dining', 'meals', 'Eating in the car',
       'Whether this family eats full meals, handheld food, snacks or nothing in the car.'),
    _e('venue_dining', 'meals', 'Eating at a venue',
       'The same question for sitting at a practice or a game.'),
    _e('sides_per_meal', 'meals', 'Sides on a plate',
       'How many sides a proposed dinner is built with.'),
    _e('include_dessert', 'meals', 'Dessert on a plate',
       'Whether a composed plate includes something sweet.'),
    _e('grocery_weekday', 'meals', 'Shop day',
       'The day the big grocery run happens. Unset means work it out from the schedule.'),
    _e('grocery_plan_lead_days', 'meals', 'Plan ahead by',
       'How many days before the shop to ask "how does this look?".'),
    _e('meal_week_enabled', 'meals', 'Plan the week',
       'Propose the whole span the next grocery run has to buy for.'),
    _e('propose_shopping_errands', 'meals', 'Offer a shopping trip',
       'Suggest an errand for a list that has no trip attached.'),
    _e('prep_reminders_enabled', 'meals', 'Prep reminders',
       'Remind about soaking, thawing and marinating that happens outside the cook window.'),
    _e('prep_reminder_time', 'meals', 'Night-before reminder',
       'When the evening prep nudge goes out.'),
    _e('prep_morning_time', 'meals', 'Morning reminder', 'When the morning-of prep nudge goes out.'),
    _e('walmart_store_id', 'meals', 'Walmart store',
       'Localises cart links and prices to your store.'),
    _e('walmart_impact_publisher_id', 'meals', 'Walmart affiliate publisher',
       'Only needed if the household has onboarded as an affiliate. The plain cart link needs none of it.'),
    _e('walmart_impact_ad_id', 'meals', 'Walmart affiliate ad id',
       'Part of the same affiliate trio; leave blank unless you have onboarded.'),
    _e('walmart_impact_campaign_id', 'meals', 'Walmart affiliate campaign',
       'Part of the same affiliate trio; leave blank unless you have onboarded.'),

    # --- the kitchen (owned by the meals surface, not the config page)
    _e('kitchen_ovens', 'kitchen', 'Ovens',
       'How many ovens the kitchen has. Two dishes at different temperatures cannot share one.',
       page='shopping', anchor='kitchen'),
    _e('kitchen_burners', 'kitchen', 'Burners',
       'How many rings the hob has. A dish holds its ring while somebody stands at it.',
       page='shopping', anchor='kitchen'),
    _e('kitchen_cooks', 'kitchen', 'Usually cooking',
       'How many pairs of hands normally cook. Hands-on work divides between them.',
       page='shopping', anchor='kitchen'),

    # --- kids & school
    _e('kid_digest_enabled', 'kids', 'Kid evening digest',
       'A calm look at tomorrow, sent to each child in the evening.'),
    _e('kid_digest_time', 'kids', 'Kid digest time', 'When the evening digest goes out.'),
    _e('kid_digest_cutover_time', 'kids', 'Digest cutover',
       'After this time the digest talks about tomorrow rather than today.'),
    _e('kid_quiet_start', 'kids', 'Kid quiet hours start',
       'No push reaches a child after this time.'),
    _e('kid_quiet_end', 'kids', 'Kid quiet hours end', 'Pushes resume from here.'),
    _e('school_calendar_id', 'kids', 'School calendar',
       'A district calendar whose all-day closure events mark days out of session.'),
    _e('school_year_start', 'kids', 'School year starts',
       'How summer is known without guessing from event titles.'),
    _e('school_year_end', 'kids', 'School year ends',
       'The other end of the year, so summer is known rather than guessed.'),
    _e('school_closed_keywords', 'kids', 'No-school keywords',
       'Words in an all-day event title that mean school is closed.'),

    # --- cars
    _e('car_battery_warn_pct', 'cars', 'Battery warning',
       'Charge level below which the car is flagged before a drive.'),
    _e('car_fuel_warn_pct', 'cars', 'Fuel warning',
       'Tank level below which the car is flagged before a drive.'),
    _e('car_auto_errand', 'cars', 'Auto fuel errands',
       'Propose a fuel or charge stop on a route without being asked.'),
    _e('car_fuel_station', 'cars', 'Preferred station', 'Where a fuel stop is proposed by default.'),

    # --- digests & nudges
    _e('tomorrow_digest_enabled', 'digests', 'Tomorrow digest',
       "An evening summary of tomorrow's driving for the parents."),
    _e('tomorrow_digest_time', 'digests', 'Tomorrow digest time', 'When it goes out.'),
    _e('weekly_digest_enabled', 'digests', 'Weekly digest',
       'A weekly family round-up, including anything waiting in intake.'),
    _e('weekly_digest_day', 'digests', 'Weekly digest day', 'Which day it goes out.'),
    _e('weekly_digest_time', 'digests', 'Weekly digest time', 'What time it goes out.'),
    _e('proactive_watchers_enabled', 'digests', 'Proactive nudges',
       'Let the app raise unassigned events, stale proposals and approaching occasions on its own.'),
    _e('weather_entity', 'digests', 'Weather entity',
       'The Home Assistant entity the digests read the forecast from.'),

    # --- intake
    _e('ingest_email_enabled', 'intake', 'Email intake',
       'Poll a dedicated mailbox and turn what arrives into proposals.',
       page='intake', anchor='settings'),
    _e('ingest_email_host', 'intake', 'IMAP host', 'The mail server to poll.',
       page='intake', anchor='settings'),
    _e('ingest_email_user', 'intake', 'Mailbox address', 'The dedicated address the family forwards to.',
       page='intake', anchor='settings'),
    _e('ingest_email_password', 'intake', 'App password',
       'An app password, never the account password.', page='intake', anchor='settings'),
    _e('ingest_sender_defaults', 'intake', 'Sender routing',
       'Which calendar a given sender usually belongs to.', page='intake', anchor='settings'),

    # --- integrations
    _e('public_base_url', 'integrations', 'Public URL',
       'The address push notifications and share links point back to.'),
    _e('ha_base_url', 'integrations', 'Home Assistant URL', 'Where Home Assistant lives.'),
    _e('ha_token', 'integrations', 'Home Assistant token', 'A long-lived access token.'),
    _e('ma_server_url', 'integrations', 'Music Assistant URL', 'Where Music Assistant lives.'),

    # --- AI
    _e('llm_provider', 'ai', 'Model provider', 'Gemini or a local Ollama.'),
    _e('llm_gemini_api_key', 'ai', 'Gemini API key',
       'The key every extraction, suggestion and chat turn runs on.'),
    _e('llm_gemini_model', 'ai', 'Gemini model', 'Overrides the default model pool.'),
    _e('llm_ollama_url', 'ai', 'Ollama URL', 'Where a local model server lives.'),
    _e('llm_ollama_model', 'ai', 'Ollama model', 'Which local model to call.'),
    _e('chat_suggestions_enabled', 'ai', 'Chat suggestions',
       'Offer example prompts on each page.'),
    _e('enable_ai_rules', 'ai', 'AI scheduling rules', 'Let the assistant author solver rules.'),
    _e('enable_ai_priority_rules', 'ai', 'AI priority rules', 'The same for driver priority.'),
    _e('enable_ai_themes', 'ai', 'AI themes', 'Let the assistant restyle the dashboard.'),
    _e('suggested_routes_enabled', 'ai', 'Suggested routes',
       'Offer route ideas alongside the solved schedule.'),

    # --- maps & quotas
    _e('disable_mapbox', 'maps', 'Turn Mapbox off', 'Stops every Mapbox call at once.'),
    _e('disable_mapbox_matrix', 'maps', 'No travel-time matrix', 'Falls back to straight-line estimates.'),
    _e('disable_mapbox_directions', 'maps', 'No directions', 'Stops route geometry lookups.'),
    _e('disable_mapbox_category', 'maps', 'No category search', 'Stops "find a petrol station near" lookups.'),
    _e('mapbox_matrix_limit', 'maps', 'Matrix call limit', 'Monthly cap before the app stops asking.'),
    _e('mapbox_directions_limit', 'maps', 'Directions limit',
       'Monthly cap on route geometry lookups before the app stops asking.'),
    _e('mapbox_geocode_limit', 'maps', 'Geocode limit',
       'Monthly cap on turning an address into coordinates.'),
    _e('mapbox_searchbox_limit', 'maps', 'Search limit',
       'Monthly cap on place searches, which is what trip planning uses.'),
    _e('mapbox_category_limit', 'maps', 'Category limit',
       'Monthly cap on nearby-category lookups such as fuel stations.'),
    _e('enable_mapbox_map_loads', 'maps', 'Interactive maps', 'Whether map tiles load at all.'),
    _e('mapbox_map_loads_limit', 'maps', 'Map load limit', 'Monthly cap on interactive map loads.'),

    # --- solver
    _e('enable_standard_rules', 'solver', 'Scheduling rules', 'Apply the hand-written solver rules.'),
    _e('enable_standard_priority_rules', 'solver', 'Priority rules',
       'Apply hand-written driver priority rules.'),
    _e('load_balancing_enabled', 'solver', 'Balance the load',
       'Spread driving across parents rather than optimising route length alone.'),
    _e('load_balancing_metric', 'solver', 'Balance by',
       'Whether fairness is measured in trips or in minutes.'),
    _e('chore_status_tiers', 'solver', 'Chore status tiers',
       'The thresholds behind the chore status colours.', page='chores', anchor='tiers'),
    _e('routine_status_tiers', 'solver', 'Routine status tiers',
       'The thresholds behind the routine status colours.', page='routines', anchor='tiers'),
]

BY_KEY: Dict[str, dict] = {e['key']: e for e in ENTRIES}
GROUP_TITLES = {g: (icon, title) for g, icon, title in GROUPS}


def audit() -> dict:
    """Which keys the registry has drifted away from.

    Called by a test. A registry that quietly falls behind the model is worse
    than no registry at all, because the index would then claim to be complete
    while hiding whatever was added last.
    """
    from models.schemas import Settings
    model = set(Settings.model_fields)
    listed = set(BY_KEY)
    return {'missing': sorted(model - listed), 'stale': sorted(listed - model)}


def index(values: dict = None) -> List[dict]:
    """Every setting, grouped, with its current value — the one place to look.

    Values are included so the index answers "what is it set to" without a
    round trip to the owning page. Secrets are never returned as values, only
    as whether-they-are-set: an index is a findability tool and has no business
    being a second place a token can leak from.
    """
    vals = values if values is not None else {}
    out = []
    for group, icon, title in GROUPS:
        rows = []
        for e in ENTRIES:
            if e['group'] != group:
                continue
            raw = vals.get(e['key'])
            secret = any(w in e['key'] for w in ('token', 'password', 'api_key'))
            rows.append({**e,
                         'value': ('set' if raw else 'not set') if secret else raw,
                         'is_secret': secret})
        if rows:
            out.append({'group': group, 'icon': icon, 'title': title, 'settings': rows})
    return out


def search(term: str, values: dict = None) -> List[dict]:
    """Label, key and help text are all searched, which is why `help` has to
    contain the words a person would actually type — somebody looking for the
    oven will type "oven", not "kitchen_ovens"."""
    low = (term or '').strip().lower()
    if not low:
        return index(values)
    hits = []
    for grp in index(values):
        rows = [s for s in grp['settings']
                if low in s['label'].lower() or low in s['key'].lower()
                or low in (s['help'] or '').lower()]
        if rows:
            hits.append({**grp, 'settings': rows})
    return hits


def owner(key: str) -> Optional[dict]:
    e = BY_KEY.get(key)
    return {'page': e['page'], 'anchor': e['anchor']} if e else None
