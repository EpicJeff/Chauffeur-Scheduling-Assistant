# PWA reimagined, slice 7: More and its destinations — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** For an adult, More becomes a list in the new look (a 34 px "More" title, a borderless search field, rows with an icon tile, a title, one secondary line and a chevron, no cards and no separators), Profile's sheet takes the same rows, and the destinations More opens (Projects, Library, School, Family map, Music, the critter) take the vocabulary: the wash shows through, cards are the translucent 22 px card with no border, one raised card at most, the one dark primary, pills for chips, 34 px titles, and every essential line at 4.5:1. Builders, ids, handlers, endpoints and behaviour do not change. Kids and the admin and wall hosts of the same components are untouched.

**Architecture:** CSS-first. A marker attribute `data-pwa-skin` goes on each destination's host on the phone (`#projects-container`, `#library-container`, `#music-container`, `#map-container` in `app.html`; the School sheet built in `pwa_school.js`; `#pet-editor-panel` in `pet_editor.html`). One shared block in `static/pwa_shell.css` under `html[data-audience="adult"] [data-pwa-skin]` maps the components' Tailwind surfaces, borders, corners, type and muted text onto the adult tokens (`--pwa-card`, `--pwa-card-raised`, `--pwa-ink`, `--pwa-msg-muted`, `--pwa-radius`); each destination then gets a short block for what the shared map cannot know (Music's now-playing as the raised card, the map's chips over the map, the School sheet, the critter panel). `pwa_shell.css` is linked only by `app.html` and every rule is adult-scoped, so admin pages, the wall and kid shells cannot pick it up. More's change is markup + CSS + `pwaFeatureButton` (a chevron) + the title.

**Tech Stack:** FastAPI + Jinja, vanilla JS, Alpine (vendored), precompiled Tailwind (`python tools/build_tailwind.py` after any template class change), Playwright live tests via `tests/live_app.py`. Tests run from `chauffeur/` as `python tests/test_x.py` with `HA_BASE_URL` unset.

**Spec:** `docs/superpowers/specs/2026-11-03-pwa-reimagined-design.md` ("The vocabulary", "More and the header", "Inherited unchanged", Acceptance's contrast line). No mockup draws More; the vocabulary section is the reference, and Household (`.pwa-house-*`) and Messages (`.pwa-conv*`, `.pwa-conversation-search`) are the shipped examples to match. Inventory: `docs/design/pwa-reimagined/current-state-inventory.md` §9 (More directory) and §10 (Profile) — the preservation checklist. Design guide: `chauffeur/docs/ui_design_guide.md` "Adult PWA, reimagined: the vocabulary".

**Split (codex-coordination):** Claude writes Task 1 (the live proof and its helper) before any code and runs every test; Codex builds Tasks 2–4 (`codex:codex-rescue`, the test file as the contract, the file allow-list per task, no bump, no commit); a Claude reviewer reviews each Codex task; Claude does Task 5.

## Global Constraints

- Adult-only: every new rule sits under `html[data-audience="adult"]`. Kid stages (Sprout's More grid, the kid School sheet, the kid critter editor, the navigator's House Projects section) render exactly as today; `pwa_child_checks.py` stays green.
- Nothing a person can do is removed or moved: every More row and its `run` (`pwaFeatures` is not edited except where Task 2 says), search with the no-match line, every Profile action (avatar, critter, appearance, refresh, notifications, voice setup and delete, switch person / sign out), and every control inside the six destinations.
- No builder, id, handler, endpoint or Alpine state changes in `projects_page.html`, `library_page.html`, `music_widget.html`, `family_map*.html`, `pet_editor.html` or `pwa_school.js`'s render functions. The only markup changes: the `data-pwa-skin` attribute (on the app.html containers, the School sheet's `.pwa-sheet`, `#pet-editor-panel`), More's directory markup, the chevron in `pwaFeatureButton`, Music's page heading.
- Vocabulary values, verbatim from the spec: cards `rgba(255,255,255,.62)` light (the `--pwa-card` token; dark `rgba(255,255,255,.06)`), 22 px corners, no border, no shadow at rest; the one raised card opaque `--pwa-card-raised` with a soft tinted shadow; page titles 34 px weight 700 tight tracking (`-.03em`); row titles 16 px; secondary 13–14 px; section labels 12 px uppercase tracked; chips 12 px weight 600 pill on the muted fill; one dark primary (`--pwa-ink` fill) per screen, secondaries on the muted fill (`color-mix(in srgb, var(--pwa-ink) 6%, transparent)`); 44–56 px targets; essential text never in the faint colour — 4.5:1 or better on the wash and on cards, light and dark.
- Inner corners step down from the card: 18 px for rows inside a page, 14 px for tiles and artwork, 999 px for chips. Nothing hardcodes a hue; the accent stays `--pwa-accent`.
- The map canvas (`#family-map`, MapLibre/Leaflet) and the critter art (the editor's preview canvas/SVG) are not restyled; only the chrome around them.
- No browser dialogs. Page JS fetches `apiBase + 'api/...'`.
- Tailwind rebuilt before any live run; `chauffeur/config.yaml` → `2.499.758` and a `system_capabilities.md` entry in the last task.

## Review Focus

1. **The longest description at 360 px** ("Each child’s assignments, tests and what is due", School for a parent) wraps onto a second line rather than ellipsizing or pushing the chevron off the row, and the row stays one tap target ≥ 56 px (Task 1 `more_rows` at 360).
2. **Dark mode over the deep wash:** Tailwind `text-gray-500`/`text-gray-600` secondary lines inside the destinations fall under 4.5:1 on `rgba(255,255,255,.06)`; the shared map moves them to `--pwa-msg-muted` (Task 1 `contrast` runs every destination in dark).
3. **Projects reached by both doors** — the Household card's pushed screen (parent) and More (lists-only adult, `setView('projects')`) — skins the same, and the pushed screen's own h1 still replaces the component's title (Task 1 `projects_both_doors`).
4. **A sheet opened from inside a destination** (a project's piece sheet, the Library's run sheet, the School task detail, the critter's battle/guide) still opens above its page and closes back to it, and a `.pwa-sheet` appended to `body` keeps slice 0's sheet skin rather than half of this one (Task 1 `sheets_still_open`).
5. **The same components on other hosts** — admin `projects.html`, `library.html`, `map.html`, the wall's music card, kid shells — render unchanged (Task 1 `other_hosts_untouched`: the stylesheet is linked only by `app.html`, and the navigator's School sheet keeps slice 0's kid sheet background `rgb(var(--c-gray-900))` and its task rows' own classes).

---

### Task 1: The live proof and the vocabulary checker (Claude; written before Tasks 2–4, green after them)

**Files:**
- Create: `chauffeur/tests/pwa_vocab_checks.py` (shared helper), `chauffeur/tests/test_pwa_more_live.py`
- Modify: `chauffeur/tests/test_pwa_adult_shell_live.py` (~518–545: the More block keeps every assertion; the title reads "More"; add the chevron count = row count)

**Interfaces:**
- `check_skin(page, host, *, title=None, cards=None, raised=None) -> dict` in `pwa_vocab_checks.py`. In the page: `host` visible; when `title` (selector), its computed font-size `34px`, weight `700`; every visible element matching `cards` (selector) has border widths 0, `border-radius` ≥ 18 px, background equal to the resolved `--pwa-card`; `raised` (selector, optional) has background `--pwa-card-raised` and a non-`none` box-shadow; `host.scrollWidth <= host.clientWidth + 1`. **Contrast:** every visible element inside `host` with a direct non-whitespace text node, except inside `#family-map`, `[disabled]`, `[aria-disabled="true"]`, `input::placeholder` and `[aria-hidden="true"]`, has (text colour × product of ancestor opacities) against its effective background ≥ 4.5 — the effective background composites each ancestor's background colour, outermost first, over the computed `--pwa-sky-mid`. Returns `{checked: n, failures: [{text, ratio, selector}]}`; the caller asserts `failures == []` and `checked > 0`.
- Profiles: `parent` (adult with a Household, d1, a child Maya with school tasks, a critter), `lists_only` (adult, Projects through More), `navigator` (kid), `sprout` (kid). Data: seed through `storage` where the existing live tests seed (`library_run_fixture.py` for a library program with a run; projects as `test_projects_one_door_live.py` seeds them); mock with `page.route` what they mock: `api/kid-tasks?member_id=*` and `api/kid-tasks/classes?member_id=*` (two tasks, one class), `api/family/locations*` (two people), the music widget's reads (read `music_widget.html`'s `fetch(url)` callers: players with one playing track, two favorites, a search result), the pet reads (`api/pets/bundle`, `api/pets?member_id=*`, `api/pets/xp?member_id=*`). Screenshots to `tests/probe_shots/pwa_slice7` when `PWA_REVIEW_OUTPUT` is set (the slice 3–6 convention).

- [ ] **Step 1: Write the test** with scenarios:
  - (the checker itself) `checker_catches_a_grey`: inject a `<p class="text-gray-600">` into a `[data-pwa-skin]` host with the adult rules switched off (`dataset.audience='child'`) and assert `check_skin` reports it — so a green run means something.
  - `more_rows` (parent, light): `#pwa-more-title` text "More", 34px/700; the lead line muted; the searchbox's accessible name "Search features", border width 0, its `<label>` visually hidden (clipped, still in the accessibility tree); every `#pwa-feature-list .pwa-feature` has border widths 0, transparent background, height ≥ 56, a `.pwa-feature-icon` 44×44 with radius ≥ 12, a title span 16px/600, a `small` 14px in the muted ink, and a `.pwa-feature-chevron` whose right edge is within 24px of the row's right edge; at 360 px the School row's `small` wraps (height > one line) and is not ellipsized (`text-overflow` not `ellipsis`, `scrollWidth <= clientWidth`); search "map" leaves one row, "no-match-xyz" shows `#pwa-search-empty` in the muted ink; each row runs: map → `#map-container` visible and `#tab-more[aria-current="page"]`, music, library, school → `#pwa-school-overlay`, critter → `#pet-editor-panel` visible, profile → `#pwa-profile` open; screenshot `more-light.png`.
  - `profile_sheet` (parent): `#pwa-profile` background `--pwa-card-raised`, radius 22px, border 0; its rows are `.pwa-feature` rows with the same skin as More's; Appearance still cycles and stays open; screenshot `profile-light.png`.
  - `projects_both_doors`: parent via the Household card (`tests/pwa_projects_door.py`) → `check_skin(page, '#pwa-stack #projects-container', cards='[data-project-card]')`, the component's `.panel-page-title` hidden, the screen's h1 present; lists_only via More → `check_skin(page, '#projects-container', title='#projects-container .panel-page-title', cards='[data-project-card]')`; screenshot `projects-light.png`.
  - `library`: More › Library → `check_skin(page, '#library-container', title='#library-container .panel-page-title', cards=<the library card root class from library_card.html>)`; the primary action of a program card has background `--pwa-ink`; screenshot `library-light.png`.
  - `music`: More › Music → `#pwa-page-heading h2` "Music" 34px/700; `check_skin(page, '#music-container', title='#pwa-page-heading h2', raised='#mw-nowplaying')`; `#music-widget` itself transparent with border 0 (the page is the wash, not one big card); `#mw-playpause` background `--pwa-ink`; `#mw-search` border 0; favorites / results rows have no dividers (`border-top-width` 0); screenshot `music-light.png`.
  - `map`: More › Family map → `#family-map` height ≥ 300 and its box unchanged against a measurement taken with the stylesheet's adult rules removed (`document.documentElement.dataset.audience='child'` probe, then restored); `#family-map-chips` transparent over the wash with border 0; each chip a pill (radius ≥ 999 or ≥ half its height) with border 0 on `--pwa-card-raised`; contrast on the chips; screenshot `map-light.png`.
  - `school`: More › School (parent picks Maya through `promptChoice` when two children, or straight in with one) → `#pwa-school-overlay .pwa-sheet` background `--pwa-card-raised` (slice 0 already gives it border 0 and 22px top corners — those stay); `check_skin(page, '#pwa-school-overlay .pwa-sheet', cards=<the task row selector pwaSchoolRender draws>)`; a task opens its detail and Back/close returns; screenshot `school-light.png`.
  - `critter`: More › My critter → `#pet-editor-panel`'s dialog surface `--pwa-card-raised`, radius 22px, border 0; tabs/chips pills; the preview art's box unchanged (same probe as the map); save button background `--pwa-ink`; screenshot `critter-light.png`.
  - `contrast` (parent): every destination above again in dark at 390 and in light and dark at 360: `check_skin` with no failures; screenshots `*-dark.png`.
  - `sheets_still_open`: a project piece sheet, the Library run sheet, the School detail and the critter guide each open above their page, close back to it, and the body-appended `.pwa-sheet`s other than School's keep slice 0's skin (22px top corners at 390, background `rgb(var(--c-gray-900))`).
  - `other_hosts_untouched`: the source of `templates/*.html` other than `app.html` never names `pwa_shell.css`; navigator: More › School sheet has no `data-pwa-skin` and its background is `rgb(var(--c-gray-900))`; sprout: `#pwa-feature-list` is still `display: grid`; `served.errors()` empty for every profile.
- [ ] **Step 2: Run** `python tests/test_pwa_more_live.py` → FAIL at `more_rows` (the title reads "More from Chauffeur").
- [ ] **Step 3: After Task 4, run** it and `python tests/test_pwa_adult_shell_live.py` → green.

---

### Task 2: More and Profile in the new look (Codex)

**Files:**
- Modify: `chauffeur/templates/components/pwa_directory.html` (the `<label>` gets the visually-hidden class the app already uses — `sr-only` is in the precompiled sheet; the search sits in a `.pwa-directory-search` wrapper like `.pwa-conversation-search`), `chauffeur/static/pwa_shell.js` (`pwaFeatureButton` appends `<span class="pwa-feature-chevron" aria-hidden="true">` with `pwaIcon('arrow')`; `pwaSyncShell` sets `#pwa-more-title` to "More" for adults), `chauffeur/static/pwa_shell.css` (adult skin for `.pwa-directory`, `.pwa-feature`, `.pwa-profile`)
- Test: Task 1 `more_rows`, `profile_sheet`, `other_hosts_untouched` (sprout half); `tests/test_pwa_adult_shell_live.py`; `tests/test_pwa_nav.py`

**Interfaces:**
- `.pwa-feature` (adult): flex row, gap 14px, padding 10px 0, min-height 56px, no border, no background; `.pwa-feature-icon` 44×44, radius 14px, `--pwa-card-raised` with `0 2px 8px rgba(31,29,43,.06)` (Household's `.pwa-house-icon`), the glyph in `--pwa-accent`; title 16px/600 `--pwa-ink`; `small` 14px/400 `--pwa-msg-muted`, wraps, no clamp; `.pwa-feature-chevron` 20px `--pwa-msg-muted`, `margin-left: auto`, `flex-shrink: 0`; the copy `flex: 1; min-width: 0`. Kids hide `.pwa-feature-chevron` (`[data-child-stage] .pwa-feature-chevron { display: none }`), so their rows are unchanged.
- `#pwa-more-container` (adult): padding 12px 20px 28px; h2 34px/700/-.03em `--pwa-ink`; lead 16px `--pwa-msg-muted`; search input border 0, radius 12px, background `--pwa-msg-soft`, 15px, min-height 44px; `#pwa-search-empty` muted ink.
- `.pwa-profile` (adult): background `--pwa-card-raised`, border 0, radius 22px, `--pwa-ink`; its title 22px/700; rows as above (the existing `.pwa-sheet .pwa-feature` rule's border-bottom goes for adults).

- [ ] **Step 1: Implement**; `python tools/build_tailwind.py`.
- [ ] **Step 2: Run** `python tests/test_pwa_nav.py && python tests/test_pwa_adult_shell_live.py && python tests/test_pwa_more_live.py` → `more_rows`, `profile_sheet` green (the destination scenarios still red).

---

### Task 3: The shared destination skin; Projects and Library (Codex)

**Files:**
- Modify: `chauffeur/templates/app.html` (`data-pwa-skin` on `#projects-container`, `#library-container`, `#music-container`, `#map-container`), `chauffeur/static/pwa_shell.css` (the shared block + Projects + Library)
- Test: Task 1 `projects_both_doors`, `library`, `sheets_still_open` (project and library halves), `contrast` (those two); `tests/test_projects_live.py`, `tests/test_project_sheets_phone_live.py`, `tests/test_projects_one_door_live.py`, `tests/test_library_live.py`

**Interfaces — the shared map, `html[data-audience="adult"] [data-pwa-skin]`:**
- The host: background transparent (the wash shows), `color: var(--pwa-ink)`, padding 12px 20px 28px where the component brings none.
- Top-level cards — `:is(.bg-gray-900, .bg-gray-800).border` and `:is(.bg-gray-900, .bg-gray-800):is(.rounded-xl, .rounded-2xl)` that are not inside another card → `--pwa-card`, border 0, radius `--pwa-radius`, box-shadow none. Surfaces nested inside a card → the muted fill, border 0, radius 14px. (Codex: read each component, list which elements match, and add a component-specific selector where the class pattern catches a progress bar, a swatch or a divider by mistake.)
- Chips — `.rounded-full` elements with `.text-xs` or `.text-[11px]` → 12px/600 pill, muted fill, border 0.
- Buttons — `:is(.bg-teal-700, .bg-blue-600, .bg-emerald-600)` buttons → `--pwa-ink` fill, `--pwa-card-raised` text, radius 14px, min-height 44px (one primary per card; a second coloured button on the same card takes the secondary); bordered gray buttons → the muted fill, border 0.
- Type — `.panel-page-title` 34px/700/-.03em; `.uppercase` labels 12px/700 tracked `.08em` `--pwa-msg-muted`; `:is(.text-gray-400, .text-gray-500, .text-gray-600)` → `--pwa-msg-muted`; `:is(.text-white, .text-gray-100, .text-gray-200)` → `--pwa-ink`.
- Dividers — `.divide-y > *` border 0 with 4px spacing; `.border-b`/`.border-t` hairlines between rows → 0.
- Inputs and selects — border 0, radius 12px, `--pwa-msg-soft`, `--pwa-ink`.
- Projects: `[data-project-card]` is the card; inside the Household screen the existing slice-3 rules stay (title hidden, section unpadded). Library: the library card root (`library_card.html`) is the card; the run rows inside are the nested surface.

- [ ] **Step 1: Read** `projects_page.html`, `library_page.html`, `library_card.html` on the phone host and list the selectors each rule must reach (and must not).
- [ ] **Step 2: Implement**; `python tools/build_tailwind.py`.
- [ ] **Step 3: Run** `python tests/test_projects_live.py && python tests/test_project_sheets_phone_live.py && python tests/test_projects_one_door_live.py && python tests/test_library_live.py && python tests/test_pwa_more_live.py` → the projects and library scenarios green.

---

### Task 4: Music, Family map, School and the critter (Codex)

**Files:**
- Modify: `chauffeur/static/pwa_school.js` (`data-pwa-skin` on the School `.pwa-sheet` for adults only — `pwaIsAdult()` at build time), `chauffeur/templates/components/pet_editor.html` (`data-pwa-skin` on `#pet-editor-panel`; nothing else), `chauffeur/static/pwa_shell.js` (`pwaPageHeading`'s `names` gains `music: ['Music', 'Favorites and household listening.']`), `chauffeur/static/pwa_shell.css` (the four blocks; the adult `.pwa-page-heading h2` moves to 34px/700/-.03em with the other titles)
- Test: Task 1 `music`, `map`, `school`, `critter`, `contrast`, `sheets_still_open`, `other_hosts_untouched`; `tests/test_school_view_live.py`, `tests/test_family_map_live.py`, `tests/test_household_features_live.py` (its critter half), `tests/test_pwa_drive_live.py` (its `openPetEditor` use)

**Interfaces:**
- Music: `#music-widget` dissolves (transparent, border 0, shadow none, padding 0) so its parts sit on the wash; `#mw-nowplaying` is the one raised card (`--pwa-card-raised`, 22px, padding 16px, `0 10px 30px color-mix(in srgb, var(--pwa-accent) 18%, transparent)`) and shows only when it does today; `#mw-art` 14px corners; `#mw-playpause` the ink circle 48px; shuffle / repeat / queue icon buttons on the muted fill 44px; `#mw-queue`, `#mw-results`, `#mw-fav-tracks` → `--pwa-card` groups radius 18px, no outer border, no `divide-y` hairlines; favorites tiles 14px corners; `#mw-player` select and `#mw-search` per the shared inputs; the volume range accent `--pwa-accent`.
- Family map: `#map-container` keeps its full-bleed layout and `#family-map` its box; `#family-map-chips` transparent, border 0, padding 10px 12px; chips (`family_map_core.html` ~292) pills on `--pwa-card-raised`, border 0, 13px/600 `--pwa-ink`, the colour dot kept; no title (the map is the screen).
- School (adult sheet only): the sheet background `--pwa-card-raised` (slice 0's border 0 and corners stay); the sheet title 22px/700; agenda day labels 12px uppercase muted; task rows the nested surface (muted fill, 14px); the month grid's cells unchanged in size; the mode toggle a segmented control in the Household `.pwa-seg` style; chips per the shared map.
- Critter (adult panel only): the panel's dialog surface `--pwa-card-raised`, radius 22px, border 0; tabs and part chips pills; Save the ink primary, Cancel and the rest secondary; the preview art and the battle arena (`pet_battle.html`) untouched.

- [ ] **Step 1: Read** `music_widget.html`, `family_map.html` + `family_map_core.html`, `pwa_school.js`'s renderers, `pet_editor.html` and list the selectors.
- [ ] **Step 2: Implement**; `python tools/build_tailwind.py`.
- [ ] **Step 3: Run** `python tests/test_school_view_live.py && python tests/test_family_map_live.py && python tests/test_household_features_live.py && python tests/test_pwa_drive_live.py && python tests/test_pwa_more_live.py` → green (`test_household_features_live.py`'s admin chores 401 and wall board timeout are pre-existing red on main; every other scenario green).

---

### Task 5: Record it, gate it, ship it (Claude)

**Files:**
- Modify: `chauffeur/docs/ui_design_guide.md` ("More, a list; destinations take the vocabulary": the `data-pwa-skin` marker, the shared map, the per-destination exceptions, the contrast checker), `chauffeur/system_capabilities.md` (new top entry `v2.499.758`), `chauffeur/config.yaml` (→ `2.499.758`)

- [ ] **Step 1: Docs and version.** Look at every `tests/probe_shots/pwa_slice7` screenshot, light and dark, 360 and 390, before writing the entry.
- [ ] **Step 2: Gate** (from `chauffeur/`, `HA_BASE_URL` unset):

```bash
python tests/test_pwa_nav.py && python tests/test_template_js.py && python tests/test_tailwind_build.py && python tests/test_auth.py && python tests/test_pwa_more_live.py && python tests/test_pwa_adult_shell_live.py && python tests/test_pwa_household_live.py && python tests/test_pwa_myday_live.py && python tests/test_projects_live.py && python tests/test_project_sheets_phone_live.py && python tests/test_projects_one_door_live.py && python tests/test_library_live.py && python tests/test_school_view_live.py && python tests/test_family_map_live.py && python tests/test_pwa_drive_live.py
```

- [ ] **Step 3: Commit** as one commit `feat(pwa): slice 7 of the reimagined PWA, More and its destinations (v2.499.758)` and push.

---

## Sequencing calls (check these while reading)

1. **The destinations stay where they are** (spec "Inherited unchanged": builders and behaviour kept, vocabulary through shared CSS and nothing else). Library, Map and Music stay `setView` views with More highlighted; School stays a sheet; the critter stays its panel. Turning School or the critter into pushed screens is a later choice, not this slice.
2. **One marker, one map.** `data-pwa-skin` names a host that takes the vocabulary; the shared rules translate the components' Tailwind classes onto the adult tokens, so the next destination is one attribute plus its exceptions. The marker is on the phone's containers, not in the shared components (except the critter panel, whose root is the component, and the School sheet, built in JS), and the stylesheet is linked only by `app.html`.
3. **More's rows wrap, never ellipsize.** "One-line description" is the copy's length, not a clamp; a wrapped second line beats a hidden word.
4. **Profile takes the same rows** (it shares `pwaFeatureButton` and the inventory lists it under "Inherited unchanged").
5. **Music gets a page title; the map does not.** Music is a page of lists; the map is the screen, and a 34 px title would cost it a fifth of its height.
6. **The contrast check is a measurement, not a list of classes.** `check_skin` composites the real backgrounds over the wash and fails any visible essential line under 4.5:1, so a grey the shared map missed shows up as a named failure rather than a screenshot to squint at.
7. **Not this slice:** the lesson player, the trips and occasions sheets, the battle arena, kid stages, More grouping into sections, an avatar on the Profile row, device checks (slices 0–7 go to the device run next).
