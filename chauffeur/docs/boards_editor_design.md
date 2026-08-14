# Boards Editor Arc — design brief (drafted 2026-08-14)

The gap, in one sentence: **boards are edited from a form that lives at the
bottom of the board.** [`#panel-setup`](../templates/home.html) is 800 lines of
lists, number fields and ▲▼✕ buttons covering every board at once, while the
board itself — the thing you are actually looking at — can only be arranged.
Adding a tile, renaming a board, changing its grid, or reordering the shelf all
happen in a column of text far below the wall you are designing.

The target is the dashboard workflow the app already half has: you open a
board, you see it, and you change it in place. A list of boards with an **+ Add
Board** button; clicking one takes you to that board with an editor bar; every
tile carries a ✎; every settings surface is an overlay over the thing it
configures.

## What this brief argued out (read before relitigating)

**1. There are three kinds of board, and the code only ever named two.** This
is the vocabulary that makes everything else discussable:

| kind | where it lives | who may edit it |
|---|---|---|
| **Home** | always stored in `panel_pages`, reserved slug | the household, fully |
| **Shipped boards** (the ten destinations) | `BUILTIN_PAGES`, authored by us | nobody — hide from shelf only |
| **Own boards** | `panel_pages` | the household, fully |

Home is *not* a shipped board — it is not in `BUILTIN_PAGES` and never was. It
being lumped in with them is most of why "built-in boards vs built-in pages"
reads as nonsense. The other half is that a shipped board **shares its slug
with an admin page**: `/chores` is a page, `/chores?panel=true` draws the
chores *board*. The board is the kiosk face of the destination.

**2. Shipped boards are authored, not configured.** Today, editing a shipped
board silently forks it into the household's settings, where their copy wins
forever and no shipped improvement ever reaches them again. There is a
`_shippedPristine` JSON-string check whose whole job is to *un*-fork you if
your edits happen to land back on the shipped bytes — a fragile guard around a
model that was wrong.

So: **shipped boards become read-only for households.** The only thing a
household may do to one is hide it from the shelf. This is not a restriction
added for tidiness — it deletes the fork hazard, the pristine comparison, the
Reset-vs-Delete ambiguity, and the entire class of bug where a board freezes
without anybody noticing.

**3. The escape hatch is Duplicate, not editability.** A household that wants a
different Chores board copies it into an own board, edits that freely, and
hides the shipped one. This costs nothing and it is also *how we author shipped
boards* (see B0) — which is why it is load-bearing rather than a nicety.

**4. There is no dev mode, because export is harmless.** The first design had a
gated "Save to shipped defaults" button. It was wrong twice: the add-on's
filesystem is ephemeral and is not the git checkout, so the write would vanish
on rebuild and never reach the repo; and authoring has to happen on the *real*
instance against real chores, real members and real photos, which is precisely
where a dev-only env var would not be set. The resolution is that the instance
only ever needs to **export** — which is just showing you JSON of your own
board, needs no gate, and doubles as board backup and board sharing.

**5. Order and shelf visibility must not be stored on the board.** If they
were, every shipped board would enter `panel_pages` the moment anybody
reordered the shelf, and all ten would freeze. Order and visibility live in
their own setting; the board object stays untouched. (Under B0's read-only
model this is belt-and-braces, but it is the reason the boards list cannot
simply write `order:` onto each page.)

**6. A curated shelf must not be a closed shelf.** [`resolve_tabs`](../services/home_board.py)
treats a stored `panel_tabs` as exact and final — correct while curating is a
rare expert act, fatal once the new list writes a full order on every drag.
Every household would be curated on day one and no board shipped afterwards
would ever appear for any of them. Store order **and** a hidden set, and append
known-but-unlisted boards rather than dropping them.

**7. Hiding a tile is a user's decision and has nothing to do with
auto-hiding.** Rule 1 (a tile vanishes when its feature is unconfigured) is the
system acting invisibly. A `hidden` flag is a person parking a tile they want
to keep. They are unrelated and both should exist. The one requirement: a
hidden tile renders **ghosted in edit mode**, never simply absent, or it
becomes the "why is my tile gone" bug.

**8. `require` is an ordinary option, not an authoring secret.** It means "this
board is ABOUT this tile", so an empty one says *"No chores yet"* instead of
vanishing. Households can reasonably want that on their own boards, and B0
requires it settable because shipped boards are now authored through the
ordinary editor. Plain-English label: *"Always show, even when empty."*

**9. The boards list goes in config.html, in an include.** Inventing a `/boards`
route purely to honour config-decentralisation would be ceremony — a user
cannot tell the difference and it adds a flow for one thing. What the rule
actually protects against is the mega-POST and the unnavigable page, so the
tab (a) lives in `components/boards_admin.html` and is one include line in
config.html, and (b) POSTs only its own keys, which is what config.html's save
functions already do individually.

**10. Any board can be Home.** Hiding the Home board was the ask; the ⌂
designation is the primitive that actually delivers it. `HOME_SLUG` is reserved
specifically because `/home` is the landing route, the idle-return target and
what the shelf's Home button means — hide it without moving those and the wall
snaps back every three minutes to a board you deliberately hid. With a
designation that any board can hold, "build my own home board" is a first-class
act and hiding becomes an ordinary toggle with no special case.

## What the household's boards actually look like today

From the 2026-08-14 dump of `/api/home_board/pages`. `shipped` was **empty** —
all ten shipped boards are already forked. The divergence is systematic, which
is the evidence for B0: this is a considered redesign the repo never received.

- **Every board gained a `heading` tile** at the front. No shipped board has one.
- **`row_height` 240 → 10** on seven boards (124 on occasions and trips); size
  is driven through `rows` counts instead (`drives` is `rows: 120`).
- **`gap` 16 → 20** everywhere.
- `routines` swapped its `kids` tile for a `custom` one.
- **Columns are mid-migration**: `home`, `scratchpad`, `new-board` and
  `routines` are on 64; the other nine are still on 12.
- A board named "House Monitor" sits at `/board/new-board` — the slug came from
  the placeholder and never followed the rename.
- The `schedule` board carries an orphan `map` span with no `map` tile.

**Fixed en route (v2.228.2):** `require: True` had been stripped from every
tile of every shipped board. [`toInstances`](../templates/home.html) rebuilt
each instance as `{id, type, config}`, dropping it, under a comment claiming it
could not drift from the server's `normalize_instances`. Merely *opening* the
editor was enough, since `loadSetup` runs every page through it. Had the boards
been dumped as shipped defaults first, the loss would have been baked into the
product permanently — which is why B0's ordering matters.

---

## B0 — Shipped boards become authored data

The foundation. Nothing else is safe until the fork model is gone.

**Landed v2.229.0**, except export/import and Duplicate (moved to B1, where the
editor surface they hang off is being built). What shipped: the data file and
loader, the ten boards re-authored from the household's own layouts with
`require` restored, stored forks made inert, and the pristine-copy machinery
deleted.

- **`BUILTIN_PAGES` moved out of the Python literal** into
  `chauffeur/services/builtin_boards.json` — beside the module that loads it,
  **not** in `chauffeur/data/`, which `.gitignore` excludes as a secrets
  folder. A boards file in there never reaches the repo, the image builds
  without it, and the loader's empty-dict fallback means the app comes up with
  no boards and no error. `scenario_the_shipped_boards_actually_ship` guards
  all three failure modes.
- The dict's explanatory comments stayed in `home_board.py` above the loader
  rather than moving into the JSON: prose in a machine-written data file is
  prose that gets destroyed the first time the file is rewritten.
- **Export a board as JSON** — copy-to-clipboard plus a textarea, in the board
  settings overlay (B2) or the boards list (B3). No gate.
- **Import a board from JSON** — creates an own board. Board sharing and board
  backup fall out for free.
- **Round-trip test: export → import → export is byte-identical**, covering
  `require`, `spans`, `config`, grid numbers, background and icon. This is the
  seam where a shipped board can silently lose a flag, and it just did.
- **One normaliser, or a test that pins the two together.** The `require` bug
  was two normalisers disagreeing — `normalize_instances` on the server and
  `toInstances` in the editor. Whichever survives, the drift must be a test
  failure and not a comment.
- **Shipped boards are read-only.** ✅ `normalize_pages` drops any stored page
  under a shipped slug, and the editor draft carries only the household's own
  boards. **Duplicate as my own board** is the escape hatch — deferred to B1.
- **Deleted:** ✅ `_shippedPristine` and `cleanPages`'s pristine JSON-string
  comparison. `/api/home_board/pages` keeps its `shipped` half but now returns
  **all ten always** — it used to return only the untouched ones, so a
  household that had forked a board stopped being shown ours, and the fork hid
  the very thing it forked from.

**Migration — all five steps done, v2.229.0:**

1. ~~Fix the `require` strip.~~ v2.228.2.
2. ~~Clean up the ten boards on the live instance and dump them again.~~ The
   house standard settled at **64 columns / 10px rows / 20px gutter**.
3. ~~Write them into the data file, re-adding `require` by tile type.~~ All ten
   restored; `kids` was the only flag with nowhere to land, because the
   Routines board now reaches its kid strip through a `custom` container.
4. ~~Drop the stored forks.~~ Done on READ, in `normalize_pages`, rather than by
   rewriting settings — the same lazy rule the rest of the layer follows. The
   stored pages are still in the household's settings and are simply never
   consulted again.
5. ~~Enforce read-only.~~ The editor no longer merges shipped boards into its
   draft, so they cannot be edited or saved.

**A capability was removed by this and then put back (v2.229.1).** B0 dropped
the per-board background on shipped slugs, reasoning that the alternative was
the `panel_page_backgrounds` map deleted in v2.227.0. That reasoning was wrong
about the thing that mattered: **a picture is presentation, not content.** The
tiles on a shipped board are ours; the photograph never was.

It is back as `panel_shipped_backgrounds` — `{slug: picture}`, shipped boards
only. The rule that keeps it from being the v2.227.0 bug is **one field per
board, decided by who owns the board**: a board the household owns keeps its
own `background` field and never appears in this map; a shipped board has no
household-editable field, so the map IS its field and has nothing to silently
overrule. Precedence: household pick → authored picture → panel background,
with blank meaning "no answer" rather than "no picture".

> **Process note, worth more than the feature.** This was flagged in the B0
> commit and the summary *after* it shipped, which is not the same as asking.
> A change that takes away something a person could previously do stops and
> asks first, however good the reasoning is — asking costs one question,
> reversing costs a release and rework.

Target: **v2.229.0**

## B1 — The board is the editor

**Landed ahead of the arc (v2.229.2): the board-wide calendar day count is
gone.** `panel_agenda_days` was one number for how far the calendar tile looks
ahead. That was right while a board had one calendar and wrong the moment tiles
became instances — two calendars on one board, one showing three days and one a
fortnight, is the point of instances, and a board-wide number is a second place
to set what each card already owns. `calendar.days` carries a literal default
(`AGENDA_DAYS`, 5) now and is set per card.

This is B1/B2 work that happened to land first: the field lived in
`#panel-setup`, which this arc deletes anyway, and the server-side half is
independent of the editor rewrite. Nothing on the wall changed — the household's
only two calendar tiles are a home-board tile with an explicit `days: 5` and a
month grid, where the day count does not apply.

**A trap worth remembering:** `AGENDA_DAYS` had to move above the option
vocabulary. `WIDGETS` is built at import, so a constant used as an option
default and defined 1,300 lines below it is a `NameError` on startup.

**Shipped so far: v2.230.0 → v2.230.2.** `hidden` and `require`; Duplicate,
export and import; the tile ✎ overlay and the Add-tile overlay. **Still open:
card management inside the overlay, and then deleting the tile list.**

- **Editor bar** on `/board/<slug>` outside panel mode: **Edit** (today's
  arrange), **Settings** (B2), **+ Add Tile**. ✅ Add-tile landed on the arrange
  bar; Settings is B2. Viewing first, editing on demand — the board is not
  permanently in arrange mode.
- **Every tile gets a ✎** in edit mode, opening its options in an overlay. The
  overlay and the options renderer already exist (the per-card editor and
  `components/board_options.html` with its compile-time `OW` substitution); this
  is a third context alongside `w` and `c`.
- **+ Add Tile opens the picker as an overlay.** It appends at the end of the
  grid — the grid is flow-ordered and has no empty-cell model, so "drop it
  where I clicked" is out of scope. The picker **stays open** for multi-add,
  with Done to close.
- **`hidden` on tiles**, ghosted in edit mode. ✅ Ships as a **stub** — no
  builder runs, so a parked tile costs the wall no query and cannot break the
  payload the other cards wait on — and the client refuses to draw it outside
  arrange mode. Cards inside a container are still to do.
- **`require` surfaces** as *"Always show, even when empty."* ✅ Offered only on
  types with an empty state to say, and never on chrome or a container, decided
  by `catalog().requirable` rather than a second list in the template.
- **Deletes: the tile list and the inline picker from `#panel-setup`.** NOT YET,
  and deliberately. The overlay covers the tile row (size, both heights, hidden,
  always-show, options, remove) and `scenario_the_tile_is_edited_on_the_tile`
  pins that, but the list also carries **the card management for a container
  tile** — add, remove and reorder the cards inside a Custom tile. Until that is
  in the overlay, deleting the list drops functionality.

**Two things this arc uncovered that are worth carrying forward:**

- **`toInstances` now carries instance flags as a list.** It dropped `require`
  by rebuilding each instance as `{id,type,config}`, and `hidden` would have
  been the identical bug a second time — the tell that the shape was wrong
  rather than the field.
- **B0 left a latent slug bug.** A board named "Chores" minted the slug
  `chores`, which the server now drops as a legacy fork, so the board vanished
  on save with no explanation. `freshSlug` and `setPageSlug` both check the
  shipped slugs and the reserved home slug now. The server cannot make this
  call — a new board and a stale fork are identical to it — so the editor is
  the right place for the guard. Fixed v2.230.1.

Target: **v2.230.0**

## B2 — Board settings overlay

- One overlay: **name, icon, slug, background, columns, row height, gap**, plus
  the agenda-days field. Keep the gutter-divisibility warning and the "going
  from 12 to 48 makes every tile a quarter as wide" warning.
- **Slugify the name on creation.** The slug stays editable here behind an
  explicit warning and **never auto-follows a rename** — it is in bookmarks,
  `?tabs=` strings, HA dashboard iframes, and the `board:` shelf key.
- **Deletes:** the board identity card and the grid fields from `#panel-setup`.

Target: **v2.231.0**

## B3 — The Boards tab

- **`components/boards_admin.html`**, included by config.html as a Boards tab.
  POSTs only its own keys.
- **The list**: every board, drag-reorderable with **pointer events, not HTML5
  DnD** (it does not fire for touch — the board learned this already). Per row:
  a **shelf visibility toggle**, the **⌂ home designation**, Duplicate, and
  Delete (own boards only; shipped rows have no delete).
- **+ Add Board**, creating a blank board or a duplicate of an existing one.
- **Shelf model rewrite**: order plus a hidden set; unknown-but-existing boards
  append rather than vanish. Fixes the curated-is-final trap.
- **⌂ wiring**: the landing route, idle return and the shelf's Home button all
  follow the designation rather than the literal `home` slug.
- **Intake leaves the shelf vocabulary** (`NAV_SLUGS`). It has no panel
  interaction anybody has described; it stays on the desktop nav where admin
  lives. If a kiosk-shaped intake is ever designed, it joins the shipped boards.
- **Household panel settings** move here: theme and sun offsets, idle return,
  screensaver, default background, `ha_browser_url`, allow-unsafe-controls.
- **Deletes: the rest of `#panel-setup`.** After B3 it does not exist.

Target: **v2.232.0**

---

## Landmines

- **The panel latch.** [`ha_theme.html`](../templates/ha_theme.html) re-adds
  `panel=true` from `sessionStorage` on any load that lacks it. Every link from
  the boards list into a board must carry `?panel=false` or a wall tablet goes
  straight back to kiosk.
- **`home.html` is the single point of contention** — 324 KB, with `homeBoard()`
  spanning ~3,500 lines and holding the renderer, every tile body, arrange mode
  and the whole form. B1–B3 delete a large part of it, which is the point, but
  every arc touches the same component.
- **Tests that will break and are the safety net**: `test_board_arrange_runtime`
  and `test_home_board_runtime` execute `homeBoard()` in node; `test_nav`
  asserts the shelf is built from `NAV_ITEMS`; `test_panel_chrome` asserts the
  shelf's construction. Budget for them rather than discovering them.
- **Tailwind is precompiled** — run `tools/build_tailwind.py` after any template
  class change or the sheet is stale and fails silently.
- **No browser dialogs** — `showGlobalAlert` / `promptConfirm` / `promptInput`
  from `components/control_center.html`.
- **Editor chrome uses `.ed-card .ed-panel .ed-title .ed-head .ed-note
  .ed-input`**, not literal greys. That was an explicit fix once already.
- **Spans outlive their tiles** somewhere — the orphan `map` span on the
  schedule board proves the delete path still misses a case.
- **HA degrades gracefully**: every new touchpoint must behave with no HA
  present. The picker's disabled "· needs Home Assistant" rows are the pattern.

## Open questions

1. **Is 64 the house column standard?** Blocks B0 step 3.
2. **Does a shipped board's row in the list show anything beyond name, icon,
   visibility and Duplicate?** It has no settings a household may change.
3. **Does `hidden` belong on shipped-board tiles at all**, given a household
   cannot edit them? Probably not — hiding the whole board is the lever.
