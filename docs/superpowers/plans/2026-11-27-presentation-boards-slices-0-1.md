# Presentation boards, slices 0 and 1: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. In this repository the implementers are Codex and Gemini through the Product Hub launcher (see "Who builds what"); they do not commit.

**Goal:** Slice 0 makes links in every chat bubble clickable. Slice 1 lets Argyle end a mission with a typed, provenance-checked board that the family can open and read: a look-up tool, the `present` action, board storage, the board card, the board sheet, the project row, the image proxy, the spoken form and a demo shot.

**Architecture:** A new planner action `look_up` fetches a page and stores a lookup record (title, store, image, price), with no LLM involved. A new finishing action `present` names lookups by id. `services/boards.py` validates it against those records, stores a board, and posts a `board` card through the same recipients as `_dm_person`. The phone and admin pages render the board from one JSON view (`boards.view`) through one sheet component. Images only ever come through a server proxy that reads the lookup's own stored `image_url`.

**Tech Stack:** FastAPI (`chauffeur/main.py`), SQLite JSON doc tables (`services/storage_sqlite.py`), requests, Playwright Chromium (already in the add-on), Pillow (already in `requirements-twin.txt`, which the Dockerfile installs), Alpine and vanilla JS, precompiled Tailwind, and node-run JS tests.

**Spec:** `docs/superpowers/specs/2026-11-27-presentation-boards-design.md` (approved 2026-11-27). Read sections 3, 5, 6, 7.5, 8, 9 and 12 before your task.

## Who builds what (the Claude / Codex / Gemini split)

| Task | Owner | Worktree / branch | Why this owner |
|---|---|---|---|
| 0. Clickable links in chat | Codex | `../Chauffeur-chat-links` / `chat-links`, from `main`, lands on its own | small, test-first JS with node tests, no browser needed |
| 1. Contract: board view, card and row shapes, plus fixture tests | **Claude** | `Chauffeur-presentation-boards` / `presentation-boards` | contract-first seam between the two implementers |
| 2. Page look-up and lookup records | Codex | `../Chauffeur-boards-server` / `boards-server`, from `presentation-boards` after Task 1 | server, network guard, test-first |
| 3. Boards service: validate, store, view, card, spoken | Codex | same, continued | |
| 4. `present` in the mission engine | Codex | same, continued | engine integration, end-to-end mission test |
| 5. Routes, image proxy, project row, deletion, `board_view` tool | Codex | same, continued | |
| 6. Board card, board sheet, row, done-card line, deep link | Gemini | `../Chauffeur-boards-ui` / `boards-ui`, from `presentation-boards` after Task 1 | visual iteration, can drive Chromium |
| 7. Demo shot `board` | Gemini | same, continued | needs a browser |
| 8. Merge, browser checks, landing | **Claude** | `presentation-boards` | reviews, browser checks, landing |

- Tasks 2 to 5 (Codex) and 6 to 7 (Gemini) run in parallel. Both build against the Task 1 fixture, never against each other's code.
- Every task gets an independent review: diff file, brief and report. Fix rounds go back to the same implementer (`--resume-last`, or `--conversation <id>`) and end with a scoped re-review.
- Implementers leave changes in the working tree with a report file at `docs/superpowers/reports/<task>.md`. The report holds what changed, the tests run with their output, and a `## Hub updates` section. Claude commits.
- Slice 0 lands on `main` by itself as soon as it passes review. Slice 1 lands as one landing after Tasks 2 to 7 are merged into `presentation-boards`: a `board` card without the sheet would render as nothing, and `renderCard` returns `''` for unknown kinds.
- When work starts: `hub_note.py --project chauffeur --kind started --title "Presentation boards slices 0-1" --likely 2d --worst 4d --branch presentation-boards --by claude`.

## Global Constraints

- Tests run from `chauffeur/` as plain scripts: `python tests/test_x.py`, with `HA_BASE_URL` unset (`env -u HA_BASE_URL python tests/test_x.py` in Bash; `Remove-Item Env:HA_BASE_URL` in PowerShell). Each brief names its gate test files one by one. Never run the whole suite; never select tests by word match.
- Test style follows the neighbours: `from harness import check`, `scenario_*` functions, monkeypatch by assignment restored in `finally`, `_fresh()` resets from `tests/test_subjects.py`.
- The model never supplies a URL, image or price. Items reference lookups by id (spec 6.2, 6.3).
- New UI uses data attributes and delegated listeners only. No `onclick` with interpolated ids, because `mfEscape` does not escape `'` (spec 3).
- No `alert`, `confirm` or `prompt`. Page JS fetches `base() + 'api/...'`, never a root-relative `/api/...`.
- A control that cannot deliver is not drawn. In slice 1 the board is read-only: no Like, Keep, Find more, Copy or commit controls exist yet. `view.can.*` is all `false`.
- New settings go in `services/settings_registry.py` and the typed field in `models/schemas.py`, never `config.html`.
- After any template class change run `python tools/build_tailwind.py` from `chauffeur/`.
- Every new `/api/` route gets a `services/access_readers.READERS` row. The `/api/projects/*` auth rule (`services/auth.py:441`) already covers board routes.
- Everything degrades with no Home Assistant and no network: a failed look-up returns an error note to the planner, and a failed image returns 404, which the UI draws as a placeholder.
- Copy uses plain words. The card line format is exactly `"{n} {noun} · from {price}"`, or `"{n} {noun}"` when no item has a price. The `·` is U+00B7.
- Implementers do not bump `chauffeur/config.yaml` and do not commit.

## Review Focus

1. **Hostile page data.** A store page with `<script>`, quotes, `'` or a `javascript:` URL in `og:title`, `og:site_name`, `og:url` or `og:image`. Expected: the strings render as text, the stored `url` and `image_url` are http(s) only, and anything else is dropped at look-up time. Tests: Task 2 `scenario_rejects_non_http_urls`, Task 6 node hostile-string case.
2. **Look-up aimed at the household network.** `look_up` of `http://192.168.1.10/`, `http://localhost:8099/`, or a public URL that redirects to a private one. Expected: refused at every redirect hop, and no Chromium fallback for a refused address. Test: Task 2 `scenario_refuses_private_and_redirect_to_private`.
3. **A `parents`-audience board and a child.** A mission in a `parents` project presents. Expected: the child gets no card, a 404 from the board GET and the image route, no board row in rows, and `board_view` refuses. Tests: Task 5 `scenario_parents_board_hidden_from_child`, Task 4 recipient assertion.
4. **Mixed or missing prices.** Options where some items lack a price, or currencies differ. Expected: the option total is `null` (never a partial sum), "from" uses only complete totals, and the line drops "from" when none are complete. Test: Task 3 `scenario_totals_and_summary_line`.
5. **Deleting the project.** Deleting a project that holds a board. Expected: board rows, its lookups and its cached image folder are gone, and an old card's Open shows "This board is no longer available." rather than an error page. Tests: Task 5 `scenario_project_delete_removes_board_and_cache`, Task 6 sheet 404 state.

---

### Task 0: Clickable links in chat bubbles (slice 0) — Codex

**Files:**
- Create: `chauffeur/static/chat_links.js` (one global function `linkifyText(text) -> string`)
- Modify: `chauffeur/templates/app.html:5181` (bubble uses `linkifyText(m.body)` in place of `mfEscape(m.body)`); add `<script defer src="{{ 'static/chat_links.js'|ver }}"></script>` before `pwa_shell.js` (line 114)
- Modify: `chauffeur/static/pwa_school.js:115-118` (delete `schoolLinkify`; the caller at `:149` uses `linkifyText`)
- Test: `chauffeur/tests/test_chat_links.py` (node, through `tests/pwa_pure.py` `pure_source` / `run_node`)

**Interfaces:**
- Produces: `linkifyText(text: string) -> string`. Its output is safe HTML: the text is escaped like `mfEscape` plus `'` becoming `&#39;`, and each `https?://` run is wrapped as `<a href="URL" target="_blank" rel="noopener noreferrer" class="underline break-all">URL</a>`. The function defines its own escape and does not depend on `mfEscape`, so it loads before `app.html`'s inline script.

- [ ] **Step 1: Write the failing node tests** in `tests/test_chat_links.py`:
  - `scenario_wraps_url`: `linkifyText('see https://a.com/x')` contains `<a href="https://a.com/x" target="_blank" rel="noopener noreferrer"`.
  - `scenario_trailing_punctuation_outside`: `'go to https://a.com/x.'`, `'(https://a.com/x)'` and `'https://a.com/x, then'` give hrefs `https://a.com/x`, with `.`, `)` and `,` outside the `</a>`.
  - `scenario_escapes_before_matching`: `'<b>https://a.com/?q="x"&y=1</b>'`. There is no `<b>` element, the href is `https://a.com/?q=&quot;x&quot;&amp;y=1` with the quote ending the URL at the raw `"` (match on the raw text, then escape each piece), and the `</b>` stays text.
  - `scenario_single_quote_escaped`: `"it's"` yields `it&#39;s`.
  - `scenario_no_javascript_scheme`: `'javascript:alert(1)'` produces no `<a`.
  - `scenario_school_uses_shared_helper`: `pwa_school.js` source has no `schoolLinkify` and calls `linkifyText`.
  - `scenario_bubble_uses_shared_helper`: the `app.html` bubble line contains `linkifyText(m.body)`.
- [ ] **Step 2: Run** `python tests/test_chat_links.py`. Expected: FAIL (the file `chat_links.js` is missing).
- [ ] **Step 3: Implement `linkifyText`.** Split the raw text on `/https?:\/\/[^\s<>"']+/g`. Trim trailing `.,;:!?)]}` from each match, keeping a closing `)` when the match holds an unbalanced `(`. Escape every piece, then wrap the URL pieces.
- [ ] **Step 4: Run** `python tests/test_chat_links.py tests/test_template_js.py tests/test_mission_chat_card_render.py`, each file as its own process, in parallel. Expected: all PASS.
- [ ] **Step 5: Report.** Write `docs/superpowers/reports/task0-chat-links.md`. Claude then lands it on `main` under the AGENTS.md landing steps, with a `system_capabilities.md` entry and a demo shot only if the look changes (it does not: same bubble, links underlined).

---

### Task 1: The contract (Claude)

**Files:**
- Create: `chauffeur/tests/fixtures/board_view_v1.json`: one `options` board with 4 slots and 3 options. Option 1 has all prices in USD. Option 2 is missing one price. Option 3's title is the hostile string `Look "3" <script>x</script> it's`. The fixture also holds one `compare` board and one `list` board, the matching `card` payloads, one project `row`, and one `mission_done` card with a `boards` line.
- Create: `chauffeur/tests/test_board_contract.py`: it loads the fixture and asserts the key sets below, so a drift on either side fails one test that both sides run.
- Create: `chauffeur/services/boards_contract.py`: the key sets as frozen constants, imported by Task 3's `boards.view` tests and by this test.

**Interfaces (Produces, used by every later task):**

`boards.view(board, viewer) -> dict`, which is also the body of `GET /api/projects/{pid}/boards/{bid}`:
```
{"id","project_id","title","ask","layout":"options|compare|list","noun","commit",
 "version","copied_from":null,"summary_line",
 "slots":[{"id","role"}],
 "options":[{"id","title","note","round","total":{"amount","currency"}|null,
   "items":[{"id","slot_id","title","url","store",
             "image":"api/projects/<pid>/boards/<bid>/image/<lookup_id>"|null,
             "price":{"amount","currency"}|null,"facts":[{"label","value"}]}]}],
 "keeps":{},"shortlist":[],"reactions":{},
 "can":{"react":false,"keep":false,"find_more":false,"copy":false,"commit":false}}
```
- The board card (`ChatMessage.card`): `{"kind":"board","board_id","project_id","title","summary_line","kept":0,"hero":[<=4 image paths from option 1, nulls dropped],"note":null}`.
- The project row from `projects.rows`: `kind "board"`, `group "now"`, `title` = board title, `subtitle "<summary_line> · <k> kept"` (k only when > 0), `sheet {"kind":"board","id":<bid>,"project_id":<pid>}`, `actions []`.
- The `mission_done` card gains `"boards":[{"board_id","project_id","title"}]` (empty list when none).
- The phone event to open a board: `window.dispatchEvent(new CustomEvent('chf-board-open', {detail:{projectId, boardId}}))`. Deep link: `#board-<project_id>-<board_id>`. Ids are hex with no dashes.
- Image paths are relative (no leading slash), for ingress.

- [ ] **Step 1:** Write the fixture and `boards_contract.py` (`VIEW_KEYS`, `OPTION_KEYS`, `ITEM_KEYS`, `CARD_KEYS`, `ROW_SHEET_KEYS`, `CAN_KEYS`).
- [ ] **Step 2:** Write `test_board_contract.py`: `scenario_fixture_matches_contract` (every view, option, item, card and row in the fixture has exactly the constant key sets) and `scenario_image_paths_relative` (no image path starts with `/`).
- [ ] **Step 3: Run** `python tests/test_board_contract.py`. Expected: PASS.
- [ ] **Step 4:** Commit on `presentation-boards`: `docs: board view contract and fixture`. Write the Codex brief (Tasks 2 to 5) and the Gemini brief (Tasks 6 to 7) as files under `docs/superpowers/briefs/`, then create both worktrees from this commit.

---

### Task 2: Page look-up and lookup records — Codex

**Files:**
- Create: `chauffeur/services/net_guard.py`: `check_public(url: str, error=ValueError) -> str`, moved from `services/twin_material_sources.py:157-172`. Twin's `_check_public` becomes `return net_guard.check_public(url, error=DownloadError)`.
- Create: `chauffeur/services/page_lookup.py`
- Modify: `chauffeur/services/browse.py`: add `render_page(url: str, timeout_s: float = 20) -> Optional[tuple[str, str]]`, which returns `(final_url, html)`. It runs one `_launch()` and one `page.goto` with no agent turns, closes everything in `finally`, and returns `None` on any failure.
- Modify: `chauffeur/services/storage_sqlite.py:30` `INDEX_SPEC`: `"lookups": [["id"], ["mission_id"]]`. In `services/storage.py`, add `lookups_table = db.table('lookups')` beside the other tables (around `:518`).
- Modify: `chauffeur/services/settings_registry.py` (next to `:785`), with `_e('mission_cap_lookups', 'missions', 'Page look-ups per mission', 'Pages one mission may look up for a board (default 30).', page='work?tab=projects', anchor='missions-settings')`. In `models/schemas.py` (next to `:1624`): `mission_cap_lookups: Optional[int] = 30`.
- Test: `chauffeur/tests/test_page_lookup.py`

**Interfaces:**
- Produces: `page_lookup.look_up_page(url: str, mission_id: str) -> dict`. It returns `{"status":"ok","lookup":<compact>}` or `{"status":"error","note":"<plain sentence>"}`.
  - Compact form: `{"lookup":"lk_<10 hex>","title","store","price":<float|null>,"currency":<str|null>,"available":<bool|null>,"excerpt":<<=300 chars>}`.
- Produces: `page_lookup.get(lookup_id) -> Optional[dict]`, `page_lookup.for_mission(mission_id) -> list[dict]`, and `page_lookup.delete_for_mission(mission_id, keep_ids: set) -> int`.
  - The stored record: `{id, mission_id, url, final_url, title, store, image_url, price, currency, available, fetched_at}`.
- Produces: `page_lookup.extract(html: str, base_url: str) -> dict`. It is pure and returns `{canonical, title, store, image_url, price, currency, available, excerpt}`.

Extraction rules:
- `title`: `og:title`, else `<title>`, else the JSON-LD Product `name`. Collapse whitespace, max 140 chars.
- `store`: `og:site_name`, else the host without `www.`.
- `image_url`: JSON-LD Product `image` (the first one when it is a list or an object `url`), else `og:image`. Resolve against `base_url`. Keep it only if http(s).
- `price` / `currency`: JSON-LD `Offer` / `AggregateOffer.lowPrice` with `priceCurrency`, else the meta tags `product:price:amount` with `product:price:currency` or `og:price:amount` with `og:price:currency`. No other source counts.
- `available`: JSON-LD `availability` ending `InStock` is `true`, `OutOfStock` is `false`, anything else is `null`.
- JSON-LD can be an `@graph`, a list or nested. Find any `@type` equal to, or listing, `Product`.

Fetch rules:
- `requests.get` with a desktop Chrome user agent string, `allow_redirects=False`, following up to 5 hops by hand.
- `net_guard.check_public` runs on every hop. Timeout 12 s, body cap 2 MB.
- The Chromium `render_page` fallback runs only when the plain fetch got HTTP 401, 403 or 429, or a 200 with no title and no JSON-LD Product, and only for an address that passed the guard. Its `final_url` is guard-checked too.
- Cap: count the mission's existing lookups. At or over `settings.get('mission_cap_lookups', 30)` it returns the error note `"This mission has used its 30 page look-ups."`

- [ ] **Step 1: Write the failing tests:**
  - `scenario_extracts_jsonld_product`: a fixture HTML with `@graph` Product plus Offer gives title, store, image, `price 79.0`, `currency "USD"` and `available true`.
  - `scenario_meta_tag_price_fallback`.
  - `scenario_no_price_without_structured_data`: the text "$79" in the body gives price `None`.
  - `scenario_rejects_non_http_urls`: `og:image` set to `javascript:x` gives `image_url None`.
  - `scenario_refuses_private_and_redirect_to_private`: fake `requests.get` so the first hop 302s to `http://127.0.0.1/`. Expected: an error note, `render_page` never called, and no record stored.
  - `scenario_chromium_fallback_on_403`: the fake returns 403 and `browse.render_page` is faked to return product HTML. Expected: a record whose `final_url` comes from the render.
  - `scenario_cap`: 30 records already exist for the mission. Expected: an error note naming 30.
  - `scenario_compact_is_small`: `len(json.dumps(compact)) < 900`.
  - `scenario_twin_guard_unchanged`: `twin_material_sources._check_public('http://127.0.0.1/')` still raises `DownloadError`.
- [ ] **Step 2: Run** `python tests/test_page_lookup.py`. Expected: FAIL (the module is missing).
- [ ] **Step 3: Implement** `net_guard.py`, `page_lookup.py`, `browse.render_page`, the table, the index and the setting.
- [ ] **Step 4: Run** these files in parallel, one process each: `tests/test_page_lookup.py`, `tests/test_twin_material_sources.py`, `tests/test_storage_sqlite.py`, `tests/test_settings_registry.py`. Expected: all PASS. (If a named neighbour file does not exist under that name, say so in the report; do not substitute a word match.)

---

### Task 3: Boards service — Codex

**Files:**
- Create: `chauffeur/services/boards.py`
- Modify: `services/storage_sqlite.py` `INDEX_SPEC`: `"boards": [["id"], ["project_id"]]`. In `services/storage.py`: `boards_table = db.table('boards')`.
- Test: `chauffeur/tests/test_boards.py`

**Interfaces:**
- Consumes: `page_lookup.get`, `page_lookup.for_mission` (Task 2); `boards_contract` constants (Task 1).
- Produces:
  - `boards.build_from_present(action: dict, mission: dict) -> tuple[Optional[dict], Optional[str]]`. It returns `(board_fields, None)` or `(None, "<refusal note naming the problem>")`.
  - `boards.create(fields: dict) -> dict`. Ids are `uuid4().hex`; it sets `version 1`, `rounds [{mission_id, started_by, started_at, note:None, kept_at_start:{}}]`, `keeps {}`, `shortlist []`, `reactions {}`, `copied_from None` and timestamps.
  - `boards.get(board_id) -> Optional[dict]`, `boards.for_project(project_id) -> list[dict]` (newest first), and `boards.delete_for_project(project_id) -> list[str]` (deleted ids; also removes their lookups and `image_dir(bid)`).
  - `boards.view(board, viewer) -> dict`, `boards.card(board) -> dict` and `boards.row(board) -> dict`, in the Task 1 shapes. `can` is all `false` in slice 1.
  - `boards.summary_line(board) -> str`, `boards.spoken(board) -> str` and `boards.image_dir(board_id) -> str` (`os.path.join(os.path.dirname(storage.DB_PATH), 'board_images', board_id)`).
- The `present` action fields: `title` (required, at most 80 chars), `layout`, `noun` (optional plural word or words, letters and spaces, at most 20 chars, default `"options"`), `slots [{role}]`, `options [{title, note, items:[{slot:int, lookup:str, facts:[{label,value}]}]}]`, `commit`, `summary`, `next_action`.

Validation:
- The layout must be in `options|compare|list`; an unknown layout is stored as `list`.
- `commit` must be in `buy|book|contact|none`; anything else is stored as `none`.
- 2 to 8 options (a `list` board may have 1), 1 to 6 slots, 1 to 6 items per option, and at most 4 facts per item with label and value at most 40 chars each.
- Provenance (spec 6.2): an item's `lookup` must be a record in `page_lookup.for_mission(mission['id'])`.
  - Title, url (`final_url` or `url`), store, image and price come from the record.
  - Any model-supplied `url`, `image`, `price` or `store` key on the item is ignored.
  - An item whose lookup fails is dropped. An option that then lacks an item for any slot index it used (multi-slot boards only) is dropped.
  - Fewer than the minimum options left fails, with a note such as `"Look up every item you show. Items lk_9 and lk_10 are not lookups from this mission."`
- The board's `project_id` is `mission['project_id']`. With none, refuse with `"This mission has no project to hold a board."`

Totals:
- An option total is the sum of its item prices only when every item has a price and all share one currency. Otherwise it is `null`.
- `summary_line`:
  - "from" uses the minimum of complete totals for multi-slot boards, or the minimum item price for single-slot and compare boards;
  - price format: `$118` for USD whole amounts, `$118.50` otherwise, `118 EUR` for other currencies;
  - "from" is left out when there is no price or the minimum spans mixed currencies.
- `spoken`:
  - `"I found {n} {noun} for {title}, from {lo} to {hi} dollars. Open the board on your phone to pick."` when prices exist;
  - `", at {lo} dollars"` when lo equals hi;
  - no price clause otherwise;
  - the currency word is `dollars` for USD, else the code;
  - title lowercased only if it starts with "The ";
  - at most 2 sentences.

- [ ] **Step 1: Write the failing tests:**
  - `scenario_present_builds_from_lookups`: server-filled fields equal the lookup record's, and a model `url` key on an item is ignored.
  - `scenario_unknown_lookup_drops_item_and_option`.
  - `scenario_too_few_options_refuses_with_note`.
  - `scenario_limits` (9 options, 7 slots, 5 facts).
  - `scenario_unknown_layout_becomes_list`.
  - `scenario_totals_and_summary_line`: the fixture's prices give `"3 looks · from $118"`; with one price missing the total is `None`; with mixed currency there is no "from"; with no prices the line is `"3 looks"`.
  - `scenario_view_matches_contract`: key sets equal `boards_contract`, image paths match `api/projects/<pid>/boards/<bid>/image/<lookup_id>`, and every `can` value is `False`.
  - `scenario_spoken`: the exact strings above for priced and unpriced boards.
  - `scenario_delete_for_project_removes_lookups_and_dir`.
- [ ] **Step 2: Run** `python tests/test_boards.py`. Expected: FAIL.
- [ ] **Step 3: Implement** `boards.py` and the table.
- [ ] **Step 4: Run** `tests/test_boards.py`, `tests/test_board_contract.py` and `tests/test_page_lookup.py` in parallel. Expected: all PASS.

---

### Task 4: `look_up` and `present` in the mission engine — Codex

**Files:**
- Modify: `chauffeur/services/missions.py`:
  - the action schema in `_system_prompt` (`:174-193`) adds
    `'{"action":"look_up","url":"<a product or listing page you found>"}'`
    and
    `'{"action":"present","title":"<title>","layout":"options|compare|list","noun":"<plural, e.g. looks>","slots":[{"role":"<slot>"}],"options":[{"title":"<title>","note":"<one line>","items":[{"slot":0,"lookup":"<lookup id>","facts":[{"label":"<label>","value":"<value>"}]}]}],"commit":"buy|book|contact|none","summary":"<one line>","next_action":"<optional>"}'`;
  - the rules (`:194-241`) add the three prompt rules from spec 6.3 verbatim in meaning: "When the goal is to find, choose or compare things, end with present, not finish. Look up every item you will show. Never type a URL or price you did not get from a tool.", plus the layout guidance from spec 5 (the three bullet sentences);
  - `_apply_planner_action` (`:1610`) gets a `look_up` branch next to `research` (`:1746`) and a `present` branch next to `finish` (`:1822`);
  - `_land_finish(mission, res, *, next_action_rev=None, card=None)` and `_dm_person(mission, text, card=None)`: an explicit `card` replaces the computed one;
  - `_done_card` adds `boards`.
- Modify: `chauffeur/services/planned.py`: a running WORK stage may receive `present`. `planned.planner_action` (`:673`) routes it to `finish_work(mid, action)` with `found={"board_id": <id>}` after the board is created. The board card posts when the stage ends.
- Test: `chauffeur/tests/test_mission_present.py`

**Interfaces:**
- Consumes: `page_lookup.look_up_page` (Task 2); `boards.build_from_present`, `boards.create`, `boards.card` (Task 3).
- Produces: mission steps `{'kind':'tool','name':'look_up','args_json':{'url'},'result_json':<look_up_page result>}`, `{'kind':'note','name':'present_refused','result_json':{'note'}}` and `{'kind':'llm','name':'present','result_json':{...action, 'board_id'}}`.

Behaviour:
- `look_up` counts against the step cap like `research`, sits behind the same budget guard (`:1586`), and makes no pro call.
- `present` as the mission's final action:
  - it is refused with the existing open-stages note while plan stages are open (same rule as `finish`, `:1826`);
  - on a validation failure it adds `present_refused` with the note, and the planner tries again;
  - when a `present_refused` step already exists, the second failure lands as `finish` with `res['summary']`, so the mission ends with text;
  - on success it does what `finish` does: `_close(mid,'done',summary=...)`, the same draft and revision logic, then `_land_finish(mission, res, next_action_rev=rev, card=boards.card(board))`, so the card goes to exactly the `_dm_person` recipients, for planned and plain missions alike.
- Factor the shared tail of the `finish` branch (`:1843-1866`) into `_finish_tail(mission, res, card=None)` rather than copying it.

- [ ] **Step 1: Write the failing tests:**
  - `scenario_plain_mission_end_to_end`. Use the real tool registry. Fake `missions._llm` with a script: `research`, then `look_up` ×3, then `present`. Fake `web.research` and `requests.get` in `page_lookup` with product HTML, and capture `missions._post`. Expected: a board is stored with 3 options, server-filled fields, the mission is `done`, and exactly one post carries `card.kind == 'board'`, sent to the creator's DM.
  - `scenario_present_bad_url_drops_item`: a script item names `lk_fake`; that item is gone from the board.
  - `scenario_two_invalid_presents_fall_back_to_text`: no board, the mission is `done`, the summary is posted as text, and no board card is sent.
  - `scenario_parents_project_card_not_to_child`: a mission in a `parents` project started by a parent. The child's DM gets nothing.
  - `scenario_present_refused_with_open_stages`.
  - `scenario_work_stage_ends_in_board`: a planned mission whose work stage presents. The stage `found.board_id` is set, the board card posts, and the later `mission_done` card's `boards` names it.
  - `scenario_prompt_has_rules`: the `_system_prompt` text contains `"end with present, not finish"` and the `look_up` and `present` schema lines.
- [ ] **Step 2: Run** `python tests/test_mission_present.py`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** these files in parallel: `tests/test_mission_present.py`, `tests/test_missions_engine.py`, `tests/test_planned_missions.py`, `tests/test_planned_mission_cards.py`, `tests/test_mission_chat_cards.py`, `tests/test_mission_research_key.py`, `tests/test_browse_mission.py`, `tests/test_start_mission.py`. Expected: all PASS.

---

### Task 5: Routes, image proxy, project row, deletion, `board_view` — Codex

**Files:**
- Modify: `chauffeur/main.py`, next to the project routes (`:6638` `_project_for_actor`, `:6838` detail):
  - `GET /api/projects/{project_id}/boards/{board_id}`: `actor = _piece_viewer(request)`, `_project_for_actor(project_id, actor)`, board loaded and `board['project_id'] == project_id`, else 404 `"This board is no longer available."`. Returns `boards.view(board, actor)`.
  - `GET /api/projects/{project_id}/boards/{board_id}/image/{lookup_id}`:
    - same checks, and `lookup_id` must belong to an item on this board, else 404;
    - serves `image_dir(bid)/<lookup_id>.jpg` when cached;
    - otherwise fetches the lookup's stored `image_url` only (never a URL from the request), with `net_guard.check_public` on every hop, timeout 12 s, 5 MB cap and an `image/*` content type;
    - downscales with Pillow to an 800 px long edge, RGB, JPEG quality 82, writes the cache, then serves;
    - `Cache-Control: private, max-age=86400`; any failure returns 404.
- Modify: `chauffeur/services/projects.py` `rows` (`:1625`): append `boards.row(b)` for each `boards.for_project(project['id'])` when `can_see`.
- Modify: `chauffeur/services/deletion.py` `_cleanup` (`:404`):
  - a project record calls `boards.delete_for_project`;
  - a mission record calls `page_lookup.delete_for_mission(mid, keep_ids=<lookup ids used by any surviving board>)`.
- Modify: `chauffeur/services/agent_tools_v2.py`: a read tool `board_view(board_id: str = None)`. With no id it reads the newest board on the thread in focus. It refuses unless `projects.can_see(project, acting_member)` and returns `{"status":"success","spoken":boards.spoken(b),"title","summary_line","project_id","board_id"}`.
  - Register it in `services/voice_tools.TOOLS`, with a `row_checks_after` rule that returns `False` (not speech-safe) when the board's project audience is not `household`.
  - It is a read tool, so add it to `missions.READ_TOOLS` only if the planner should read boards. **Do not** add it (YAGNI); it is excluded by default.
- Modify: `chauffeur/services/access_readers.py`: rows `((R,'GET','/api/projects/{project_id}/boards/{board_id}'),'4.1-signed-in',('thread','mission','program'),'projects.can_see')`, the same for `.../image/{lookup_id}`, a `T` row for `board_view`, and `F` rows for `boards.view` / `boards.for_project` if `scenario_every_function_reader_is_classified` asks.
- Test: `chauffeur/tests/test_board_routes.py`

**Interfaces:**
- Consumes: Tasks 2 and 3.
- Produces: the two routes, the `board` row in `GET /api/projects/{pid}` `rows`, and the `board_view` tool.

- [ ] **Step 1: Write the failing TestClient tests:**
  - `scenario_get_board_view`: 200, and the body matches the contract.
  - `scenario_board_in_other_project_404`: the right board id under the wrong project id gives 404.
  - `scenario_parents_board_hidden_from_child`: the GET, the image route and the rows all hide it from a child.
  - `scenario_image_cached_and_downscaled`: fake the fetch to return a 2000×1000 PNG. Expected: a JPEG with an 800 px wide body, a cache file written, and the second request served without a fetch.
  - `scenario_image_only_from_lookup`: a lookup id not on the board gives 404, and a query string `?url=` is ignored.
  - `scenario_image_private_address_404`.
  - `scenario_project_row_present`.
  - `scenario_project_delete_removes_board_and_cache`: through `deletion.delete('project', pid)`.
  - `scenario_board_view_tool_audience`: a child asking about a `parents` board is refused, a `household` board is speech-safe, and a `parents` board seen by a parent is not speech-safe.
- [ ] **Step 2: Run** `python tests/test_board_routes.py`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** these files in parallel: `tests/test_board_routes.py`, `tests/test_boards.py`, `tests/test_access_register.py`, `tests/test_projects.py`, `tests/test_projects_audience.py`, `tests/test_deletion_cleanup.py`, `tests/test_deletion_core.py`, `tests/test_registry_parity.py`, `tests/test_app_voice.py`. Expected: all PASS. (`test_access_register.py` also proves the auth classification.)
- [ ] **Step 5: Report** for Tasks 2 to 5 in `docs/superpowers/reports/boards-server.md`, with each gate's output.

---

### Task 6: Board card, board sheet, row, done-card line, deep link — Gemini

**Files:**
- Create: `chauffeur/templates/components/board_sheet.html`: one builder for phone and admin. A full-screen overlay listens for `chf-board-open`, fetches `base() + 'api/projects/' + pid + '/boards/' + bid` and renders by layout:
  - `options`, layout B from mockup version 2 (https://claude.ai/artifact/Aq5iMBLwGdMc3ZDopSUtt6):
    - one option per screen, swipe or arrow keys between options, plus a dot pager;
    - a hero collage from the option's item images (1 to 4 tiles, laid out client-side, a neutral placeholder tile on a 404);
    - title, note and total (`$167`, or none when `null`);
    - item rows: thumbnail, title, store, price, and a link out (`target="_blank" rel="noopener noreferrer"`) labelled with the store;
    - facts as small label/value pairs;
  - `compare`: a table, one column per item, rows for price, store and each fact label, column headers linking out;
  - `list`: a checklist look (read-only boxes in slice 1) with title, store, price and link.
  - Header: board title and `summary_line`, with a close button. Escape closes.
  - States: loading, and 404 showing `"This board is no longer available."`.
  - No Like, Keep, Find more, Copy or commit controls (every `can` flag is false; draw a control only when its flag is true, which no slice 1 view sets).
- Modify: `chauffeur/templates/app.html`:
  - `renderCard` (`:5770`) gains `if (card.kind === 'board') return renderBoardCard(card);`;
  - new `renderBoardCard(card)`: title, a hero strip of up to 4 `card.hero` images, `summary_line`, `"{kept} kept"` only when > 0, and an Open button `data-board-open data-project-id data-board-id`;
  - one delegated `click` listener on `document` for `[data-board-open]` dispatches `chf-board-open`;
  - `renderMissionDoneCard` (`:5821`) adds one line per `card.boards` entry, with the board title and an Open button using the same data attributes;
  - include `components/board_sheet.html`;
  - deep link: on load and on `hashchange`, `#board-<pid>-<bid>` dispatches `chf-board-open`.
- Modify: `chauffeur/templates/components/projects_page.html` `openRow` (`~:541`): `r.kind === 'board'` dispatches `chf-board-open` with `r.sheet.project_id` and `r.sheet.id`. Modify `templates/components/projects_admin.html` to include `components/board_sheet.html`.
- Run `python tools/build_tailwind.py`.
- Test: `chauffeur/tests/test_board_render.py`, a node run using the chunk technique of `tests/test_mission_chat_card_render.py:38-45` for `renderBoardCard` and the done-card line, plus a jsdom run of the sheet's render functions over every fixture board.

**Interfaces:**
- Consumes: only `tests/fixtures/board_view_v1.json` (Task 1). Stub `fetch` with the fixture; do not wait for Codex's routes.

- [ ] **Step 1: Write the failing node tests:**
  - `scenario_card_renders`: title, `summary_line`, up to 4 `<img>` with relative `src`, and the Open button's data attributes.
  - `scenario_card_hostile_strings`: the fixture's option 3 title and a store `O'Neil "&" <b>` render as text, with no `<script>` element, no `onclick` attribute anywhere in the output, and `'` unable to break an attribute.
  - `scenario_sheet_options_compare_list`: each fixture board renders, the options board shows 3 screens, a `null` total shows no price, the compare board has one column per item, and every outbound link has `rel="noopener noreferrer"`.
  - `scenario_sheet_draws_no_controls_when_can_false`: no element carries a `data-board-react`, `data-board-keep`, `data-board-more`, `data-board-copy` or `data-board-commit` attribute.
  - `scenario_done_card_board_line`.
  - `scenario_deep_link_parses`: the hash `#board-abc-def` yields `{projectId:'abc', boardId:'def'}`, and a malformed hash yields nothing.
- [ ] **Step 2: Run** `python tests/test_board_render.py`. Expected: FAIL.
- [ ] **Step 3: Implement**, following `docs/ui_design_guide.md` (Adult PWA presentation and vocabulary sections) and the shared builders it names.
- [ ] **Step 4: Visual pass in Chromium.** Serve the page with the fixture stubbed and capture at 390×844 (phone) and 1280×800 (admin): an options board on screens 1 and 3, compare, list, the card in a chat thread, and the 404 state. Save the captures to `docs/superpowers/reports/boards-ui/`. Revise against mockup version 2 for up to 3 rounds.
- [ ] **Step 5: Run** these files in parallel: `tests/test_board_render.py`, `tests/test_board_contract.py`, `tests/test_mission_chat_card_render.py`, `tests/test_planned_mission_cards.py`, `tests/test_template_js.py`, `tests/test_pwa_argyle.py`, `tests/test_projects_detail_live.py`. Expected: all PASS.

---

### Task 7: Demo shot `board` — Gemini

**Files:**
- Modify: `chauffeur/tools/demo_seed.py`: `seed_board()` writes the following.
  - An invented project, "Demo concert outfit", with audience `household`.
  - 12 lookups: invented store names, `https://demo.invalid/...` URLs and prices.
  - One `options` board with 4 slots and 3 looks, created through `boards.create` and `boards.card`, with its card posted in a demo Argyle DM.
  - Product photos are generated with Pillow (flat, silhouette-style product tiles, one per lookup), written straight into `boards.image_dir(bid)/<lookup_id>.jpg`, so the image route never fetches. No real store pages and no real products.
- Modify: `chauffeur/tools/demo_capture.py`: `'board'` goes in `OPT_IN_SHOTS` (`:39`). The readiness branch (pattern at `:146-154`) opens the phone app at `#board-<pid>-<bid>` and counts as ready when the sheet shows look 1 with all hero images loaded (`img.complete && naturalWidth > 0`).
- Test: run the shot.

- [ ] **Step 1:** Implement `seed_board()` and the shot.
- [ ] **Step 2: Run** `python tools/demo_capture.py --shot board --timeout 240 --out <dir>`. Expected: `board.png` showing look 1 with 4 real-looking tiles, totals and stores. Attach it to the report.
- [ ] **Step 3: Report** for Tasks 6 and 7 in `docs/superpowers/reports/boards-ui.md`, with captures, test output and `## Hub updates`.

---

### Task 8: Merge, browser checks, land (Claude)

- [ ] **Step 1:** Review both reports and diffs (independent review agent per half: diff file, brief, report). Fix rounds go back to the implementers and end with a scoped re-review.
- [ ] **Step 2:** Merge `boards-server` and `boards-ui` into `presentation-boards`. Rebuild Tailwind if both touched it.
- [ ] **Step 3: Gate**, in parallel, one process each: `test_board_contract.py`, `test_page_lookup.py`, `test_boards.py`, `test_mission_present.py`, `test_board_routes.py`, `test_board_render.py`, `test_access_register.py`, `test_missions_engine.py`, `test_planned_mission_cards.py`, `test_mission_chat_card_render.py`, `test_template_js.py`, `test_projects.py`, `test_deletion_cleanup.py`, `test_twin_material_sources.py`.
- [ ] **Step 4: Browser check on the real app with demo data.**
  - Run the end-to-end mission with faked web, then confirm the card shows in the Argyle DM.
  - Open it and check the sheet on phone width; check the project row in Projects on admin and phone.
  - Check the deep link, and the child account seeing nothing on a `parents` board.
  - Report the cost: requests per sheet open (1 view plus at most 4 images per screen), the image cache size per board, and the number of Chromium fallbacks during the run.
  - Send the owner the card and sheet captures next to mockup version 2.
- [ ] **Step 5: Land** under the AGENTS.md steps: merge `main`, gate, run `bump_version.py`, add the `system_capabilities.md` entry, commit, `--ff-only`, push, remove the worktrees. Then send `hub_note.py --kind shipped --version <v>` and update the `presentation-boards` memory with the hand-off for slice 2.

## Calls made in this plan (beyond spec section 13)

- The look-up is a planner **action** `look_up`, like `research`, not an agent registry tool. This keeps it mission-only, so Argyle chat cannot make lookups outside a mission.
- `present` gains an optional `noun` ("looks", "camps"), so the card can say "3 looks". The default is "options".
- The deep link is `#board-<project_id>-<board_id>`, not the spec's `#board-<id>`. Board routes sit under the project, so the link carries both ids.
- `board_view` (spec 7.3) ships in slice 1, read-only, so the spoken form has a caller. `board_find_more` and `board_keep` stay in slice 2. Speech is allowed only for `household` boards.
- The private-address guard moves out of the twin library into `services/net_guard.py` and is shared.
- The demo shot is opt-in, like the other recent shots.
