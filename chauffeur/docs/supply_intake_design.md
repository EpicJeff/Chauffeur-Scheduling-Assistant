# Supply Intake & Gifts — design brief (drafted 2026-08-21)

The pitch this came from: *autonomous household logistics and pre-emptive
ordering* — the app notices that a school project is coming, that a classmate's
party has been accepted, that the paper towels are nearly gone, and puts the
things you need in a cart before you have thought about it.

Stripped of the marketing, that is three different features wearing one coat,
and they are not equally real. This brief keeps two of them, cuts the third,
and names the one piece of engineering they genuinely share.

## What this brief argued out (read before relitigating)

**1. There is no auto-ordering, and there must never be one.** Walmart's
Add-To-Cart is a *URL*, not an authenticated API
([walmart.py](../services/walmart.py) — `CART_URL`). It builds a cart. It does
not check out, it holds no payment instrument, and nothing in this app will
ever hold one. The ceiling is *"the cart is packed, tap to pay"*, and the UI
must say that plainly rather than implying a purchase happened. This is not a
limitation to route around — an app that spends money unattended is a worse
product, and the approval tap the pitch wanted is simply the checkout that was
always going to be there.

**2. Supplies are an attribute of a dated thing, not a kind of thing.** The
poster board is not an event and it is not a to-do; it is what the science fair
*wants*. Modelling it as its own proposal kind creates a matching problem
(which event does this belong to?) that modelling it as a field does not have —
the supplies ride the item that becomes the event, and the tie is free.

**3. Tying supplies to an *existing* event costs zero extra LLM requests, and
that is why this is affordable at all.** `known_events_block()`
([email_ingest.py](../services/email_ingest.py) ~L256) already puts the
calendar into the extraction prompt and already gets `duplicate_of` back —
semantic event matching riding a call that happens anyway. Supplies against a
known event is the same trick with a different field name. Any design that
needs a second LLM round-trip to answer "which event is this for" is the wrong
design.

**4. The duplicate branch is where most of the real traffic is.** Reminder
emails outnumber announcement emails. A reminder for an event already on the
calendar is currently stored with `status: 'duplicate'` and rendered as a skip
— correct today, wrong the moment a proposal can carry supplies. *"Already on
the calendar — but it wants three things"* is a proposal, not a skip, and that
path does not exist yet.

**5. The gift shortlist must never name a product.** An LLM asked for gift
ideas returns `LEGO Friends Beach House, $34.99` with an invented SKU and a
price from its training data. The precedent for the fix is already in the
codebase and already cited in the occasions brief: trips do
**LLM-proposes → Mapbox-verifies**. Here it is **LLM emits search queries →
`walmart.search()` returns real itemIds and real `salePrice` → the budget cap
filters the API response**. The cap is applied to Walmart's answer, never to
the model's imagination.

**6. Gift secrecy is already solved; the occasions brief's blocker is stale.**
`ShoppingList.audience='private'` plus `shared_with`
([schemas.py](../models/schemas.py) ~L1352) is an allow-list with no parent
bypass and no panel bypass, written for exactly this case, and
[scope.py](../services/scope.py) ~L581 already reserves `gift_list: 'parents'`.
The mechanism exists. The noun does not. Nothing in this arc needs a new
visibility primitive — it needs to *use* the one that shipped.

**7. Routine restocking is cut.** See §Cut. It is the leg of the pitch with no
implementable signal behind it.

## Design principles (argue before violating)

1. **Precision over recall, because the queue is the product.** The intake
   module's own docstring: *a noisy queue teaches the parent to ignore it,
   which is worse than no queue.* Supplies extraction is structurally lower
   confidence than date extraction, so it gets its own floor and its own
   rules, and an empty supplies list is the expected common answer.
2. **Nothing is bought, added, or ordered without a tap.** Candidates are
   staged. This matches every capture path already shipped — photo candidates,
   Walmart search (*"Never auto-maps: the family picks"*), intake proposals.
3. **The deadline is the feature, not the list row.** "Add poster board to the
   list" is worth almost nothing; "the fair is Friday and your shop run is
   Saturday" is worth the whole arc. Anything that writes a supply must write
   *when it is needed by*.
4. **Never route a list with the LLM.** The model does not know the family's
   lists or stores. Default list, parent moves it. Same reasoning that made
   intake's sender patterns a routing *hint* rather than a gate.
5. **One prompt per question.** [shopping.py](../services/shopping.py)'s vision
   prompt answers *"what is running low in this photo"* and carries a design
   rule — *never claim to know what is in the house*. Intake's answers *"what
   must this family do by a date"*. They stay separate.
6. **Additive provenance.** An item records why it is here without its list
   belonging to the cause — the `source_meal_id` precedent, restated.

## The shared spine

Both halves of this arc end in the same sentence: *a dated thing needs objects
bought before it.* They differ in everything else, and they share exactly one
piece of engineering worth building once —

**`ShoppingItem.needed_by` (ISO date) diffed against the next shop run.**
`shopping.next_scheduled_shop()` already knows when the family shops, and
`lists_needing_a_trip()` / `propose_shopping_errands()` already know how to ask
for a run that does not exist yet. `buy_on` already exists as the *output*
(which run this item rides); `needed_by` is the missing *input* (the latest run
that still works). Every item carrying a deadline then behaves correctly
regardless of which half of the arc wrote it, and the gift arc's "order by
Wednesday for Saturday" collapses into arithmetic the school arc already did.

What is **not** shared, and should not be forced together:

- The occasion's tie is `ShoppingList.occasion_id` (list-level); intake's is
  `ShoppingItem.source_event_id` (item-level). That looks like two mechanisms
  and is one rule — *tag the coarsest entity the thing wholly owns*. A gift
  list is wholly the party's. A poster board goes on the list you already keep.
- A science fair is an **event**, not an occasion. Minting an occasion for it
  would be exactly the empty-container failure the occasions brief was written
  to avoid. `source_event_id` stays distinct from `occasion_id`.

---

## Build order

**A1 → A2 → A3 → A4 → A5 → A6.** A1 first because the spine needs a producer,
and because school email arrives weekly while classmate parties arrive six
times a year. A5 last because it is the only slice that can fail on *quality*
rather than plumbing, and cutting it strands nothing.

## A1 — Supplies in intake

One field on the extraction schema, carried through both entry points at once
(`run_ingest` and `run_photo_ingest` share `EXTRACTION_SYSTEM`):

```
{ "kind": "event"|"task", ..., "supplies": [{"name", "qty", "why"}] }
```

Extraction rules, tight on purpose (principle 1):

- **Nameable physical objects only.** "$5 for pizza day" is money, not an item.
  "Wear team colours" is clothing the family owns. "Bring a labelled water
  bottle" is a real one only if the family plausibly has to buy it — and when
  in doubt, omit. A supply that turns out to be junk costs more than a supply
  that was missed, because the missed one still shows up in the notes.
- **Never invent a quantity** (the shopping prompt's existing rule).
- **An empty list is the expected common answer**, stated as explicitly as the
  relevance gate states it for items.

`normalize_item()` carries and sanitizes the array; malformed entries drop
individually rather than killing the item.

**Supplies are not a target.** They ride whichever target the parent picks —
calendar event, errand, household task, kid task. The card grows a checkbox
section (all pre-checked, because extraction already filtered) plus a list
picker defaulting to the default list, and approval writes the items *in
addition to* whatever the target branch wrote.

New `ShoppingItem` fields:

| field | type | note |
|---|---|---|
| `source_event_id` | `str?` | what caused this row — event id, errand id, or task id |
| `needed_by` | `str?` | ISO date; the spine's input |

`added_via` gains `'intake'`.

## A2 — The deadline spine

`needed_by` against `next_scheduled_shop()`. Three surfaces:

- The list row shows the deadline when there is one, and shows it *urgently*
  when the next run falls after it.
- A [watchers.py](../services/watchers.py) finding for the same condition —
  because a surface you have to open is one you do not open.
- When no run lands in time, the existing shopping-errand proposal path is what
  gets offered, not a new one.

No percentage, no completion bar (occasions §O2 reasoning): three of eight
supplies unbought is fine on Monday and an emergency on Thursday, and one
number cannot say both.

## A3 — Duplicates that carry supplies

A proposal whose `duplicate_of` matches a known event but whose `supplies` is
non-empty stops being a skip. It renders as a supplies-only card against the
existing event, and approval writes the items with `source_event_id` pointing
at the event already on the calendar. No new event, no duplicate.

## A4 — The invited occasion

Every occasion template today is host-side — `thanksgiving`, `christmas`,
`birthday`, `party`, `gathering` all ask headcount, cooking hands, and whether
to tidy the house. Being *invited* is the inverse: headcount one, no kitchen,
somewhere that is not home.

New `kind: 'invited'`:

- Questions: whose party, roughly what age, budget cap.
- Checklist: a gift errand at `anchor − 3d`, and **wrapping paper and a card**
  as its own line, because that is the thing actually forgotten.
- The list it generates is created with `audience: 'private'`.

Created two ways: an agent tool from chat ("Ellie's been invited to Jack's
party Saturday"), and a watcher that *proposes* on a party-shaped calendar
event with a kid attendee. Proposes — never auto-creates.

The budget cap is a **search filter**, not a ledger. No totals, no history, no
"you spent $340 on gifts this year". Spend tracking stays cut (occasions
brief), and this does not reopen it.

## A5 — The gift shortlist

`generate_list()`'s shape with a verification stage spliced in: the LLM returns
search queries and a one-line rationale per query, `walmart.search()` resolves
each to real items, the budget cap filters that response, and what survives is
**staged** for a pick. Nothing auto-added.

If the search returns thin, the correct output is a short honest list, not a
padded one — a bad gift suggestion is worse than none, because the parent has
to think about it either way and now also has to reject it.

## A6 — Order-by

A fulfilment-lead setting (default 3 days) turns the party's anchor into the
`needed_by` A2 already understands, and the occasion page gets the cart button
that `cart_for_list()` has been able to serve since W1. Nearly free — the
arithmetic landed in A2.

A school supply carts through the *same* rails with no new code: the
name→itemId mapping is per-name and store-agnostic, and unmatched names already
surface honestly in `cart_for_list()` rather than being dropped.

---

## Explicitly cut — with reasons that hold

- **Routine household restocking.** There is no consumption signal for non-food
  goods: no purchase history (the affiliate API does not expose one), no
  scan-out, no shelf sensor. Groceries are already covered by the dish →
  ingredient drain with `claims`. What remains is toilet paper and toothpaste,
  where the only implementable version is *"we buy this every six weeks"* —
  a recurring errand plus a list item, both already expressible. And a watcher
  that pings about toothpaste is how a family stops reading watchers
  (occasions principle 8, do not become a taskmaster). If it ever ships it is
  a silent `restock_days` re-add on the next run, with no notification, ever.
- **Auto-ordering.** §argued-out 1.
- **Merging the two vision extractors.** Principle 5.
- **LLM-chosen shopping list.** Principle 4.
- **A gift-spend ledger.** §A4.

## Risks

- **Prompt bloat is the real cost of A1.** `EXTRACTION_SYSTEM` already runs a
  relevance gate, extraction, date resolution, and dedupe, on the background
  tier at 44–180s, and the same prompt serves the vision path. A fifth job
  degrades the other four. The mitigation is a short tightly-ruled block and
  re-verification of the existing intake assertions — the standing rule about
  shared prompts applies exactly here: diff the backend change first.
- **A5 is the only quality risk in the arc.** Everything else is plumbing over
  machinery that already works.
- **`ShoppingItem` will carry four provenance fields** after A1
  (`source_meal_id`, `claims`, `occasion_id`, `source_event_id`). Each is a
  different noun with a different lifecycle, so collapsing them into
  `source_kind`/`source_id` buys a migration and no user-visible gain.
  Additive is right — but a *fifth* is the signal to stop and refactor.
- **An invited party has no prior instance.** Different kid, different party,
  every time. The gap-report diff that justifies occasions is inert here, so
  A4 gets the context object and the checklist without the carryover story.
  Fine, but know it before it reads as a regression.

## Tests when built

- `tests/test_supply_intake.py` — supplies survive `normalize_item`; malformed
  entries drop individually without killing the item; money and clothing
  phrasings produce no supplies; approval writes items with `source_event_id`
  and `needed_by` on every target branch; a duplicate carrying supplies is
  proposable (A3).
- `tests/test_shopping_cards.py` additions — `needed_by` versus the next
  scheduled run, including the no-run-in-time case (A2).
- `tests/test_occasions.py` additions — the `invited` template stamps a gift
  errand and a wrapping line; its generated list is `audience: 'private'` (A4).
- Gift shortlist: the budget cap filters the **search response**, asserted
  against a stubbed `walmart.search()` — never against the model (A5).
