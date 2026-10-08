# Work first, settings in a drawer — design

**Status:** approved in conversation 2026-10-07; spec awaiting review.
**Scope:** every browser (admin) page. Kiosk (`?kiosk=true`), filtered embeds
(`?tabs=`) and wall panels (`?panel=true`) are out of scope and must not change.

## Problem

Many admin pages mix the feature's settings into the surface you actually use.
The settings push the work down the page or split it in two:

- Mind (18 controls) and Missions (7, including an API key) sit always-open
  *above* the work.
- Meals' "How this works" block (~25 controls) sits between the week planner
  and Our meals.
- Chores' pet XP, reward store and tier editor sit always-open below the queues.
- Intake's Family mailbox (~120 lines, its own Save button) sits at the bottom.
- Threads, Occasions, Trips, Routines and Drives each have one to five
  settings threaded through the work.
- Three different "open the settings" patterns already exist: Home's centered
  modal, Programs' accordion, Map's inline ⚙ reveal.
- Four whole tabs are (almost) only settings: Drive setup, Errands › Rules,
  School › Calendar, Rhythms › Growing up.

## Goal

The main surface of every admin page is the work. A page's settings are reached
in exactly one way, in exactly one place, and look the same everywhere.

Success:

- No settings control renders in any page's work flow.
- Every admin page with settings shows **⚙ Settings** at the same spot, and
  that button opens that page's settings and nothing else.
- Every existing setting is still reachable, keeps its key, endpoint and
  anchor, and Find a setting lands on it.
- Nothing a person could do before is lost.

## The paradigm

### Page bar

The PAGE_GROUPS tab strip in `templates/nav.html` becomes a **page bar** on
every browser admin page:

- Grouped pages show their tabs, as today.
- Ungrouped pages (Home, Trips, Map, Music) show only the page name, taken from
  the NAV_ITEMS label.
- **⚙ Settings** sits at the bar's right end. It opens the settings of the
  *active tab* (Mind's gear opens Mind settings, not all of Work).
- The gear renders only when the active tab has a drawer
  (`[data-settings-for="<tab>"]` exists in the DOM). Config and Find a setting
  show the bar without a gear; they are settings pages.
- Kiosk, `?tabs=` and panel views draw no bar, no gear and no drawer.

### Settings drawer

One shared shell, `templates/components/settings_drawer.html`, a Jinja macro
used with `{% call %}`. Each page wraps its existing settings markup in it.

- **Shape:** a right slide-over, `md:w-[40rem]` (the Control Center's width),
  over a light backdrop. On phones it is an 88vh bottom sheet. The shell is cut
  from the dish editor sheet (`templates/shopping.html:1334`) and uses the UI
  guide's panel vocabulary. No new visual language.
- **Layer:** `z-[85]`, the dish editor's tier: above the Control Center
  (`z-[70]`) and the Ask Argyle bar (`z-[80]`), below page dialogs (`z-[90]`)
  and global prompts (`z-[400]`). Only one drawer is open at a time.
- **Header:** "<Tab label> settings", a save-status mark, ✕.
- **Section chips:** a row of jump chips under the header when the drawer has
  three or more sections.
- **Sections:** heading plus controls. Each section's root keeps its registry
  anchor as its `id`.
- **Close:** ✕, Escape, or tapping the backdrop.
- **Saving:** every control saves on change. Pages keep their current save
  functions and endpoints (`POST /api/settings` with only the page's own keys;
  feature endpoints such as `/api/status-tiers`, `/api/errand_rules` and the
  member API stay as they are). A shared mark in the drawer header shows
  "Saving…", "Saved ✓" or the error. Pages report through one helper,
  `window.chfSettingsSaved(ok, message?)`.
- **Alpine scope:** the drawer markup stays inside the page's own Alpine island,
  so existing bindings and save functions keep working unchanged. Fixed
  positioning lifts it out visually. If any ancestor of the drawer has a CSS
  `transform` (which would trap `position: fixed`), it must be removed or the
  drawer moved; the live test checks the drawer covers the viewport.

### Opening and deep links

- The gear dispatches `chf-settings-open` with `{tab, anchor}` on `window`.
  The drawer whose `data-settings-for` matches opens. A missing anchor opens at
  the top.
- On load, and on `hashchange`: if `location.hash` names an element inside a
  drawer, the page bar switches to that drawer's tab if needed (the existing
  hash-to-tab scripts in `rhythms.html` and `school.html` become one shared
  path), opens the drawer and scrolls to the section.
- Closing the drawer clears a hash that pointed into it (`replaceState`), so a
  reload does not reopen it.
- Find a setting (`/settings`) links stay `page#anchor`. Registry entries that
  fall back to `anchor='general'` (mind, missions, threads, programs) get a real
  anchor on the drawer's first section, and their `page` points at the tab URL
  that hosts them (`work?tab=mind`, `rhythms?tab=programs`, …).
- `services/settings_registry.py` `audit()` gains a check: every registry anchor
  whose page has a drawer sits inside it. Config entries are exempt, since
  Config is a settings page.

### Placement rules

These go into `chauffeur/docs/ui_design_guide.md` as a standing section.

1. **Settings for the whole page** live in the page's drawer, never in the work
   flow.
2. **Settings for one item** live in that item's editor (a reward's active
   switch, a child's school hours, a dish's details), not in the drawer.
3. **Work actions that write a setting** stay in the work area: Block sender in
   Intake, Graduate in Mind.
4. **A feature switched off** shows an honest one-line state in the work area
   with a **Turn on…** button that opens the drawer at the switch. Never a blank
   or silently empty work area.
5. **No pointers** ("settings are now in ⚙") are left where a setting used to
   be, per the v2.499.261 ruling.
6. **Walls never show settings.** Kiosk, `?tabs=` and panel views render no
   drawer.

## Page by page

The work stays on the page. "⚙" lists the drawer's sections.

### Schedule

- **Drives** (`dashboard.html`)
  - Work: toolbar, schedule, timeline, triage inbox.
  - ⚙ sections:
    - Leave margin (moved out of the toolbar)
    - Rules
    - Cars, including car alerts
    - Protected time
    - Outside hands
    - Solver: horizons, behaviour, traffic, tomorrow digest. The solver debug
      panel stays as a button in this section.
  - The Drive setup tab leaves the strip. `/drive_setup` forwards to
    `dashboard_v2`, keeping any hash, and opens the drawer. Registry
    `drive_setup` entries move to `page='dashboard_v2'` with the same anchors.
- **Calendar**
  - Work: the calendar, plus setting and clearing status days and their
    Upcoming list.
  - ⚙: status day *types* (the definitions) from `components/status_days.html`.
- **Moments:** no gear.
- **Occasions**
  - Work: the new-occasion form and list (audience stays per occasion).
  - ⚙: gift lead time (`#gifts`).

### Errands

- **Errands and Tasks:** work as today. ⚙ on either opens **Rules**: the rule
  create form and the rules list (`components/errand_rules.html`).
- The Rules tab leaves the strip. `errands?tab=rules` forwards to the drawer.

### Meals

- **Meals** (`shopping.html`, `page_mode='meals'`)
  - Work: tonight's plate, the week planner, then Our meals directly beneath
    it.
  - ⚙: the whole "How this works" block: meal rules, dining, plate, planning,
    prep, Walmart, pictures, kitchen.
  - The two "How this works" buttons and `showMealSettings` go; ⚙ replaces
    them. `openMealSettings()` callers dispatch the open event instead.
- **Groceries and Lists:** no gear. Default list and sharing stay per list.

### Rhythms

- **Chores**
  - Work: leaderboard (with its per-child point and XP tools), pending rewards,
    verification queue, chore pot.
  - ⚙ sections: critters and pet XP (`#petxp`), reward store (on/off switch plus
    the reward catalog, `#rewards`), status tiers (`#tiers`).
- **Routines** (`components/routines_page.html`)
  - Work: each member's routine blocks (the per-child cue-room select stays
    per item) and prep kits.
  - ⚙ sections: runway (`#runway`), status tiers (`#tiers`), kid evenings
    (`#kid-evenings`).
- **Programs:** the create form and list stay. The "⚙ Settings" accordion and
  `settingsOpen` become the drawer (general, lessons, and the "Write lessons
  now" action).
- **Growing up:** leaves Rhythms entirely; see below.

### Growing up → Config › People

Growing up is a property of each child, not of any one feature. It changes what
the PWA shows them, whether points lead, whether they can ask for things,
whether they get real jobs, and whether programs need a grown-up. Birthdays,
which suggest the stage, already live on People. Config is a settings page, so
the drawer rule does not apply there.

- `components/growing_up.html` moves, unchanged, into one section on the
  Config › People tab, below the member list (`#growing-up`): pending move-ups,
  then each child's stage pin and practise switch, then the cutoff timeline.
  It stays one section rather than splitting pins onto each identity card,
  because the timeline with the kids plotted on it is what makes the model
  readable.
- The registry entry moves to `page='config', anchor='growing-up'`.
- The Needs You stage finding (`services/watchers.py` `_stage_findings`) changes
  its line to "Confirm it in Config → People" and links to
  `config?tab=people#growing-up`.
- The Rhythms Growing up tab leaves the strip. `rhythms?tab=growing-up` forwards
  to `config?tab=people#growing-up`.
- **Why here, and why not again:** this is the section's fourth home
  (Config → School v2.499.250 → Rhythms v2.499.256 → Config). School was wrong
  because growing up is not about school. Rhythms was wrong because it reaches
  far beyond routines. It belongs with the people it describes. It should not
  move again without a reason that beats that one.

### School

- Work: the per-child cards, with Add a task for this child, unchanged. They
  are per-item editors (rule 2).
- ⚙: Calendar (calendar id, year dates, keywords).
- The Calendar tab leaves the strip. School is left with one tab, so its bar
  shows just "School". `school?tab=calendar` forwards to the drawer.

### Work

- **Intake**
  - Work: missed mail, proposals, mis-filed, skipped duplicates, ignored
    senders (Block stays), activity log.
  - ⚙: Family mailbox (`#settings`, `#ingest-daily-limit`): fields, sender to
    calendar map, blocked senders, daily limit.
  - The Save Settings button goes. Each field saves on change through the
    existing `POST /api/ingest/config`. Text fields save on blur or change, not
    per keystroke. This is the one behaviour change in the arc.
- **Mind**
  - Work: insight lane, history, counters with Graduate.
  - ⚙: all of today's top block (enabled, wake times, cadences, caps,
    negotiation, `#heads-ups`).
  - When Mind is off, the work area shows rule 4's state.
- **Threads**
  - Work: create form and list.
  - ⚙: stall days.
- **Missions**
  - Work: launch, active missions, history.
  - ⚙: its seven controls. The API key shows set or not set only, as Find a
    setting already does.

### Ungrouped pages

- **Home and Music** (`home.html`)
  - The `#board-settings` modal becomes the drawer: name, icon, address,
    picture, grid. It keeps saving on close.
  - The toolbar's ⚙ goes. ✎ Edit stays, since it is a work action.
- **Trips**
  - Work: the gallery.
  - ⚙: trip hashtags (`#trip-hashtags`).
- **Map**
  - Work: the announce strip and the map.
  - ⚙: Announcements (Argyle's voice plus each room's speaker pin,
    `#announce`). The announce strip's ⚙ reveal goes.

### Not changing

Config (apart from gaining Growing up), Find a setting, all item editors (dish
sheet, event modals, card and tile editors, triage), Moments, Groceries, Lists,
and every kiosk, `?tabs=` and panel view.

## What goes away

No setting and no capability is removed. These are replaced by the gear:

- the strip tabs Drive setup, Errands › Rules, School › Calendar and
  Rhythms › Growing up (each URL forwards)
- duplicate openers: Meals' "How this works" buttons, Home's toolbar ⚙,
  Map's ⚙ reveal, Programs' accordion

Intake's Save button gives way to saving on change.

## Build order

Each slice is its own release: bump `chauffeur/config.yaml`, commit
`(vX.Y.Z)`, push. Each one updates `system_capabilities.md`, runs
`tools/build_tailwind.py` when classes change, and carries screenshot proof:
drawer closed and open, dark theme, desktop and phone width.

1. **Shell plus pilots:**
   - page bar on every admin page
   - `settings_drawer.html`, gear, open event, deep links
   - shared save mark and the switched-off state
   - registry `audit()` drawer check
   - placement rules in `ui_design_guide.md`
   - pilots: Threads and Programs
2. **Work:** Mind, Missions, Intake.
3. **Meals.**
4. **Rhythms:** Chores and Routines; Growing up moves to Config › People.
5. **Schedule:** Drives takes in Drive setup; Calendar status day types;
   Occasions.
6. **The rest:** Errands Rules, School Calendar, Trips, Map, Home and Music.

## Testing

- **Pins (source or rendered-HTML tests):**
  - each admin page shows the gear exactly when the active tab has a
    `data-settings-for` drawer
  - no registry anchor of a drawer page sits outside the drawer (`audit()`)
  - kiosk, `?tabs=` and panel renders contain no drawer and no gear
  - forwarded URLs (`/drive_setup`, `?tab=rules`, `?tab=calendar` on School,
    `?tab=growing-up`) land on the right drawer section
  - the page-group tests (`test_nav`, `test_page_tabs_live`) updated for the
    removed tabs and the bar on ungrouped pages
- **Live (playwright, one per slice):** load the page, click ⚙, change one
  control, assert the request went out and "Saved ✓" shows, reload, assert the
  value stuck. Plus one deep-link test that opens from a hash. This is the
  runtime check that source-reading tests miss.
- Per change, run `tools/test.py --focus` with the touched and keyword-matched
  tests only, with `HA_BASE_URL` unset. Full sweep at the end of the arc.

## Risks

- **Fixed-position trap:** an ancestor with `transform` would clip the drawer
  inside the page. The live test asserts the drawer's rect covers the viewport.
- **Tests that read raw templates:** moving markup into the macro changes
  where strings live. Tests that raw-open templates must flatten includes (the
  admin-consolidation trap).
- **Discoverability:** settings are one click further away. The gear is
  labelled, always in the same spot, and Find a setting deep-links into
  drawers.
