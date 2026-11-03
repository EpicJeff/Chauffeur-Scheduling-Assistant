# The reimagined adult PWA: design

**Date:** 2026-11-03. **Status:** design, approved in conversation screen by screen; not built. **Mockups:** [`../../design/pwa-reimagined/index.html`](../../design/pwa-reimagined/index.html) (open in a browser). **Current-state inventory and gap check:** [`../../design/pwa-reimagined/current-state-inventory.md`](../../design/pwa-reimagined/current-state-inventory.md) (Codex, read-only review).

## Intent

The phone app opens on My Day, and My Day reads as a productivity app: a driver's list of drives with some things waiting at the bottom. The person who uses it every day said it "doesn't have the feel of a thing you want to turn to to help you through your day", and "it just spirals from there". The content is close to right. The presentation is bland and dry, and the rest of the app inherits that.

The reference points the user brought: Hero (tryhero.app) for the daily brief, Signal and Messenger for messages, Siri for an assistant you can summon from anywhere, and the add-on's own wall-panel Home board for "everything you need at a glance". The brief is to find the best example of every screen we have and let that guide the app.

This document describes the adult PWA after that pass. Kid stages keep their current treatment until their own pass.

## Goals

- My Day is a brief you want to turn to: it tells you what kind of day it is, the next thing that happens to you, and what needs you, at a glance, and the full list is one tap away.
- Every adult screen shares one calm, modern vocabulary (soft cards, no hairlines, big type, the warm wash) so the app feels like one thing.
- Argyle is reachable from anywhere, with a presentation that comes and goes like Siri, while the Argyle conversation in Messages stays the one and only record.
- Household is a list of cards, each a door, each saying the state of that thing right now.
- Messages is clean and sparse: no cards, no separators.
- Nothing a person can do today is lost. The inventory is the checklist.

## Non-goals

- No change to data, permissions, auth tiers, scopes, the solver, or any existing API contract. Additive, read-only API growth is allowed where a screen needs a read the add-on does not serve yet (a member-scoped hero, current weather conditions); nothing existing changes shape. This is presentation and arrangement.
- No change to the kid stages (Sprout, Explorer, Navigator, Copilot) beyond the orb joining their bar where the stage already reaches Argyle.
- No new Argyle capabilities. The overlay is a new door onto the agent router that exists.
- No change to the wall panel, kiosk boards or admin pages.
- Not a native app.

## Anti-goals

- A pretty My Day that hides a changed pickup or a needs-a-driver under decoration. Time-critical things come first, always.
- A floating button that sits on a checkbox. The orb lives in the bar, never over content.
- A second visual language inside one screen (an old dark card under a new soft one). Each screen converts whole.
- Drive screens that need reading. Start and Arrived stay thumb-sized and low.
- Argyle inventing a number. Every sentence Argyle says on a screen comes from the rows that screen already fetched.

## Constraints (locked, from the memory files and the design guide)

- An event, a list of events or a container of events is drawn by `components/agenda_row.html` (`agendaEventRow`). The Plan timeline and the collapsed "Your day" list call it; they do not redraw it.
- The hero card is `window.HeroCard` (`components/hero_card.html`), shared with the wall. My Day's hero and the wall's are one renderer with two skins.
- The orb is the wall's `#panel-chat-orb` (markup in `components/control_center.html`, CSS in `templates/ha_theme.html`): same gradient, hairline, ring, lightning glyph, 4.5 s breath. It moves into one shared component both shells include.
- No browser dialogs. `showGlobalAlert`, `promptConfirm`, `promptInput`, `promptChoice`, `_pwaModal`.
- Tailwind is precompiled: run `python tools/build_tailwind.py` after any class change.
- Adult overrides stay scoped to `html[data-audience="adult"]`. Child shells untouched.
- The person's accent colour: `pwaProfilePalette` builds the gray scale and the accent from `member.color_code`. The new surfaces read the same tokens. Nothing hardcodes a hue (the violet in the mockups is the accent token).
- Calendar shows everything; the solver takes the filtered view. Plan is the whole family's feed with people as filters, never a per-person calendar.
- Event lifetime is clock-only. The hero never shows a passed launch as next.
- Every HA touchpoint degrades gracefully: weather absent means no weather, not a blank.
- Never remove anything a person can do without approval first. Part 2 of the inventory is the gap list; every gap is either placed in the design or raised with the user before build.
- Every agent capability has a hand path; the overlay's buttons are the same buttons the screens already have.

## The vocabulary (decided)

- **Wash.** The page background is a vertical gradient that follows the time of day (my call): peach to lavender to pale blue for morning and afternoon, deeper tones in the evening, and the deep version of the same wash in dark mode. It is the same for every person; the person's hue lives in the accent.
- **Cards.** Translucent white (`rgba(255,255,255,.62)` on light), 22 px corners, no border, no shadow at rest. The one raised card on a screen (the hero, the leave-at card) is opaque white with a soft tinted shadow.
- **Type.** Greeting and page titles 34–52 px, weight 700, tight tracking. Row titles 16 px. Secondary 13–14 px. Section labels 18 px weight 600, or 12 px uppercase tracked for sub-sections. Essential times, names and places are never in the faint colour (the audit's contrast finding stands).
- **Chips.** 12 px weight 600, pill, muted fill; one warm "hot" pill per card at most for the thing that needs you; green only for a real good state.
- **Rows in a list.** Avatar or icon, title, one secondary line, right-aligned time or chevron. No separators; spacing does the work.
- **Buttons.** One dark primary (`--ink`) per screen; secondaries on the muted fill; the drive's Arrived is the one green button in the app. 44–56 px targets.
- **Tab bar.** Frosted white, the role's tabs from the left, the orb at the far right, every slot the same width, first and last anchored to the edges, the rest spread evenly.
- **Dialogs.** Pushed screens with a Back for "tap into a card"; `.pwa-sheet` sheets only for short confirmations and pickers. Pushed screens are a stack on the History API (my call, slice 0): hardware and browser Back pop one screen; a reload lands on the tab, never on a pushed screen; `chauffeur_view` keeps storing the tab only.
- **Motion.** The day slide on My Day stays; the orb breathes; the overlay fades and lifts; `prefers-reduced-motion` turns all of it off.

## The screens (decided)

### My Day: the warm brief (mockup A)

**One My Day for every adult.** Today a driver gets the drives timeline (`buildTimeline`), a passenger adult gets the other My Day (`renderMyDay`), and a keeping-up adult has neither and lands on Plan. This pass merges the two renderers into one brief with one data assembly (driver facts and passenger facts both), and the keeping-up adult gets the same My Day with no drive hero: the next thing that happens to them, Needs you, and the family's day. The two-tabs memory rule (both say My Day, change both) is retired by the merge.

Top to bottom:

1. **Date line.** The date centred, a pencil on the right. The pencil opens "what's on my day" (my call: the existing My Day options, which sections show, as a sheet; if there are none today it is omitted, never a dead control). No read-aloud in this pass (the user's decision: the phone voice path never sends a private answer to browser speech, and nothing today speaks arbitrary text; the speaker is dropped rather than bending that rule).
2. **Greeting.** "Good morning, Jeff" in the big type, the first name alone on its own line. Beside it the weather: icon, temperature, one short line ("clearing by 5"). Weather comes from the household's weather entity through HA. The add-on serves only a daily forecast today (`/api/weather/daily`); my call: add a current-conditions read beside it (additive), fall back to today's daily chip when the entity has no current state, and omit the slot with no HA.
3. **The sentence.** One line in the muted colour, Argyle's, built from the rows the page fetched: how many drives, what is unusual today (a needs-a-driver, a status day, a changed pickup, a birthday). Never more than two sentences. The builder is a pure function over the day payload so it is testable without the model; the model may rephrase it only when the user has the provider on, and the numbers must survive.
4. **The hero.** `HeroCard`, phone skin, fed by a member-scoped `next` (my call: the server's `_hero` in `services/home_board.py` grows a member parameter, additive, so the phone and the wall compute "next" in one place; the PWA reads it through the existing home-board route or a sibling of it): kicker ("Next departure · in 28 min"), the big line ("Leave at 3:40"), who and what ("Take Maya to soccer practice"), place, drive time and car on one meta line, then the two real actions: for a drive, Start drive and Ask for cover; for any other kind, the buttons that kind's row carries today on My Day (a session's open-the-lesson, a routine step's done, an appointment's details), and only one button where only one exists. No hero button without a hand path behind it. The hero is the next thing that happens to you, not only a drive: own appointments, program sessions, a routine step that is now, a status day, in that order of what is next by the clock.
5. **Needs you.** The deduplicated pile: requests, reward and chore reviews, due-soon tasks, intake proposals, Mind situations, needs-a-driver legs, packing with things left. One card each: icon, title, one line of why, chevron. Tapping goes to where the decision lives today (the review dialog, the Household card, the Plan day). Ranked by deadline and consequence, as the audit asked. Absent entirely when nothing needs you (no "all clear" card).
6. **Your day.** The full timeline you have today (drives, sessions, routines, own events), drawn by `agendaEventRow` in the new skin, collapsed behind a fade with "Show the whole day". The day arrows and the date strip act on this list; a day other than today opens it expanded. The collapsed state remembers across visits (my call).

Everything the current My Day shows survives: the status banner becomes a Needs-you card or the sentence; the launch row becomes the hero; routines, due-soon, requests, program sessions, "Ask for something" (a chip under Needs you for roles with `can_request`), the moment button (on the row once the event has started) are all placed. The gap check names any I missed.

### Household: cards, then focus

Title "Household", Argyle's one-line lead ("Two things want your yes. Shop day is tomorrow."), then one card per thing in the order of what needs you most (a card with nothing pending sinks; a card the role cannot see is absent):

- **Chores.** Open count, claimed by whom, done waiting on you; chips for the two or three live items.
- **Rewards.** Balances per kid, pending redemptions, family goals with a progress bar.
- **Tasks.** The household to-do list (the due-soon rows' home). Overdue and due-this-week in the line; items needing attention also appear on My Day.
- **Lists.** Each list with its count; shop day in the chip; a packing list shows packed-of-total.
- **Projects & programs.** Running projects and programs with the next session; faces of who is running them. This replaces the Threads section. The threads themselves (the situations lane, `renderHouseThreads` and `situations.js`: a thread's state, next move, asks, notes, photos, Handled, close) are not dropped: a thread that needs a person is a Needs-you card on My Day, every thread stays reachable from Plan's Needs-you lane as today, and the thread detail builder is what opens from both (my call; the user removed threads from Household, not from the app).

Tap a card: a pushed screen with "‹ Household", the thing's title, Argyle's one-line lead, a segment control where the thing has modes (Chores: Mine / Open / To check), and the full content drawn by the builders that exist today (`renderChores`, `renderHouseLists`, the projects page, the reviews content) in the new skin. The lists-only reveal (a member whose chores door is closed but who holds lists) shows only the Lists card.

### Messages: Signal's list, Messenger's thread

**List.** Title "Messages", camera (Add a moment) and compose on the right, a search field. A Moments row across the top (event albums as rings, "Add" first); absent when there are no moments. Then "Pinned": Family and Argyle. Then "Chats", by last message: DMs, event threads (named by event and day), and group rooms. ("Note to self" from the mockup is dropped from this pass: nothing supports a self-DM today and it is not worth the scope.) A row is avatar, name, time, one preview line; unread is weight plus a dot or a count. No cards, no separators.

**Thread.** Back, avatar, name, member line. Day markers. Bubbles: theirs on the muted fill with a small sender name above, mine in the accent. Photos as rounded images in a bubble. Argyle's asks are a white bordered bubble with buttons in the same stream (the chat-card asks that exist today). Compose: + for photos and moments, a text field, a mic; the send button appears when there is text. Helper share mode (contribute, never read) keeps its surface in the new skin. Share-out, guests, the event-thread invitation stay as they are.

### Argyle from anywhere: the orb and the overlay

**The orb** is the far-right slot of the tab bar on every profile whose scope gives it `chat.agent` (parents and household adults by default; helpers and guests only when a parent has granted it, since their default scope is none); it is the wall's orb. Tap to type; hold to talk (the phone voice path that exists). It hides while the overlay is open and while the Argyle thread in Messages is open.

**The overlay** rises over the current screen, which stays put and dims slightly; the screen's edges glow in the orb's gradient; a waveform while listening; your words right-aligned; Argyle's reply in one frosted bubble with its buttons (the same chat-card buttons as in Messages); a text field with the orb as the send; "Swipe down to dismiss · full conversation in Messages". Every exchange is written to the Argyle DM so Messages is the record. The overlay never narrates lateness and never blocks a drive's Arrived. Reduced motion: no glow animation, a plain fade.

"Ask Argyle" leaves More (the user's decision, 2026-11-03: it serves no purpose beside a persistent orb). Its popup (`toggleKioskChat`, `/api/chat?surface=pwa`) kept a second Argyle history that never reached Messages; that history retires with it. The orb and the DM are the one path.

### Plan: the family's week, one day at a time

Title "Plan" with a "Today" reset on the right; Argyle's one-line lead for the day; people as filter chips ("Everyone" default; each member; a chip filters, it never hides the feed's content from the server); the week strip with weekday, date, the weather glyph for the day, and a small count of events; then the day as an hour timeline: coloured blocks per event (the person's colour), the now line, and the solver's leave-at rows as thin tinted strips in the timeline so a drive reads as part of the day. A block tap opens the event the way the Family tab does today (details, then the typed-details builder). Intake and insights keep their doors: intake as a Needs-you card and a "Proposed" chip on the day; insights where they are today. Previous and next day by swipe and by the arrows; the date strip expands as it does today.

### The drive: one sheet, two moments

A pushed screen from the hero (and from a leg on Plan or Your day), "‹ My Day".

**Before.** The leave-at card (time huge, drive time, arrive-by, car and charge), the stops as a vertical line (Home with who to pick up and what to bring; destination with arrive-by and the field or room), "Everybody in?" as tap chips (roll call, never a gate), "Packed?" as tap chips (the packing claims), Start drive (primary), Ask someone to cover, and, where they mean something, the retro-split options and Mark as completed below (same order as today).

**On the road.** The arrival card (place, ETA big, who is aboard), Google / Apple / Waze three across, "Tell {who is waiting}" quick lines and Send my ETA, Arrived (green, the one green button), the retro-split options under it. Nothing on this screen needs reading to drive correctly.

### More and the header

More keeps its tab and its searchable directory, in the new skin: a list of rows with a title and a one-line description, no cards. Profile stays a sheet (appearance, avatar, critter, notifications, voice setup, sign-out). The header shrinks to the date line on My Day and the title on other tabs; identity lives in Profile and on the avatar top-right where a screen needs it (my call: the avatar top-right opens Profile on every tab; search lives in More and Messages, not in the header).

## Dispositions from the gap check

The inventory's Part 2 lists everything the static mockups do not draw. Most of it is the content of the screens the mockups open, which the design draws with the builders that exist today, in the new skin. The rows that needed a placement:

| Gap | Where it lives in the design |
|---|---|
| Notifications bell, telemetry sheet, Clear All, test push | Beside the avatar top-right on every tab; the sheet keeps its content. |
| Feature search in the header | More's search field; the header loses the icon. |
| Presence roster (online stack) in Messages | The Messages header, between the title and the camera/compose icons; same toggle and roster sheet. |
| New chat (recipient pills, DM vs group, initiation limits) | The compose icon in the Messages header opens the existing New-chat sheet. |
| Reactions, message menu (edit, share, delete), lightbox, media grid, composer staging and retry, share-only helper surface, event-thread grants | Inherited by the thread; the bubbles change skin, the handlers do not. |
| Rich cards in the Argyle DM (asks, proposals, missions, projects, program courses) | Inherited; the overlay's reply bubble is the same card builder, one card at a time. |
| Popup history of the old Ask Argyle | Retires with the popup (approved). |
| Intake: Snap a flyer, proposals, Approve / Ignore, edit fields | A "+" in the Plan header opens intake; a day with proposals shows a "Proposed" chip on the strip and the proposal rows above the timeline; the proposal editor is the existing one. |
| Insights / Needs-you lane on Plan (findings, situations, asks) | Stays on Plan above the timeline, in the new skin; the same rows feed My Day's Needs you. |
| All-day entries, trip banners, suppressed entries on the family calendar | A band above the hour timeline for the selected day; trips keep their detail sheet. |
| Event details, assignment (parent assign/change, claim, split legs, conflict preview), outside coverage, cancel/restore, errand Steer, practice rows | The existing event dialog and sheets open from a timeline block or a row; unchanged. |
| Family status banner (protocols, two-tap clear) | A Needs-you card when a status is set or asked for, with the same chooser and clear; the sentence names it. |
| Requests (Yes / Can't / withdraw / Ask for something) | Needs-you cards; "Ask for something" is a chip under Needs you for roles with `can_request`. |
| Routine items (check, streak) and due-soon tasks (See all, Clear all, detail) | Rows inside "Your day" (routine steps at their time) and the Tasks card in Household; the next routine step can be the hero. |
| Optional events (Going / Skip today / Undo) | On the event's row in "Your day" and on the block's detail on Plan. |
| Passenger ride facts (split legs, Where?, Message, Add a moment) | On the ride's row in "Your day" and in the hero when that ride is next. |
| Driver chronology (legs, states, car-swap warning, packing confirmation) | Rows in "Your day" via `agendaEventRow`; the drive screen carries the rest. |
| Drive sheet: Mark as Completed, Not staying / Staying, three-state roll call, on-road packing, Tell-them catalog, Arrived variants, continuation, live lane, failure states | All on the two drive screens; the Tell-them lines are the server's catalog (`services/drive_sheet.py`), not the mockup's samples. |
| Chores: own Mark done, release, assign/unassign, send back with reason, waiting-for-OK; Rewards: grant/reject, approve anyway, family-goal grant/release; Lists: item check, add, needed-by explanations, private lock | The Household focus screens, drawn by the existing builders. |
| Tab badges (Messages unread, Household reviews) | Kept on the tabs. |
| Loading, failure, Try again, offline, per-person cache | Kept on every surface; the audit's honesty rule. |
| Sign-in, PIN, pairing, install, deep links | Untouched. |

## Flows

- **Morning.** Open the app → My Day brief → read-aloud or read → tap the hero → the drive, before → Start drive → on the road → Arrived → back on My Day the hero has moved to the next thing.
- **Something needs you.** My Day → Needs-you card → the decision where it lives (review dialog, Household Chores "To check", Plan day with the needs-a-driver leg) → back; the card is gone.
- **Ask Argyle from anywhere.** Any screen → tap or hold the orb → overlay → say or type → reply with buttons → tap a button or swipe down → the screen is where you left it; the exchange is in Messages › Argyle.
- **Household.** Household → a card → the thing, in full → Back.
- **Messages.** Messages → a row → the thread → compose, + for a photo, mic to talk → Back.
- **Plan.** Plan → a day on the strip → the day's timeline → a block → event details → Back; a leave-at strip → the drive, before.

## Left to the builder

- Exact gradient stops per time of day and the dark-mode counterpart, within the wash rule.
- The sentence builder's phrasing table and its ranking of what is "unusual".
- The Needs-you ranking function (deadline first, then consequence), and which existing dialogs each card routes to.
- The overlay's listening and speaking states on the phone voice path, and how the hold-to-talk gesture coexists with the tab bar.
- How the Household card order is computed (a score per card from its pending counts).
- The Plan timeline's hour density and how overlapping blocks lay out (lanes).
- Where the collapsed/expanded state of "Your day" is remembered.
- Test fixtures: a populated adult day (driver), a passenger adult, a keeping-up adult, a past-only day, an empty day, dark mode, 360 and 390 widths, each profile's tab bar, reduced motion.
- `hero_card.html`, `agenda_row.html` and the orb are not included by `app.html` today; slice 0 includes them.

## Decided with the user after the builder check (2026-11-03)

- No read-aloud speaker on My Day in this pass.
- "Ask Argyle" is removed from More; the orb and the Argyle DM are the one path; the popup's separate history retires. Approved removal.
- One My Day for every adult, the keeping-up adult included (no drive hero for them).

## Calls I made (check these while reading)

1. The wash follows the time of day, not the person; the person's hue is the accent.
2. The pencil on My Day opens the existing My Day options as a sheet, and is absent when there are none.
3. "Your day" remembers collapsed/expanded; a non-today day opens expanded.
4. Tapping a Household card pushes a full screen with Back, not a sheet; pushed screens ride the History API.
5. "Note to self" is dropped.
6. The drive is a pushed screen from the hero, not a bottom sheet.
7. The avatar top-right opens Profile on every tab; search lives in More and Messages.
8. The orb hides inside the Argyle thread and while the overlay is open.
9. The Moments row sits at the top of Messages and is absent with no moments.
10. Kid bars gain the orb only where the stage already reaches Argyle; nothing else changes for kids in this pass.
11. Additive read-only API growth is allowed: a member-scoped hero, current weather conditions.
12. The hero's non-drive action pairs are the buttons the row carries today; one button where only one exists.

## Suggested slices (for the plan)

0. Vocabulary and shell: tokens, the wash, the tab bar with the orb slot, the shared orb component, the pushed-screen chrome. No screen converts yet.
1. My Day: the brief, the phone HeroCard skin, the sentence builder, Needs you, the collapsed day.
2. The orb overlay.
3. Household cards and the focus screens.
4. Messages list and thread.
5. Plan.
6. The drive.

Each slice ships with its own live test that renders the surface in a browser (populated, empty, dark) and a screenshot in `tests/probe_shots`, per the design-guide rule. The design guide gains a section for this vocabulary when slice 0 ships.

## Inherited unchanged

Everything the inventory lists under Profile (avatar editor, critter, appearance, force refresh, push setup, voice enrollment, switch person, sign-out), the More directory's destinations (Projects, Library, Family map, Music, My programs, School, My critter), the lesson player, the school task detail, the trips and occasions sheets, and every confirmation dialog keep their builders and their behaviour. They take the vocabulary (tokens, corners, type) through the shared CSS and nothing else.

## Acceptance

- An adult opens the app and reads, without scrolling: the kind of day, the next thing, and what needs them.
- Every action in the inventory's Part 1 is reachable on the new surfaces; Part 2 is empty or every row has an approved disposition.
- The orb is in the bar for every profile that could reach Argyle before, and never covers content.
- The wall orb and the phone orb are one component.
- Contrast: essential text at 4.5:1 or better on the wash and on cards, light and dark.
- The kid shells render unchanged (their live tests stay green).
