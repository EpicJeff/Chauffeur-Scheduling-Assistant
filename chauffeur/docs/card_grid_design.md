# The card grid: real row spans, and moving a card between tiles

Two requests, one grid. A household wanted a tall card with two shorter cards
stacked beside it inside a Custom tile — the layout the main board grid has
always allowed for tiles — and wanted to move a card from one Custom tile to
another by dragging it, instead of copying the card's YAML out of one and
pasting it into a new card on the other.

Both land on `.nc-stack-grid`, the twelve-column grid that lays out cards inside
a Custom tile and sub-cards inside a Home Assistant `vertical-stack` / `grid`
card. This is the design for changing it.

## Why the layout is impossible today, exactly

A cell in `.nc-stack-grid` is placed with a column span and sized with a CSS
height:

    grid-column: span <cols>;
    height: calc(<rows> * var(--nc-row));     /* --nc-row: 56px */

`grid-column` makes a card a participant in the grid's horizontal geometry.
`height` does not do the same thing vertically: **every cell occupies exactly
one implicit grid row**, whatever its height. So a four-row card and a two-row
card side by side both sit in row 1, the row grows to the taller of them, and
the next card in source order is placed in row 2 — below the tall card's bottom
edge, not in the empty space beside it.

`.nc-free` (`align-items: start`) was added so a tall card stops *stretching*
its neighbours. It does not reclaim the space: the short neighbour keeps its
height with dead whitespace under it, and nothing can be placed into that
whitespace because there is no row track there to place anything into.

The main board grid does not have this problem because it writes
`grid-row: span N` onto a shared lattice, which is what makes a tall tile beside
a stack of two an everyday layout there. Home Assistant's own sections view
writes `grid-row: span var(--row-size)` for the same reason.

## Decision 1 — a card's `rows` becomes a row span

    grid-column: span <cols>;
    grid-row:    span <rows>;
    height:      calc(<rows> * var(--nc-row) + (<rows> - 1) * var(--nc-gap));

A card with no `rows` (the default, "as tall as the content") spans one
automatically-sized row and keeps the height it has today. The twelve columns
are unchanged; what changes is where those two variables come from — see the
next section, because `--nc-row: 56px` is the other half of this request.

That is the whole feature. With row spans, a four-row card in columns 1–6 and
two two-row cards in columns 7–12 place as rows 1–4, rows 1–2 and rows 3–4,
because the second short card now finds a free slot beside the tall one rather
than a new row beneath it.

### The height formula has to change, and it settles an existing disagreement

Today a sized card draws at `rows × 56px`. The resize drag, meanwhile, has
always moved at a pitch of `56 + gap` per row — both in the Custom tile handler
and in the Home Assistant stack handler. Dragging a card to "three rows" and
drawing a card at "three rows" therefore already mean two different heights, and
the drift is invisible because nothing else on the tile was measured against it.

With spans, they cannot stay different: three rows must equal one row plus two
rows plus the gap between them, or a tall card and the stack beside it will
never bottom-align — and bottom-aligning them is the entire request. The
formula above is the pitch the resize drag was already using.

## Decision 1b — the row and the gutter come from the board

`--nc-row: 56px` is Home Assistant's section row height, borrowed when the card
grid was written. Inside a Custom tile it is arbitrary: this panel is not
drawing an HA dashboard there, and the tile it sits in was placed on a board
whose own rows are `10px` with a `20px` gutter. Five and a half board rows is
not a unit anybody chose.

So the Custom tile's card grid takes the **board's** `row_height` and `gap` —
the two numbers already in board settings — as `--nc-row` and `--nc-gap`. One
vertical unit for the whole page: a card of nine rows is as tall as a tile of
nine rows, and a number typed into the tile editor means what the same number
means in board settings.

**The arithmetic holds at any values, and that is worth knowing.** The board
grid lays tiles on a 1px lattice and *paints* its gutters as margins, which is
why board settings warn that a stack of tiles only bottom-aligns beside a tall
one when the gutter divides into a whole number of rows. The card grid uses real
CSS gaps instead, so a card spanning `N` rows is `N·h + (N−1)·g` tall and two
cards of `a + b = N` rows stacked beside it come to `N·h + (N−1)·g` as well —
identical, at every row height and every gutter. No lattice trick, no
divisibility rule, nothing to warn about.

Three things follow, and all three are part of this work:

- **The `rows` cap rises from 40 to 1000.** Forty rows was a sensible ceiling at
  56px each; at a 10px board row it would cap a card at 400px, shorter than most
  tiles.
- **The "no intrinsic height" floor becomes absolute.** A drawn card that lays
  its content *into* its box (a map, a mounted calendar, a camera) currently
  falls back to `calc(4 * var(--nc-row))`. At a 10px row that is 40px — a
  collapsed card. It becomes a fixed pixel floor, keeping the height it has
  today.
- **Both resize handlers read the variables.** `56` is hardcoded in the Custom
  tile handler and in the Home Assistant stack handler; a pitch that disagrees
  with the grid is the bug this design already had to unpick once.

**Nothing on the wall changes height.** No card on any board carries a `cols` or
`rows` today — the sizing has never been used — so this is a new capability
rather than a re-layout of boards nobody edited.

Per-tile row/gutter overrides were considered and declined for now: the boards
already run a 10px lattice, finer than a card layout needs, and two more
settings on every Custom tile editor is a real cost. If one tile ever needs to
differ, the override can be added then without changing anything here.

### What stays exactly as it is

- **`fill` cards** keep their measured pixel height and one row span. `fill`
  means "take the rest of the screen", which is a measurement, not a row count.
- **Drawn cards with no intrinsic height** (a map, a mounted calendar, a
  camera) keep `min-height: calc(4 * var(--nc-row))` when unsized. The content
  is laid out *into* the box, so "as tall as the content" has no answer for
  them, and fit still means fill.
- **`.nc-free`** stays. It is about stretching, which row spans do not replace.
- **The stored data shape.** `cols` and `rows` keep their names, their ranges
  (1–12 and 0–40) and their meaning as twelfths of the tile and rows of 56px.
  Nothing needs migrating, on either surface.

### Both grids get row spans; only one of them gets the board's row

The span change lands on the Custom tile's card grid (`cellStyle`) and on the
Home Assistant stack renderer (`drawCard`) alike. They share the class and the
defect, and a `grid_options: {rows: 3}` pasted out of a real dashboard should
mean in this panel what it means in Home Assistant — which, since HA's sections
view spans rows, it currently does not.

The *unit* is where they part. A number inside a Home Assistant card config was
written against HA's 56px section row, so a stack's cells keep `--nc-row: 56px`
and the 12px gutter they have today: `rows: 2` is expected to draw the height it
draws in HA, and a household comparing the two surfaces is entitled to that.
Only the panel's own card grid — the one whose numbers are typed into this
panel's own editor — follows the board.

Two grids, two vocabularies, each matching where its numbers came from. Both
variables are set on the grid element, so this is a question of which value is
written where, not of two implementations.

## Decision 2 — a card can be dragged into another Custom tile

The card drag is pointer-based, not HTML5 drag-and-drop, for the reason stated
where the tile drag was written: DnD does not fire for touch at all, and this
panel runs on a tablet. Cross-tile movement extends that same handler rather
than introducing a second mechanism.

While a card is being dragged, each pointer move resolves what is under the
pointer twice:

- `.closest('[data-cards]')` — **which tile**. The grid element already carries
  `data-cards="<tileId>"`.
- `.closest('[data-path]')` — **which slot** in it.

When the tile under the pointer is the one the card started in, the behaviour is
today's reorder, unchanged. When it is a different Custom tile, the card is
spliced out of the source tile's `config.cards` and into the destination's at
the hovered index. Dropping onto the grid of a Custom tile that has no cards
appends.

### The rules that keep it honest

- **Only into an unlocked Custom tile.** A built-in tile is built with a single
  synthetic card and has no card list to join; it must refuse rather than
  half-accept.
- **A full destination refuses.** Twelve cards per tile is the server's limit
  (`TILE_MAX_CARDS`), so a thirteenth is refused with a `showGlobalAlert`
  saying so. Never a browser dialog — the panel has its own.
- **A colliding id is re-minted.** Card ids are unique within a tile, and the
  destination may already hold a card of the same type. The mint is the one
  `addCard` already uses: the bare type, then `type-2`, `type-3`.
- **`cols` and `rows` travel unchanged.** Both are twelfths of the tile and rows
  of the tile's grid; refitting them to the destination's width would silently
  resize a card somebody just moved, and the size is a decision they made.
- **The gesture is never swallowed.** A drag that ends somewhere invalid returns
  the card to where it started.

### Persistence

None of this is new. Cross-tile moves splice the same draft
(`page().widgets[…].config.cards`) that every other arrange-mode edit writes to;
`Save` commits the whole page through `POST /api/settings`, and `Cancel`
restores the snapshot taken when arranging began. No new endpoint, no new
server-side validation — `normalize_cards` already caps the list and refuses
nested containers on the way in.

## The bug this uncovers

When a Home Assistant card sits *inside* a Custom tile, dragging its sub-cards
does nothing at all. `startCardDrag` looks its tile up by `tile.id` in
`page().widgets`, but a card inside a container is drawn with the namespaced id
`"<tileId>-<cardId>"`, which never appears in that list — and by the time the
handler gives up it has already called `preventDefault()` and `stopPropagation()`,
so the gesture is consumed and nothing moves, with nothing said anywhere.

It is in the handler this work edits, so it is fixed here: the sub-card drag
resolves its instance through the containing tile when the drawn id is
namespaced, and a drag that genuinely has nowhere to go stops swallowing the
gesture.

## Testing

Both halves are geometry, so both are measured in a real browser rather than
asserted from the source — the same bargain the hosted-card box test makes, for
the same reason: a layout string can be plausible and wrong.

**Row spans (chromium, against the real `.nc-stack-grid` rules read out of
home.html):**

- A four-row card and two two-row cards in the remaining columns produce three
  distinct top offsets, the two short cards share a column band, and the second
  short card's top is above the tall card's bottom. This fails today.
- A sized card's height equals the summed height of the stack beside it — the
  formula's whole job — and it holds at more than one row height and gutter,
  because the point of taking the board's numbers is that any of them work.
- A card grid inside a Custom tile draws on the board's `row_height` / `gap`,
  while a Home Assistant stack's cells stay on 56px.
- An unsized card keeps its content height, a `fill` card keeps its measured
  height, and a card with no intrinsic height keeps its pixel floor rather than
  collapsing to four board rows.

**Cross-tile drag (node, against the real handler):**

- A card dragged into another Custom tile leaves the source list and enters the
  destination at the hovered index.
- A destination holding twelve cards refuses, and the card stays put.
- A colliding id is re-minted rather than duplicated.
- A built-in (locked) tile is not a destination.
- `Cancel` after a cross-tile drag restores both tiles.

**The swallowed drag:** a sub-card drag inside a Custom tile resolves its
instance and moves the card.

## Out of scope

- Dragging a card **out of** a tile onto the board to become a tile of its own,
  or between boards. Both need somewhere to park a card mid-gesture; neither was
  asked for.
- A no-drag "Move to tile…" control. Considered and declined: the board editor
  only runs in a browser, where dragging is available, and a second path to the
  same outcome is a second path to keep working.
- Masonry. `grid-auto-flow: dense` reads like a one-word version of this fix and
  is not one — it backfills whole rows for narrow items, so the tall card would
  still own a single row and two shorts still could not stack beside it.
