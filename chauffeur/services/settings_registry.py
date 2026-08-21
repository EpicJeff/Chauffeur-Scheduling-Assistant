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
    ('panel', '🖥️', 'The wall panel'),
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


def _e(key, group, label, help_text, page=_CONFIG, anchor='general', ui_marker=None):
    # `ui_marker` is for the honest exception: a control that does not name its
    # setting anywhere. The status-tier editor is one component shared by Chores
    # and Routines, keyed by `kind` and saving through /api/status-tiers, so the
    # words `chore_status_tiers` appear nowhere on screen. Declaring the marker
    # keeps the coverage audit truthful without weakening it into a guess.
    return {'key': key, 'group': group, 'label': label, 'help': help_text,
            'page': page, 'anchor': anchor, 'ui_marker': ui_marker}


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
    _e('trip_hashtags', 'household', 'Trip hashtags',
       'Event hashtags that mark something as a trip rather than a normal day.'),
    _e('route_cache_duration_mins', 'household', 'Route cache',
       'How long a computed travel time is reused before being looked up again.'),

    # --- the wall panel (owned by the home board, which is the thing being
    # configured — you pick the tiles while looking at them)
    _e('panel_widgets', 'panel', 'Home board tiles',
       'Which tiles the wall panel home screen shows, and in what order. '
       'A tile with nothing to say hides itself either way.',
       page='home', anchor='board-settings'),
    _e('panel_tabs', 'panel', 'Shelf buttons (old form)',
       'The wall panel shelf, as one curated list. Superseded by the board '
       'order and the hidden list below, which is what the Boards tab writes; '
       'this is still read when those are empty, so a shelf curated before '
       'v2.232.0 keeps working exactly as it did.',
       page='config', anchor='boards', ui_marker='panel_board_order'),
    _e('panel_board_order', 'panel', 'Board order',
       'The order your boards and the app pages sit in, left to right along '
       'the wall panel shelf. Drag them into place on the Boards tab. Six or '
       'seven fit at a size a thumb can hit; the rest move into a More button, '
       'so the order decides what stays one tap away.',
       page='config', anchor='boards'),
    _e('panel_board_hidden', 'panel', 'Boards hidden from the shelf',
       'Boards you have switched off on the Boards tab. They still exist and '
       'still have an address — they just do not get a button on the wall '
       'panel shelf.',
       page='config', anchor='boards'),
    _e('panel_home_board', 'panel', 'Home board',
       'Which board the wall panel treats as home: what /home shows, where an '
       'idle panel returns to, and what the shelf Home button opens. Set it '
       'with the house marker on the Boards tab, so you can build your own '
       'home screen and hide the one that ships.',
       page='config', anchor='boards'),
    # Superseded by `panel_pages`: every board carries its own grid now, and
    # these three are what the FIRST page is built from when a household has
    # never made one. They are still real settings — an un-migrated install
    # reads them — but the control that changes them is the per-board field,
    # which names the page rather than the key. `ui_marker` is what that
    # honest exception is for.
    _e('panel_grid_columns', 'panel', 'Board columns',
       'How many columns a board is divided into. Tile widths are spans of '
       'these, so 12 gives you halves, thirds, quarters and sixths. Set per '
       'board, under Boards.',
       page='home', anchor='board-settings', ui_marker="page().columns"),
    _e('panel_allow_unsafe_controls', 'panel', 'Let the board operate locks',
       'Whether a tap on a board tile may lock or unlock a door, open a cover '
       'or a garage, or turn a valve. Off by default because a wall panel is '
       'reachable by everybody in the house; alarms are never included.',
       page='config', anchor='boards'),
    _e('panel_pages', 'panel', 'Boards',
       'Every board this household has — the wall panel\'s home screen plus '
       'any others you have made. Each one carries its own tiles, layout, '
       'grid and background, so a hallway board and a kitchen board can be '
       'genuinely different screens rather than the same screen twice.',
       page='config', anchor='boards'),
    _e('panel_grid_row_height', 'panel', 'Board row height',
       'What one row of a board grid is worth, in pixels. Tile sizes are '
       'measured in these, so a 2-row tile is twice this tall. Set per board, '
       'under Boards.',
       page='home', anchor='board-settings', ui_marker="page().row_height"),
    _e('panel_tile_spans', 'panel', 'Tile sizes',
       'How much room each tile gets on its board, in columns and rows. Set on '
       'the tile itself, or by dragging its corner in Arrange.',
       page='home', anchor='board-settings', ui_marker='setSpan'),
    _e('panel_background', 'panel', 'Panel background',
       'The photograph the wall panel floats on. A web address, or just a '
       'phrase like "mountains at dusk" to have one found for you.',
       page='config', anchor='boards'),
    _e('panel_shipped_backgrounds', 'panel', 'Pictures for the app\'s boards',
       'A photograph for one of the boards this app ships — Chores, Meals, '
       'Trips and the rest. Those boards are not editable, but their picture '
       'is yours to choose: a web address, or a phrase like "quiet kitchen". '
       'Leave one blank and it uses the panel background.',
       page='config', anchor='boards'),
    _e('panel_theme', 'panel', 'Panel theme',
       'Light, dark, follow the device, or follow the sun. Auto matches Home '
       'Assistant while the panel is embedded in a dashboard, but falls back '
       'to the tablet outside it; Sun asks Home Assistant where the sun is, so '
       'it works the same on the wall and over the tunnel.',
       page='config', anchor='boards'),
    _e('panel_theme_sunset_offset_minutes', 'panel', 'Sunset switch offset',
       'Minutes after sunset the panel goes dark. Negative for before.',
       page='config', anchor='boards'),
    _e('panel_theme_sunrise_offset_minutes', 'panel', 'Sunrise switch offset',
       'Minutes after sunrise the panel goes light. Usually the negative of '
       'the sunset offset — the same darkness of sky comes BEFORE sunrise.',
       page='config', anchor='boards'),
    _e('panel_idle_return_seconds', 'panel', 'Return home when idle',
       'How long the wall panel sits untouched on some other page before it '
       'goes back to the home board. Zero leaves it wherever it was left.',
       page='config', anchor='boards'),
    _e('panel_screensaver_enabled', 'panel', 'Screensaver',
       'Whether the panel ever shows the idle photo slideshow at all.',
       page='config', anchor='boards'),
    _e('panel_screensaver_idle_seconds', 'panel', 'Screensaver after idle',
       'How long the panel sits untouched before it dims into the photo '
       'slideshow. Zero turns the screensaver off.',
       page='config', anchor='boards'),
    _e('panel_screensaver_source', 'panel', 'Screensaver pictures',
       'Where the slideshow pictures come from: the family\'s own Moments '
       'photos, image files in the Home Assistant media folder, or the panel '
       'wallpaper slow-panned.',
       page='config', anchor='boards'),
    _e('panel_screensaver_media_path', 'panel', 'Media folder',
       'Folder in the HA media share to scan for pictures (when the source '
       'is the media folder). Either a name inside the share (photos) or the '
       'full path (/media/photos). Empty scans the whole share.',
       page='config', anchor='boards'),
    _e('panel_screensaver_dwell_seconds', 'panel', 'Seconds per photo',
       'How long each picture holds before crossfading to the next.',
       page='config', anchor='boards'),

    # --- meals & shopping
    _e('car_dining', 'meals', 'Eating in the car',
       'Whether this family eats full meals, handheld food, snacks or nothing in the car.',
       page='meals', anchor='dining'),
    _e('venue_dining', 'meals', 'Eating at a venue',
       'The same question for sitting at a practice or a game.',
       page='meals', anchor='dining'),
    _e('grocery_weekday', 'meals', 'Shop day',
       'The day the big grocery run happens. Unset means work it out from the schedule.',
       page='meals', anchor='planning'),
    _e('household_headcount', 'meals', 'Cooking for',
       'How many people a normal dinner feeds. Decides how far a dish stretches '
       'and whether it makes a second night. Override any single night on the plate.',
       page='meals', anchor='plate'),
    _e('grocery_plan_lead_days', 'meals', 'Plan ahead by',
       'How many days before the shop to ask "how does this look?".',
       page='meals', anchor='planning'),
    _e('grocery_cadence_days', 'meals', 'Days between shops',
       'How many nights one grocery run has to cover. Seven for most families; '
       'set it longer and the plan covers the extra nights instead of leaving '
       'them unbought.',
       page='meals', anchor='planning'),
    _e('meal_week_enabled', 'meals', 'Plan the week',
       'Propose the whole span the next grocery run has to buy for.',
       page='meals', anchor='planning'),
    _e('propose_shopping_errands', 'meals', 'Offer a shopping trip',
       'Suggest an errand for a list that has no trip attached.',
       page='meals', anchor='planning'),
    _e('prep_reminders_enabled', 'meals', 'Prep reminders',
       'Remind about soaking, thawing and marinating that happens outside the cook window.',
       page='meals', anchor='prep'),
    _e('prep_reminder_time', 'meals', 'Night-before reminder',
       'When the evening prep nudge goes out.',
       page='meals', anchor='prep'),
    _e('prep_morning_time', 'meals', 'Morning reminder', 'When the morning-of prep nudge goes out.',
       page='meals', anchor='prep'),
    _e('walmart_store_id', 'meals', 'Walmart store',
       'Localises cart links and prices to your store.',
       page='meals', anchor='walmart'),
    _e('walmart_impact_publisher_id', 'meals', 'Walmart affiliate publisher',
       'Only needed if the household has onboarded as an affiliate. The plain cart link needs none of it.',
       page='meals', anchor='walmart'),
    _e('walmart_impact_ad_id', 'meals', 'Walmart affiliate ad id',
       'Part of the same affiliate trio; leave blank unless you have onboarded.',
       page='meals', anchor='walmart'),
    _e('walmart_impact_campaign_id', 'meals', 'Walmart affiliate campaign',
       'Part of the same affiliate trio; leave blank unless you have onboarded.',
       page='meals', anchor='walmart'),

    # --- the kitchen (owned by the meals surface, not the config page)
    _e('kitchen_ovens', 'kitchen', 'Ovens',
       'How many ovens the kitchen has. Two dishes at different temperatures cannot share one.',
       page='meals', anchor='kitchen'),
    _e('kitchen_burners', 'kitchen', 'Burners',
       'How many rings the hob has. A dish holds its ring while somebody stands at it.',
       page='meals', anchor='kitchen'),
    _e('kitchen_cooks', 'kitchen', 'Usually cooking',
       'How many pairs of hands normally cook. Hands-on work divides between them.',
       page='meals', anchor='kitchen'),

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
    # The flip (auth arc S8). On the People surface with everything else that
    # decides who may reach the house, and DELIBERATELY next to the audit
    # report — the arc's rule is flip on evidence, so the evidence is drawn
    # beside the switch rather than remembered from another page.
    _e('auth_enforce', 'integrations', 'Enforce sign-in',
       'Off, Chauffeur only records what it would have refused (audit mode). '
       'On, every request must prove who it is: members sign in, screens '
       'pair, Argyle presents its token. Refuses to turn on while anyone '
       'would be locked out.', page='config', anchor='people'),
    # Argyle's credential (auth arc S7). On the People surface with the other
    # things that grant access, rather than in the integrations pile: what a
    # family is doing here is deciding who may reach their house.
    _e('service_token', 'integrations', 'Argyle service token',
       'The credential the Home Assistant integration presents. Paste it into '
       'the Chauffeur integration in HA after generating it.',
       page='config', anchor='people'),
    _e('service_local_grace', 'integrations', 'Trust local requests',
       'While on, anything reaching Chauffeur from your own network without a '
       'token is treated as Argyle. Turn it off once the Home Assistant '
       'integration has its token — leaving it on means a permanently trusted '
       'network.', page='config', anchor='people'),
    # Outbound mail (auth arc S3). Lives on the People surface, beside the
    # invite button that uses it — a family configures a sender because they
    # are trying to invite somebody, not because they set out to configure
    # mail. Its own credentials, with a toggle to mirror intake's.
    _e('smtp_use_intake', 'integrations', 'Send from the intake mailbox',
       'Reuse the intake mailbox to send invites instead of its own account. '
       'Off by default: the intake mailbox reads everything that arrives, so '
       'bounces and out-of-office replies to invites would become proposals.',
       page='config', anchor='people'),
    _e('smtp_host', 'integrations', 'SMTP host',
       'The outgoing mail server for invites and password resets.',
       page='config', anchor='people'),
    _e('smtp_port', 'integrations', 'SMTP port',
       'Usually 587 (STARTTLS) or 465 (SSL).', page='config', anchor='people'),
    _e('smtp_user', 'integrations', 'SMTP account',
       'The account that authenticates to the mail server.',
       page='config', anchor='people'),
    _e('smtp_password', 'integrations', 'SMTP password',
       'An app password, never the account password.',
       page='config', anchor='people'),
    _e('smtp_from', 'integrations', 'Send invites as',
       'The From address on invites. Most providers reject a From the '
       'account does not own, so keep it the same or a verified alias.',
       page='config', anchor='people'),
    _e('ingest_sender_defaults', 'intake', 'Sender routing',
       'Which calendar a given sender usually belongs to.', page='intake', anchor='settings'),
    _e('ingest_sender_blocklist', 'intake', 'Blocked senders',
       'Addresses and domains whose mail is skipped instead of read.',
       page='intake', anchor='settings'),

    # --- integrations
    _e('public_base_url', 'integrations', 'Public URL',
       'The address push notifications, invites and share links point back '
       'to — just the address, with no page after it: '
       'https://chauffeur.example.com, not .../app. Everything that uses it '
       'adds its own page, so a page here lands people on /app/app or a 404.'),
    _e('ha_base_url', 'integrations', 'Home Assistant URL', 'Where Home Assistant lives.'),
    _e('ha_browser_url', 'panel', 'Home Assistant address for the panel',
       'Where a BROWSER reaches Home Assistant, for the dashboard tile — '
       'e.g. http://homeassistant.local:8123. Leave empty when the panel '
       'is opened through Home Assistant itself, which is the only '
       'arrangement where framing a dashboard reliably works.',
       page='config', anchor='boards'),
    _e('ha_token', 'integrations', 'Home Assistant token', 'A long-lived access token.'),
    _e('ma_server_url', 'integrations', 'Music Assistant URL', 'Where Music Assistant lives.'),
    _e('ma_token', 'integrations', 'Music Assistant token',
       'A long-lived token from Music Assistant (Settings → Profile). Without '
       'it music still works through Home Assistant; with it the queue, '
       'provider filters, playlists and removable favourites appear.'),
    _e('stage_cutoffs', 'kids', 'When the kid stages change',
       'The three ages where a child moves from Sprout to Explorer to '
       'Navigator to Copilot — roughly preschool, elementary, middle and high '
       'school. Change them to match your schools.',
       page=_CONFIG, anchor='growing-up'),
    _e('assist_ready_buffer_mins', 'household', 'Be-ready buffer for covered rides',
       'When somebody outside the house drives, the wall says "be ready at" — '
       'the start time minus the drive from here minus these minutes. How '
       'early everyone should be standing by the door before the car arrives.',
       page=_CONFIG, anchor='outside-hands'),
    _e('announce_targets', 'integrations', 'Room announcement speakers',
       'Pin which speaker Argyle announces through in a room; unpinned rooms '
       'pick the voice satellite, then whichever player is already on.',
       page='map', anchor='announce'),

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
    _e('traffic_live_enabled', 'maps', 'Day-of traffic',
       'Re-price each drive with real traffic on the day: a predictive pass '
       'in the morning and a live check an hour before leaving. Two small '
       'Directions requests per drive per day; leave-by times and pushes '
       'only ever move EARLIER. Planning stays on typical times.'),
    _e('traffic_morning_hour', 'maps', 'Morning traffic pass',
       'The hour (0-23) the day\'s drives get their predictive traffic '
       'estimates. Default 6.'),
    _e('routing_avoid_tolls', 'maps', 'Avoid toll roads',
       'Price every drive without toll roads. Off, Mapbox happily routes '
       'over the toll road and quotes its faster time whether or not you '
       'would take it. Flipping this clears every cached drive time so the '
       'schedule re-prices under the new policy.'),

    # --- solver
    _e('enable_standard_rules', 'solver', 'Scheduling rules', 'Apply the hand-written solver rules.'),
    _e('enable_standard_priority_rules', 'solver', 'Priority rules',
       'Apply hand-written driver priority rules.'),
    _e('load_balancing_enabled', 'solver', 'Balance the load',
       'Spread driving across parents rather than optimising route length alone.'),
    _e('load_balancing_metric', 'solver', 'Balance by',
       'Whether fairness is measured in trips or in minutes.'),
    _e('chore_status_tiers', 'solver', 'Chore status tiers',
       'The point thresholds behind the chore status colours.',
       page='chores', anchor='tiers', ui_marker='statusTiersEditor'),
    _e('routine_status_tiers', 'solver', 'Routine status tiers',
       'The streak thresholds behind the routine status colours.',
       page='routines', anchor='tiers', ui_marker='statusTiersEditor'),
    # Pet xp. All three live on the CHORES page because that is where the
    # economy is already tuned, even though routines mint too -- one home for
    # the rates beats two half-homes.
    _e('pet_xp_per_chore_point', 'kids', 'Pet XP per chore point',
       'How much pet experience a verified chore mints, per point it is worth. '
       'Separate from points: a chore pays both, and xp never becomes points.',
       page='chores', anchor='petxp'),
    _e('pet_xp_per_routine', 'kids', 'Pet XP per routine',
       'Experience for ticking off one routine item. Once per item per day, '
       'however many times it is tapped.',
       page='chores', anchor='petxp'),
    _e('pet_xp_routine_all_bonus', 'kids', 'Pet XP for a full routine day',
       'A bonus the first time every routine due today is done.',
       page='chores', anchor='petxp'),
    _e('pet_xp_daily_grant', 'kids', 'Daily pet XP for everyone',
       'A small amount of pet experience every member gets each day just for '
       'using the app, so adults with no chores can play too.',
       page='chores', anchor='petxp'),
    _e('pet_pvp_enabled', 'kids', 'Battles between family',
       'Whether children may challenge each other. Off, only the practice '
       'opponents remain. Family battles are always level-matched.',
       page='chores', anchor='petxp'),
    _e('pet_pvp_pair_cap', 'kids', 'Family battles a day',
       'How many battles between the same two people pay experience each day.',
       page='chores', anchor='petxp'),
    _e('pet_pve_daily_cap', 'kids', 'Rewarded battles a day',
       'How many battles pay experience each day. Past it the fight still '
       'happens and the replay still plays -- only the reward stops.',
       page='chores', anchor='petxp'),
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


def _camel(key: str) -> str:
    head, *rest = key.split('_')
    return head + ''.join(w[:1].upper() + w[1:] for w in rest)


def audit_ui(templates_dir: str = None) -> dict:
    """Which registered settings have no way to change them by hand.

    This is the guarantee that nothing gets LOST while settings migrate off
    the config page. The registry says where each setting lives; this checks
    the claim by looking for the key — or its camelCase Alpine binding — in
    that page's template. A registry entry pointing at a page that does not
    actually carry the control is exactly the silent failure the index would
    otherwise hide, and it is worse than the old 5,631-line page: there, at
    least, everything really was on it.

    Ran once at the start of the migration and found SIX settings with no UI
    anywhere at all (sides per plate, dessert, the three prep-reminder keys,
    and the Walmart store id) — none of which the move introduced. They had
    simply never had a hand path.
    """
    import os
    import re
    base = templates_dir or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'templates')
    cache = {}

    def _read(rel, seen):
        """A template PLUS everything it includes.

        Following `{% include %}` is not optional: shared editors are how this
        app surfaces several settings (the status-tier editor is one component
        included by both Chores and Routines), and an audit that stopped at the
        page file reported those as unreachable when they are on screen. A
        false alarm here trains people to ignore the audit, which costs more
        than the audit is worth.
        """
        if rel in seen:
            return ''
        seen.add(rel)
        try:
            with open(os.path.join(base, rel), encoding='utf-8') as fh:
                body = fh.read()
        except OSError:
            return ''
        for inc in re.findall(r"{%\s*include\s+'([^']+)'", body):
            body += _read(inc, seen)
        return body

    # `page` is the ROUTE a setting is linked to (`meals#planning`), and for
    # most destinations the template is that word plus `.html`. Not for all of
    # them: /meals and /lists are one template with two modes (see the header
    # of shopping.html), so the audit has to be told where to read. Kept as a
    # map of exceptions rather than importing main.py's routing table, which
    # would drag the whole app into a test that only wants to read files.
    PAGE_TEMPLATES = {'meals': 'shopping.html', 'lists': 'shopping.html'}

    def _text(page):
        if page not in cache:
            cache[page] = _read(PAGE_TEMPLATES.get(page, f'{page}.html'), set())
        return cache[page]

    missing = []
    for e in ENTRIES:
        body = _text(e['page'])
        if not body:
            missing.append({**e, 'why': f"no template for page '{e['page']}'"})
            continue
        # Word-boundary match so `kitchen_ovens` is not satisfied by a comment
        # mentioning `kitchen_ovens_limit`, and the camelCase form catches the
        # Alpine bindings the config page is written in.
        needles = [e['key'], _camel(e['key'])]
        if e.get('ui_marker'):
            needles = [e['ui_marker']]
        pat = re.compile(r'\b(%s)\b' % '|'.join(re.escape(n) for n in needles))
        if not pat.search(body):
            missing.append({**e, 'why': f"not found on '{e['page']}'"})
            continue
        # The ANCHOR has to exist too, or the deep link drops the reader at the
        # top of the page to hunt. This is the half the first version missed:
        # grepping a template proves a control EXISTS, not that anything can
        # get you to it — and the settings drawer spent a version nested inside
        # an unrelated panel, so every link landed on a hidden element.
        if e['anchor'] != 'general' and not re.search(
                r'id="%s"' % re.escape(e['anchor']), body):
            missing.append({**e,
                            'why': f"no #{e['anchor']} target on '{e['page']}'"})
    return {'unreachable': missing}


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
