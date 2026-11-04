# Chauffeur UI design guide

**Living standard. Reviewed against v2.499.4 on 2026-09-14.** See
[`../../docs/README.md`](../../docs/README.md) for documentation status.

*This file is handed verbatim to any agent building or touching UI. It is not
advice; it is the house style, extracted from the shipped surfaces. Where this
guide and a shipped sibling disagree, read the sibling — then fix whichever of
the two is wrong rather than inventing a third way.*

## The one rule

**Never invent a visual language. Find the sibling that already solved this
shape and reuse its builder or copy its markup exactly.** Chauffeur's look is
not a palette, it is a set of shipped components. A new surface that "looks
designed" but matches nothing else is a defect, even when it is pretty.

## Shared builders come first

### Adult PWA presentation

The approved [audience review](../../docs/design/pwa-audience-audit/AUDIT.md)
introduces a distinct adult PWA shell. `static/pwa_shell.css` and
`static/pwa_shell.js` own this presentation: neutral surfaces, thin borders,
8–12px corners, compact labeled navigation and a searchable More directory.
Today, Plan, Household and Messages retain their existing data builders and
permission rules; secondary Map and Music views remain available from More.
Profile holds appearance, avatar, critter, notification setup and sign-out.
The next-drive summary reads the existing scheduler rows rather than deriving
departure times separately. Child stages keep their existing visual treatment
until their own approved implementation pass. Keep these adult overrides
scoped to `data-audience="adult"`; do not flatten the kiosk or child UI.

Adult screens follow the mockup's actual hierarchy: 31px page headings,
15px row titles, 13px secondary copy, aligned time columns, transparent rows
with subtle separators, and one bordered departure card. Past items retain
full text contrast and use a small status label; never fade an entire adult
row. Programs use the same row treatment while retaining their disclosure.
Household sections switch between tasks, lists, reviews and existing threads.
Review counts use the selected member's fetched payloads and the existing
approval handlers. Keep primary actions green; reserve warning colors for
real states. Test populated, past-only and dark screens against the approved
mockup, not just the presence of tabs or a theme attribute.

Adult action sheets use `.pwa-sheet` and `.pwa-sheet-overlay`, including the
shared `_pwaModal` builder. Follow the audience review's `.sheet`, `.primary`
and `.secondary` styles (`mockups.css:1`): 25px headings, 22px padding and
top corners, neutral secondary buttons, one green primary action, no button
shadows. Keep drive Start/Arrived targets at least 56px. Sheets scroll within
85dvh and include bottom safe-area padding; tablet dialogs center with a
bounded width. Roll-call and packing states retain explicit marks as well as
their semantic colors. Never give sheets a separate visual language from
their adult parent screen.

### Adult PWA, reimagined: the vocabulary (slice 0, v2.499.751)

The approved redesign (`docs/superpowers/specs/2026-11-03-pwa-reimagined-design.md`,
mockups `docs/design/pwa-reimagined/index.html`) replaces the neutral adult
surfaces above screen by screen. Slice 0 ships the shell every later slice
draws on; the rules below apply under `html[data-audience="adult"]` only and
leave every child stage and the kiosk exactly as they were.

- **The sky.** The body wears a time-of-day wash, never the person's colour:
  `linear-gradient(180deg, var(--pwa-sky-top) 0%, var(--pwa-sky-mid) 42%,
  var(--pwa-sky-bottom) 100%) fixed`. `pwaSky(hour, dark)` in
  `static/pwa_shell.js` is a pure table lookup over four bands (morning 05-11,
  afternoon 12-16, evening 17-20, night 21-04); the light morning is the
  mockup's `#fff0e6 / #f6eef7 / #eef0fb`. Every stop contrasts 4.5:1 or better
  with the ink in both themes (`tests/test_pwa_sky.py` proves all 24 hours).
  `pwaSyncSky()` writes the three vars on `:root` from `pwaSyncShell`, from
  `applyTheme`, and when the page becomes visible again. Never set a body
  background on an adult surface; never derive the sky from a member.
- **Ink and cards.** `--pwa-ink` (`#1f1d2b` light, `#f3f2f7` dark),
  `--pwa-card` (`rgba(255,255,255,.62)` light, `rgba(255,255,255,.06)` dark),
  `--pwa-card-raised` (`#ffffff` / `#262a36`), `--pwa-radius: 22px`.
  Translucent, borderless, 22px corners; the person's hue stays the accent
  (`--pwa-accent`) and nothing else.
- **The orb.** Argyle is one component: `static/argyle_orb.css` (class
  `.argyle-orb`, size via `--argyle-orb-size`, hidden state
  `.argyle-orb-hidden`) and `static/argyle_orb.js`
  (`ArgyleOrb.create({ id, label })`, `ArgyleOrb.glyph()`). The wall panel's
  `#panel-chat-orb` and the phone's `#tab-argyle` are both built from it; the
  wall keeps only its position rules in `ha_theme.html`. Never paint a second
  orb; never change the look in one place.
- **Argyle from anywhere (slice 2, v2.499.753).** The orb has two gestures:
  tap opens the overlay to type, hold (350 ms) opens it listening through the
  phone voice path; a click with no pointer pair (VoiceOver, TalkBack, Switch
  Control) opens type mode; Enter/Space on the focused orb too. The overlay
  (`static/pwa_argyle.js`, `window.PwaArgyle`) rises over the current screen
  and NEVER routes through `setView` or `openChannel`: `currentView`,
  `PwaNav.depth()` and the scroll are what they were when it closes. It
  ensures the Argyle DM once, sends text with the thread's own
  `POST api/channels/{id}/messages`, and learns of the reply the way the
  thread does (the `api/messages/stream` channel event, then one messages
  read); the newest Argyle message's body and `card` are drawn with the
  thread's `renderCard`, so the buttons are the same buttons, and the card
  re-pulls after a tap. Voice runs in `ChauffeurPhoneVoice.start({ host })`:
  one state machine, the overlay a sink for its states; "Starting
  microphone…" has no wave, "Listening…" does; a release before listening
  cancels the turn with "Keep holding until Listening… appears, or type."
  Every exchange lands in the Argyle DM; Messages is the record. Dismiss by
  swipe down, backdrop tap (ignored within 400 ms of open), Escape (ignored
  under a prompt) and hardware Back (a `{pwaOverlay:'argyle'}` history entry
  `PwaNav` ignores; a view change over a pushed screen walks both in one
  `PwaNav.clear({ extra: 1 })`). Reduced motion: no glow, no wave, a plain
  fade. A refused DM shows the server's detail and no input; a 5xx or
  offline is "Could not reach Argyle" with the bar kept. "Ask Argyle" is not
  in More; the old popup and its `surface=pwa` history are gone; the orb and
  the DM are the one path. Never add a second Argyle client to the phone.
- **The tab bar.** An evenly spaced row of equal 44px slots,
  `justify-content: space-between` with 18px edge padding, the first tab
  anchored left and the orb anchored right as the last slot; tabs fill from
  the left, so a two-tab helper bar and a five-tab parent bar obey the same
  rule. Labels may spill past the slot (`white-space: nowrap`; 10px under
  360px). The orb shows only when `pwaOrbAllowed()` (an adult whose scope's
  `chat.agent` is not `none`), hides while the Argyle thread is open, and in
  this slice tapping it opens the Argyle DM in Messages (the Siri-style
  overlay is slice 2). Kid bars never show it.
- **Pushed screens.** `static/pwa_nav.js` (`PwaNav.push({ id, title, render,
  onPop })`, `pop()`, `clear()`, `depth()`, `current()`) owns `#pwa-stack`
  in `components/pwa_shell.html`. A pushed screen is a `.pwa-screen` with a
  `.pwa-back` button ("‹ " + the parent's title) and an `h1`; it rides
  `history.pushState({ pwaScreen, pwaDepth })`, so hardware Back pops one
  screen, an empty stack leaves Back to the browser, and foreign history
  states (the moments gallery) are ignored. `setView` clears the stack, so a
  tab always lands on its root. Anything that "taps in" on an adult screen
  pushes; it never opens a second tab or a full-page route.

Screenshot proof for this slice lives in the live test
(`PWA_REVIEW_OUTPUT=tests/probe_shots/pwa_slice0 python
tests/test_pwa_adult_shell_live.py`).

#### My Day, the brief (slice 1, v2.499.752)

One My Day for every adult (parent, household adult, keeping-up adult);
`static/pwa_myday.js` owns it and paints into `#myday-container`. Helpers,
guests and every child stage are untouched (`renderMyDay` still serves kids;
for an adult it returns to `pwaRenderBrief()` at its first line).

- **Order, top to bottom.** `.pwa-brief-date` (the selected day, a
  `.pwa-brief-pencil` only when an option applies), `.pwa-brief-greet`
  (`pwaGreeting`: the word on line one, the first name on line two) with
  `.pwa-brief-weather` to the right (from `GET /api/weather/now`; null,
  `unavailable` or `unknown` means no slot, never an empty box),
  `.pwa-brief-sentence` (Argyle's one or two sentences, `pwaBriefSentence`
  over `pwaBriefFacts`), the hero (`HeroCard.html(next, {phone: true, now})`),
  "Needs you" (`.pwa-need` cards, absent when the pile is empty), then
  "Your day" (`.pwa-brief-day`, collapsed behind a fade to
  `--pwa-sky-bottom`, `chauffeur_myday_day_open` remembers; a day other than
  today opens expanded and has no hero).
- **The rows are the truth.** Every row "Your day" draws stamps
  `data-kind` (`drive|event|ride|session|routine|task`), `data-start`,
  `data-end`, `data-title`, `data-place`, `data-meta`, `data-state`,
  `data-primary` (the row's own tap), `data-secondary` (drives: the event
  dialog) and `data-all-day`. `pwaRowsFromDom` reads them and `pwaNextThing`
  picks the hero: never a row whose end has passed, never an all-day row, an
  underway row first, ties by kind in that order. A drive stays the hero until
  its arrival time passes, so "Start drive" is there when a person is late.
  The hero's buttons are the row's own handlers; no hero button without a
  row behind it. Drivers' legs and events are the existing `buildTimeline`
  rows, adopted (moved, not cloned) from the active `#pane-drives`; a
  keeping-up adult's day is the Family branch; rides come from the
  member-day payload for every adult.
- **Needs you.** `pwaNeedsYou` ranks requests, reviews (parents), due-soon
  tasks, proposals (parents, one card), situations in `now`, needs-a-driver
  events within seven days (merged by base id) and active status days:
  deadline first, then rank, then title. Each card opens the dialog that
  exists today (`pwaOpenNeed`): the requests sheet, Household reviews, the
  task detail, Plan's proposals or Needs-you lane, the event dialog, the
  status sheet. "Ask for something" is a chip under the pile for roles with
  `can_request`.
- **Sheets reuse the builders.** The status sheet is `renderStatusBanner`
  (chooser and two-tap clear), the requests sheet is `renderRequests`, both
  inside `_pwaModal`. The pencil lists Family status (parents and adults,
  today or later), Ask for something, and the show-whole-day default.
- **Never** fetch an endpoint the brief does not own, restyle a row's
  builder for adults in a way kids would see, or compute a number the
  owning payload already carries.

#### Household, cards then focus (slice 3, v2.499.754)

The adult Household tab is five cards ranked by what needs you, and a tap on
a card pushes a full screen. `static/pwa_household.js` owns it; the kid House
tab (`pwaChildHouseTabs`, the child branches of `renderChores`,
`renderHouseLists` for kids) is untouched.

- **The cards are pure.** `pwaHouseholdCards(pwaHouseholdInputs())` ranks
  Chores, Rewards, Tasks, Lists and Projects & programs by a score computed
  only from the owning payloads (`choresData`, `/api/points`, `rewardsData`
  pools, pending redemptions, `/api/household-tasks` rows with their
  `past_due` / `due_today`, `houseLists[].open_count`, the `runs` field of
  `/api/shopping/runs`, `/api/projects` rows, the household's running
  programs from `/api/programs` with `upcomingWindows(id)[0]` as the next
  session). Each card carries `{id, icon, title, line, pills, faces,
  progress, score, lead, open: {screen}}`; a card whose facet is `none` is
  absent; a lists-only reveal shows only Lists; score 0 sinks in the stable
  order. `pwaHouseholdLead(cards)` writes the one-line lead from the cards'
  structured `lead` fields ("Two things want your yes. Shop day is
  tomorrow."; a session is named only when it is today; "All quiet in the
  house." when every score is 0; otherwise "Nothing needs your yes."). Dates
  within six days are weekdays, beyond that "Dec 20" (`pwaDayLabel`); the
  viewer's own claims read "you have N claimed".
- **A screen adopts, never re-renders.** `pwaOpenHouseScreen(id, segment)`
  pushes `PwaNav.push({id: 'house-' + id, …})` and MOVES the builder's own
  node into the screen body (`#chores-content` for Chores and Rewards,
  `#house-lists` for Lists, `#projects-container` for Projects with one
  `chf-projects-open`); `onPop` puts the node back where it was. Handlers and
  Alpine state survive; no id is ever duplicated. The Tasks screen is
  `renderHouseholdTasks(host)` drawn fresh. `renderChores` stamps
  `data-chore-group="mine|open|check"` and
  `data-reward-group="balances|goals|redemptions"` wrappers for adults and a
  segment (`.pwa-seg[role=group] .pwa-seg-item[aria-pressed]`,
  `data-house-segment` on the body) shows one group; Rewards shows its
  three groups without segments; Projects & programs has Projects /
  Programs. The shared filters `choresMine()`, `choresAvailable()`,
  `choresToCheck()` in app.html feed `renderChores`, the badge and the
  segment counts, so they cannot drift. `#chores-container.dataset.section`
  still mirrors the open screen (`tasks|reviews|rewards|lists|projects`)
  and the cards view carries `data-house="cards"`.
- **Every door still opens.** `pwaSelectHouse(section)` is the shim for the
  old section names; `phoneOpenList` opens the Lists screen (a granted list
  without its card still opens; otherwise the person is told where to find
  it); My Day's review card opens Chores › To check for a chore and Rewards
  for a redemption; the attention dialog's reviews door does the same.
  Writes from a screen (verify, grant, complete, check, add, a program
  write through `afterProgramWrite`) refetch and repaint the cards so Back
  shows the right pills and badge.
- **Threads live on Plan.** `#house-threads` is emitted by
  `paneSectionsHtml()` after `#mind-container` in the Family pane;
  `setView('family')` and a reload onto Plan fetch them;
  `paintPaneSections` only repaints. The builder, its names and its ids are
  unchanged; My Day's pile gains kind `thread`. A child's House still draws
  its own `#house-threads` (created by `pwaChildHouseTabs`).
- **Household tasks on the phone.** `fetchHouseholdTasks` /
  `renderHouseholdTasks` / `completeHouseholdTask` (`{done, member_id}`)
  / `addHouseholdTask` (title, an optional date through `promptInput`, an
  assignee through `promptChoice`); gated by `householdTasksAllowed()`
  (never a child, never `lists.household_tasks` none). My Day's pile gains
  kind `household_task` (overdue / due today, `open: {screen: 'tasks'}`).
- **PwaNav hardening.** A reload with a stale `pwaDepth` in history is
  re-stamped to the root; `push` focuses the screen's `h1` (tabindex −1) and
  `pop`/Back return focus to the opener (or the current tab); while a
  screen is up `#pwa-covered` (the wrapper around every view container;
  the tab bar and `#pwa-stack` sit outside it) is `inert` and
  `aria-hidden`; `setView` clears with `restoreFocus: false`. More's
  directory lives in `components/pwa_directory.html` so it sits inside the
  wrapper.
- **Skin** (`static/pwa_shell.css`, from the mockup): title 34px/700, lead
  16px muted, card `--pwa-card` 22px radius, 44px icon tile, pills (`hot`
  amber `#ffe6cc`, `ok` green), 26px faces with −6px overlap, 6px bar,
  segment 4px/14px with a white `.on` item, adopted rows `--pwa-card` 18px
  radius. Dark through the tokens; reduced motion = no animation.
- **Never** draw a second copy of a builder's node, route a card through
  `setView`, compute a card number the owning module already has, or put
  threads back on Household.

Screenshot proof lives in `tests/test_pwa_household_live.py`
(`PWA_REVIEW_OUTPUT=1` writes `tests/probe_shots/pwa_slice3/`).

Admin dialogs with a body that can grow (the schedule page's event dialog,
`dashboard.html` `#event-modal`; the calendar's, `family_calendar.html`
`#modal-content-container`) are chrome: a `flex flex-col max-h-[90vh]
overflow-hidden` panel with a `shrink-0` header holding the title and the
close button, a `flex-1 min-h-0 overflow-y-auto` body, and a `shrink-0`
footer holding the actions, so nothing a person must reach ever scrolls away.
Such a dialog sits at `z-[90]`, above the sticky top nav (`z-[60]`) and the
Argyle dock (`z-[80]`); a sticky header inside a scrolling drawer is `z-20`,
and body rows carry no z-index of their own. When the dialog has a secondary
block (rules, diagnostics) it becomes a second column at `lg` with each
column scrolling on its own, and stacks below the details on a narrow screen.

When two surfaces draw the same concept, they share ONE builder (the
kiosk-shares-logic / TripLogic pattern — an included component both consumers
load). Existing shared pieces:

- **`components/agenda_row.html`** — `window.agendaEventRow(ev, opts)`: THE way
  an event renders as a row, anywhere. Time label, 4px left color bar, bold
  title, badge slot (driver chip, car chip incl. amber car-swap, covered
  `🤝 name` teal chip, needs-driver red, conflict amber, errand), past events
  at `opacity-45`. Also owns the `.agenda-day` / `.agenda-event` /
  `.agenda-today` CSS and their ha-theme overrides. Consumers: the calendar
  card's agenda view (`family_calendar.html`) and the Family Day card
  (`packing_card.html`).
- **A container of events** (a day on the agenda, an outing on Family Day) is
  an `agenda-day rounded-2xl p-3 flex flex-col gap-2` panel: header line
  (bold identity + chips + status), then `agendaEventRow` children.

If the thing you are drawing is an event, a list of events, or a container of
events — you are not designing anything. You are calling these.

## The vocabulary (with the canonical source)

- **Panels / cards:** `rounded-2xl`, translucent fill + hairline border
  (`.agenda-day`: `rgba(30,41,59,0.5)` + `1px solid rgba(255,255,255,0.08)`),
  never opaque flat boxes. Highlight variant = colored border + soft glow
  (`.agenda-today`).
- **Rows inside a panel:** `rounded-lg px-2.5 py-1.5`, one tier lighter fill
  (`.agenda-event`), 4px left color bar carrying the entity's color.
- **Chips / badges:** `text-[10px] font-bold px-1.5 py-0.5 rounded` on a
  muted fill (`bg-gray-700 text-gray-300`); semantic tints stay translucent
  (`bg-teal-500/20 text-teal-300`, `bg-amber-500/20 text-amber-300`). Pills
  that must catch the eye are the exception and there is at most ONE saturated
  element on a resting row (Family Day's amber `N to pack` pill).
- **Type scale:** big identity numerals/titles `font-extrabold text-white`;
  secondary `text-sm font-bold text-gray-300`; metadata
  `text-[11px] font-semibold text-gray-400`; empty states
  `text-xs text-gray-500 italic`.
- **State treatments:** past/suppressed = opacity (45–50%), never removal;
  canceled = greyed + `line-through`; interactive-off = controls absent from
  the DOM (`x-if`), never hidden.
- **Theming:** wall cards render inside `html[data-panel]` where the
  gray-scale classes are remapped by `panel_skin.html`; HA-embedded surfaces
  get `body.ha-theme` overrides via CSS variables (`--ha-card-bg`,
  `--ha-primary-text`, `color-mix` tints). Never hardcode a one-theme color
  where a sibling uses the remappable vocabulary. PWA surfaces use the token
  layer (shade roles are contracts).
- **Empty states:** an honest sentence in the muted empty style — never a
  blank panel (rule 1: hide only what is not set up).
- **Dialogs:** never `alert()`/`confirm()`/`prompt()` —
  `showGlobalAlert` / `promptConfirm` / `promptInput`.
- **Tailwind is precompiled:** any new class needs
  `python tools/build_tailwind.py` or it silently does nothing.
- **Scrollable panel surfaces:** use the shared `panel_skin.html` scrollbar
  treatment. Drawers, overlays, cards, and per-person lanes must not fall back
  to browser-default tracks or thumbs.
- **Per-person lanes:** preserve a readable minimum lane width. Let the dialog
  widen to its viewport limit, then scroll horizontally. Never squeeze names,
  controls, or task labels until they overlap.

## Where settings go

Every browser admin page carries a page bar (`nav.html`): its tabs, or its
name, and **⚙ Settings** at the right end. The gear opens the active tab's
drawer — `templates/components/settings_drawer.html`, behaviour in
`static/settings_drawer.js` — and nothing else.

1. **Settings for the whole page** live in the page's drawer, never in the
   work flow.
2. **Settings for one item** live in that item's editor (a reward's active
   switch, a child's school hours, a dish's details), not in the drawer.
3. **Work actions that write a setting** stay in the work area: Block sender
   in Intake, Graduate in Mind.
4. **A feature switched off** shows an honest one-line state in the work area
   with a **Turn on…** button that opens the drawer at the switch
   (`settings_off`). Never a blank or silently empty work area.
5. **No pointers** ("settings are now in ⚙") where a setting used to be.
6. **Walls never show settings.** Kiosk, `?tabs=` and panel views render no
   drawer; the macro enforces it.

Mechanics: wrap the existing markup in `{% call settings_drawer(tab, title,
sections) %}` inside the page's own Alpine island and outside any
`<template>`; no `transform`/`filter`/`backdrop-filter` ancestor; each
section root keeps its registry anchor as its `id`; saves report through
`chfSettingsSaving()` / `chfSettingsSaved(ok, message)`. Config and Find a
setting are settings pages and have no drawer.

## Spatial house surfaces

- Put an affordance on the object or room it opens. Its label and icon must
  describe the resulting feature.
- Keep room markers visible at rest. Use a restrained pulse for discovery;
  do not cycle markers through temporary visibility.
- Tapping empty scenery backs out one level. Keep the explicit back control for
  accessibility and recovery.
- A cutaway hides the wall, door, trim, and attached objects registered to that
  room. Openings visible from an adjacent room need an interior face and an
  independent visibility group.
- Exterior windows may carry warm emissive night light. Interior-facing panes
  use room lighting and remain non-emissive.
- Use the clock and compact next-activity card on the exterior for ten-foot
  glanceability. Attention objects inside the house supplement that overlay;
  they do not replace it.
- Prefer grounded physical objects over floating boards. When a board is the
  correct real-world metaphor, mount it above wall trim with visible clearance.

## Process contract for UI agents

1. Read this file, then read the sibling component nearest your shape END TO
   END before writing markup.
2. Every styling choice cites a sibling precedent (file:line) in your report.
3. If no sibling has solved the shape, STOP and say so instead of inventing —
   the controller decides whether a new pattern enters this guide.
4. Prove the result with a rendered screenshot (playwright harness, dark
   theme, wall viewport) — markup that passes tests can still look wrong.
5. Screenshot fixtures must be realistic AND sorted the way the server sorts;
   a demo that misorders data reads as a product bug.
