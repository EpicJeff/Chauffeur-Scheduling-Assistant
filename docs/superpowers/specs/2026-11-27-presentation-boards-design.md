# Presentation boards: Argyle shows options and the family answers back

Status: design, awaiting owner approval (2026-11-27). Branch `presentation-boards`.
Mockups the owner reacted to: https://claude.ai/artifact/Aq5iMBLwGdMc3ZDopSUtt6 (version 1 = layouts A/B/C, version 2 = B with Keep).

## 1. Intent

A project like "find an outfit for a band concert: black dress, or black button-down and skirt, black tights, black 2-inch heels" ends today with a blob of text in chat. URLs are not clickable, options are not grouped, nothing can be answered except by typing. Dots and Muse present the same request as outfits with clickable items, a look book page, and price watching.

The owner does not want a look-book tool. The owner wants a **general** presentation layer, so Argyle can decide how to show the results of **any** request where things are found, shown to the family, and the family answers back: an outfit, birthday venues, summer camps, a plumber, three recipes, a trip.

Owner's words that set the shape:
- "It should be general so the agent can intelligently decide how to use what is available for any request."
- Reactions are "more like a poll than a decision". The decision to buy is "something only the parent can do".
- "There shouldn't be a More like look 2 button unless tapping it will result in more options like look 2."
- Layout B (one option per screen), "with the ability to keep individual items from a look ... if I say find more options, it keeps the things I liked and builds new options around those. Sort of mix and match and drilling down."
- Per-person trays are "super complicated"; instead, "an option to break it out into a new private project ... when it starts as a shared project".

## 2. Goals, non-goals, anti-goals

Goals
- A small typed vocabulary of presentation pieces that Argyle fills and Chauffeur renders with shared builders.
- Argyle picks pieces and layout per request; the server validates and falls back to text.
- Every link and photo on a board comes from a page a tool actually fetched in that mission.
- People react (poll), keep items (shared tray), ask for more (new search round around the keeps), copy the board into their own private project, and, where their role allows, commit (buy, book, contact).
- Clickable links in every chat bubble.

Non-goals (this design)
- Price watching and promo codes. They need wake conditions (subject model slice 3). Section 10 sketches where they plug in.
- Map and timeline pieces. The vocabulary is built so they add without a schema break.
- Automated checkout. Payment is its own approval slice; "Buy" in v1 produces a purchase checklist (section 7.6).
- A wall-panel surface. No panel shows projects or missions today.

Anti-goals (failure even if it works)
- Model-written HTML or styling. The model never controls markup.
- A link or price the model made up. A plausible fake product URL is worse than the text blob.
- A control that cannot deliver what it says (the "More like this" rule, applied to every control).
- Generated product imagery. A rendered outfit shows things nobody can buy.
- Reactions that act as decisions, or that start paid work.
- A second agent stack or a board-only planner. Boards ride the existing mission engine.

## 3. Constraints from the codebase

- The planner returns one JSON action per step (`services/missions.py:174-193`); finish carries only `summary`, `next_action`, `next_action_at`. Research results reach the planner as JSON clipped to 900 chars (`_compact`, `missions.py:246-253`); `web.research()` returns `facts[{claim,url}]` and `sources[{title,url}]` with no images or prices (`services/web.py:554-669`). Browse reports carry `learned`, `stopped_at`, and per-turn URLs, no product data (`services/browse.py:1440-1443`).
- `mission_done` cards are posted only for planned missions (`missions.py:543-544`); plain missions finish with a text DM.
- A done mission refuses `missions.answer` (`missions.py:919-920`). A new round must be a new mission; `start_mission_for` reuses a focus thread with no live mission (`services/agent_tools_v2.py:2196-2212`).
- Chat cards: `ChatMessage.card` dict, posted via `_post_chat_message` / `missions._post`, rewritten in place with `storage.update_chat_message_card`, clients refetch on `_push_message_event`. Phone renders through `renderCard` in `templates/app.html:5770`; `static/pwa_argyle.js` reuses it.
- `mfEscape` does not escape `'` and existing cards interpolate ids into single-quoted `onclick`. New UI uses data attributes and delegated listeners only.
- Projects: one builder `templates/components/projects_page.html` for admin and phone. `projects.can_see`, `can_act`, `can_edit_audience`; route helper `_project_for_actor`. Audiences `household | parents | shared | private`; a child's private project includes parents.
- Auth: `/api/projects/*` and `/api/missions/*` are already `SIGNED_IN` in `services/auth.RULES`; every new route also needs a `services/access_readers.READERS` row (`tests/test_access_register.py`).
- Caps: launch cap, step cap, pro-call cap, browse-turn cap, monthly research cap; preconditions `missions_enabled`, the paid key, `web_research_enabled`.
- No speech path turns cards into words today; phone speech only plays replies flagged `phone_speech_safe`.
- Standing rules: no browser dialogs; new settings in `settings_registry.py`; precompiled Tailwind; HA-free degradation; every agent capability has a hand path; a new visible surface adds a demo shot.

## 4. Approaches considered

1. **One tool per experience** (look-book tool, venue-compare tool). Polished for the cases built, a text blob for everything else. Rejected: the owner asked for general.
2. **Model-generated pages** (artifact style HTML in a sandbox). Unlimited expression, but no audience checks inside it, no design-guide consistency, taps cannot reliably reach the mission, no spoken form, token cost per render. Rejected.
3. **Typed blocks** (chosen). The model composes from a fixed vocabulary; Chauffeur owns rendering, links, permissions and input. Same pattern as Adaptive Cards or A2UI. The owner picked general, which is this approach.

Layout: the owner picked **B** (one option per screen, hero plus item list) with **per-item Keep** borrowed from C (lanes).

## 5. The vocabulary (schema v1)

A **board** belongs to one project and holds one presentation that grows over rounds.

```
board
  id, project_id, thread_id, title, ask (the original request in words)
  layout: "options" | "compare" | "list"
  slots: [ {id, role} ]                    # "options" only; one slot = single-item options
  options: [ option ]
  commit: "buy" | "book" | "contact" | "none"
  keeps: { slot_id -> item_id }            # shared tray, see 7.2
  shortlist: [item_id]                     # single-slot boards, see 7.2
  reactions: { option_id -> {member_id -> "like" | "drop"} }
  rounds: [ {mission_id, started_by, started_at, note, kept_at_start} ]
  version, copied_from (board id or null), created_at, updated_at

option
  id, title, note (one line, optional), round (index), items: [item]

item
  id, slot_id, title, url, store, image (lookup id or null),
  price {amount, currency} or null,
  facts: [ {label, value} ]  (max 4, e.g. Dates / Ages / Distance / Rating)
  lookup_id                                  # provenance, see 6.2
```

Layouts and when Argyle uses each (these words go into the planner prompt):
- **options**: alternatives a person chooses among. With several slots, an option is a set that goes together (an outfit, a trip day, a party package) and the total shows. With one slot, each option is one thing (a camp, a plumber, a recipe).
- **compare**: a few things judged on the same attributes (three camps by dates, ages, cost, distance). Renders as a table; each column is an item; Keep works per column.
- **list**: things to gather or do, not to choose among (a packing list with links). Renders as a checklist.

Rendering for the owner's chosen B layout (`options`): one option per screen, swipe between them, a hero collage built from the option's real item photos (no generated imagery), the items listed with store, price, link and a Keep toggle, the poll line, Like / Drop on the whole option, the commit control where allowed, the tray at the bottom. Mockup version 2 is the reference.

Map and timeline are later layouts; `layout` is an enum the renderer falls back from (unknown layout renders as `list`).

## 6. How Argyle produces a board

### 6.1 A product look-up tool

New mission tool `look_up_page(url)`: fetches the raw HTML (not `web._fetch`, which strips tags and returns no final URL) with a normal browser user agent, following redirects and recording the final URL; private and loopback addresses are refused. When the plain fetch is refused or the page carries no product data (script-rendered stores), it falls back to rendering the page in the add-on's Chromium (the browse runner's browser, one page load, no agent turns) and reads the same tags from the rendered DOM. It extracts without an LLM:
- canonical URL, `og:title` / `<title>`, `og:site_name` (store),
- `og:image` and schema.org `Product` / `Offer` JSON-LD (`image`, `price`, `priceCurrency`, `availability`),
- a short text excerpt for the planner.

It stores a **lookup record** `{id, mission_id, url, final_url, title, store, image_url, price, currency, fetched_at}` and returns a compact view to the planner (not clipped by `_compact`: the planner gets the lookup id, title, store, price). It counts against a new per-mission cap (`mission_cap_lookups`, default 30) and the existing step cap. No pro-model call.

### 6.2 Provenance rule

- An item's `url` must equal the `final_url` or `url` of a lookup record in the **same mission**, or of a lookup carried over from an earlier round on the same board (kept items).
- `image` is the lookup's `image_url`, never a model-supplied URL.
- `price` comes only from the lookup's structured data (JSON-LD `Offer` or product meta tags). A browse `LEARNED:` value is not tied to a page and does not count. A model-stated price is dropped; the item shows no price.
- An item that fails provenance is dropped from the option; an option left with an empty slot it needs is dropped; a board left with no options fails validation.

### 6.3 The `present` action

A new planner action, a finishing action alongside `finish`:

```
{"action":"present","title":"Concert outfit","layout":"options",
 "slots":[{"role":"Dress or top"},{"role":"Skirt"},{"role":"Tights"},{"role":"Heels 2\""}],
 "options":[{"title":"Look 1","note":"Midi dress, opaque tights, block heel",
   "items":[{"slot":0,"lookup":"lk_12","facts":[]}, ...]}],
 "commit":"buy","summary":"Three looks from $118 to $167.","next_action":"Pick or keep pieces"}
```

Items reference lookups by id; the server fills title, url, store, image and price from the lookup. The model supplies only structure, titles, notes, slot assignment and facts.

Validation in `services/boards.py`: schema check, provenance (6.2), limits (2 to 8 options per round, 1 to 6 slots, 1 to 6 items per option; a dress-or-shirt alternative is expressed as different options, not optional slots). On failure the planner gets one refusal note naming the problem; a second failure falls back to `finish` with the summary text, so the mission never ends with nothing.

Prompt rules added to the planner: when the goal is to find, choose or compare things, end with `present`, not `finish`; look up every item you will show; never type a URL or price you did not get from a tool.

`present` lands like `finish` (`_land_finish` path: thread next step, history entry) and additionally creates or updates the board and posts the board card (6.4) to the same recipients `_dm_person` uses, **for any mission, planned or not**.

Planned missions: a WORK stage may end with `present` in place of `stage_done` (its board is that stage's result; the stage's `found` records the board id). The board card posts when the stage ends. The mission's later `mission_done` card is unchanged apart from one line naming the board with an Open button. `present` is refused as the mission's final action while plan stages are open, like `finish`.

How the server tells a Find more round from a new board: the mission carries `board_id` when it is launched as a round (7.3); its `present` appends to that board. A mission without `board_id` makes a new board.

### 6.4 The board card in chat

New card kind `board`: title, a small hero collage from the first option, "3 looks · from $118", the kept count, and one Open button. Rendered by a new branch in `renderCard`, shared with the Argyle panel. Taps use data attributes only. When the board changes (new round, keeps), the existing card is rewritten with `update_chat_message_card` and the usual message event; a new round also posts one new card ("3 more looks around your kept dress and heels").

### 6.5 Spoken form

`boards.spoken(board)`: one or two sentences ("I found three looks for the concert outfit, from 118 to 167 dollars. Open the board on your phone to pick."). Nothing speaks a mission DM that arrives later, and this design adds no such path. Voice-origin missions get the normal text DM plus the board card, like any other mission. The spoken form is used when someone asks Argyle by voice about a board that exists ("what did you find for the concert?"), flagged `phone_speech_safe` only when the project's audience allows it on that device.

## 7. What people do on a board

All routes live under `/api/projects/{pid}/boards/{bid}/...` (covered by the existing projects auth rule; each gets an `access_readers` row). Every write takes the board `version` and returns 409 with "The board changed; look again." on a stale version.

### 7.1 Who can do what

- **See**: `projects.can_see`.
- **React, keep, find more, copy**: anyone who can see the board, kids included (owner ruling 2026-11-27: a poll is open to everyone who sees it; the kid an outfit is for must be able to react on a parent's project). Find more has its allowance rules in 7.3.
- **Commit**: parents only for `buy`; `can_act` for `book` and `contact`, inside the existing approval gates.
- A control a viewer cannot use is not drawn. The server refuses it anyway.

### 7.2 Reactions and the Kept tray

- **Like / Drop** on an option: per person, toggles, shown as the poll line ("♥ Kid · ♥ Parent"). Never starts work. A dropped option folds behind "Dropped (2)" at the end of the swipe for everyone; it can be brought back.
- **Keep** on an item: one shared tray per board.
  - Multi-slot boards hold one kept item per slot. Keeping a second item for a slot replaces the first, with an Undo toast.
  - Single-slot boards and `compare` boards: Keep is a shortlist, any number.
  - Anyone in 7.1 can keep or un-keep. No per-person trays (owner ruling); the tray shows nothing about who kept what.

### 7.3 Find more

- **Its own allowance.** Rounds do not use the household's mission launch cap. They count against a new setting `board_rounds_per_day` (default 6, household-wide, in `settings_registry.py` beside the mission caps) and the monthly research cap.
- **No blind limits** (owner ruling 2026-11-27: "I don't like blind limits with no way of overriding"). The button's state, from `boards.search_state(board, viewer)`:
  - *Room left*: "Find more". Anyone in 7.1 taps it and the round starts. This includes kids, who cannot start missions anywhere else.
  - *Allowance or research cap spent, viewer is a child*: the button reads "Ask a parent for more". The tap sends an approval card to the parents through the action-proposal rail (`create_action_proposal`, new type `board_round`): "Kid wants more looks for Concert outfit: Approve / Not now", with the kid's note if they typed one. Approve runs that one round over the limit.
  - *Allowance or research cap spent, viewer is a parent or adult*: the button reads "Find more (over today's limit)". The tap confirms in the page with `promptConfirm` ("Today's 6 rounds are used. Run one more?") and runs the round.
  - *Nothing can run* (missions off, no paid key, research switched off): no button, because no tap could deliver. A parent sees one line naming the switch, linking to where it is turned on.
  - *A round is live on this board*: "Finding more…", disabled. It is the same control, not a second one. A kid's request already waiting reads "Asked a parent".
- **Find more** (tray-level) launches a new mission on the board's thread through the `start_mission_for` checks. Its goal is composed by the server: the original ask, the kept items as locked (title, store, price, url), the open slots to fill, liked and dropped options as signals, and an optional typed note ("cheaper shoes").
- **More like this** on an option is the same round with that option as the style anchor.
- **Saying it works too.** The board card puts its thread in focus, as mission cards do. Three agent tools act on the board in focus or a named one, each with the same permission checks as the taps: `board_find_more(board, note)` ("find cheaper shoes"), `board_keep(board, item)` ("keep the block heels"), and `board_view(board)` (read it back, using the spoken form by voice). A typed or spoken "find more" on a focused board is a round on that board, never a new board. Reactions stay taps.
- A board with no thread of its own (a copy, a manual mission) gets one on its first round.
- The new mission's `present` **appends** options to the same board (new `round` index), keeps the tray, and the kept items are reused from their lookups (no re-fetch unless older than 24 hours, then one re-check of price and availability). The swipe opens on the first new option.

### 7.4 Make my own copy

- On a board in a non-private project, "Make my own copy" creates a new private project owned by the tapper (audience rules as for any project they create, so a kid's private project includes parents) with a copy of the board as it stands: options, tray, poll, rounds history, lookups.
- The copy shows "Copied from: Concert outfit" (a link only if the tapper can still see the source). It never syncs back. Copying runs no search.

### 7.5 Where the board lives

- A full-screen **board sheet** component (`templates/components/board_sheet.html`), one builder for the phone and the admin page, opened from the board card and from the project.
- The project detail gets a **board row** in Now ("Concert outfit · 6 looks · 2 kept"), built in `projects.rows`, opening the sheet. A project can hold more than one board (each `present` that is not a Find more round makes a new one).
- Deep link `#board-<id>` opens the sheet in the phone app.

### 7.6 Commit

`commit` is chosen by the planner from the fixed list and drawn only where 7.1 allows.
- **buy** (v1): "Buy this look" (or "Buy this" for one item) records the decision on the board, posts a line to the thread, and adds a **purchase checklist** to the project's Now list, one row per item with store, price and link, ticked by hand when bought. No automated checkout until the payment slice.
- **book / contact**: launches a mission to do it ("Book Camp X for week 2"), which runs through the existing release asks and submit gate (Book it / Not this / Stop). Nothing new is approved without those cards.
- **none**: no commit control.

## 8. Clickable links in chat (slice 0, independent)

Every chat bubble (Argyle and people) escapes, then wraps `https?://` runs in `<a target="_blank" rel="noopener noreferrer">`, through one shared helper that replaces `schoolLinkify` (`static/pwa_school.js:115`) and the bubble at `templates/app.html:5181`. Trailing punctuation stays outside the link. No markdown in this slice; the planner's plain-text rule stays.

## 9. Images

Item photos are served through a new route `GET /api/projects/{pid}/boards/{bid}/image/{lookup_id}`: authorised by board visibility, fetches only the `image_url` stored on that lookup, caches the bytes on disk (downscaled to 800 px long edge, JPEG/WebP), never takes a URL from the request. No hot-linking from the phone (privacy and mixed-content). The hero collage is laid out client-side from these images. Cache files go with the board on delete.

## 10. Later: watching prices and promo codes

Kept items and committed purchase rows are the natural watch targets. When wake conditions exist, "Watch price" on a kept item re-runs `look_up_page` on a schedule, updates the price with a "was $79" note on the board, and DMs a drop. Promo codes become a research step in a round. Nothing in v1 blocks this: lookups already hold price, currency and `fetched_at`.

## 11. Slices

0. Clickable links in chat bubbles (section 8).
1. Boards that show: lookup tool and records, `present` with provenance and fallback, board storage, board card, board sheet (options / compare / list), project row, image route, spoken form, demo shot `board` (invented household and products, product photos from generated demo assets, no real store pages).
2. Boards you answer: reactions, Kept tray and shortlist, Find more and More like this rounds, Make my own copy.
3. Commit: purchase checklist; book and contact through missions.
4. Later: price watching and promo codes (needs wake conditions), map and timeline layouts.

## 12. Tests that must exist (beyond unit tests)

- A TestClient run of every new route, including 403/404 for a viewer outside 7.1 and the 409 stale-version path.
- A mission run on the real tool registry with a faked web layer: research → lookups → `present` → board stored → card posted to the right recipients, for a plain (non-planned) mission.
- Provenance: a `present` naming a URL or price no lookup produced loses that item; two invalid presents fall back to text.
- A Find more round: keeps survive, only open slots get new items, the round appends, the launch cap is untouched.
- Every button state in 7.3: a kid over the allowance gets an approval card to the parents and Approve runs exactly one round; a parent over it confirms and runs; with missions off there is no button.
- Copy: new private project, copied tray, no mission launched.
- A node run of the card and sheet renderers with hostile strings (quotes, `'`, `<script>`) in titles and stores.
- Audience: a board in a `parents` project never reaches a child's chat, spoken reply, or image route.

## 13. Calls made by Claude (owner did not decide these; check them)

- The vocabulary in v1 is `options`, `compare`, `list`; map and timeline later.
- `present` is a finishing action; a mission presents once.
- Items reference lookups by id; the model never supplies URLs, images or prices directly.
- One kept item per slot on multi-slot boards; Keep is a shortlist on single-slot and compare boards.
- Dropped options fold to the end for everyone, recoverable.
- An over-limit round needs one parent approval (kid) or one in-page confirm (parent or adult); the default allowance is 6 rounds a day.
- v1 "Buy" produces a hand-ticked purchase checklist; automated checkout waits for payment.
- Images are proxied and cached, never hot-linked.
- Find more appends to the same board; a new, unrelated `present` makes a new board. A round is marked by `board_id` on its mission.
- Page look-ups fall back to rendering in the add-on's Chromium when a store refuses a plain fetch; browse `LEARNED:` prices do not count as sourced.
- Saying "find more" or "keep the heels" in chat or by voice acts on the focused board through three agent tools; reactions stay taps.
- In a planned mission a work stage may end in a board; the done card names it.
- Voice-started missions get the text DM plus the board card; no new path speaks later DMs.

## 14. Left to the builder

Table vs app_state storage for boards and lookups (a table is expected, given versioned writes); JSON-LD parsing details and which extra meta tags to read; collage layout rules; exact card and sheet styling within `docs/ui_design_guide.md`; swipe gesture implementation; cache eviction policy for images; the composed goal wording for Find more; the Codex / Gemini / Claude split, which the plan states before any code.
