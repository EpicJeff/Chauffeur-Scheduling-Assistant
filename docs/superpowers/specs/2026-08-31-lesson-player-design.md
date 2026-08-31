# Lesson player — a session teaches, not just claims the evening

**Status:** design agreed 2026-08-31. Extends the Programs arc
(v2.433.0–v2.436.0): programs already know the phases, the units, the
rotation, and the evenings; this gives the evening itself a body.
**Amended v2.448.0** (user-reported issues on the shipped v1): the
fretboard primitive is redrawn vertical, book-convention (see the
Primitives contract table) and gains an optional `muted` marker; the
counter primitive paces itself instead of one-tap-per-rep and gains
`seconds_per_rep`, spoken via the browser's own speech API where a voice
exists (see the Player component section's Sound paragraph, and Out of
scope, for why that is not a reversal of "no TTS in v1").

**North star (the user's):** each session opens into something that feels
like a generated video — interactive, modern, engaging for people who grew
up in the tech age. **The reachable version:** a scene-scripted lesson
player. The model writes a small JSON script; a hand-built renderer plays
it with motion, sound, and interaction. The expensive part (interactivity)
is built once; the cheap part (content) is generated per lesson slot.
Actual video generation is out of reach on the free tier and is also the
wrong pedagogy — practice is a *do* loop, not a *watch* loop. A "watch"
feel survives as auto-advancing beats inside the player.

## Why

A session card today says *what* to do ("practice chord changes: G→C,
10 min"). A course says *why*, *how*, what wrong looks like, what good
looks like — then the drill. That lesson layer is the missing 20% of a
course-like experience; the syllabus (phases → units → rotation → steps)
already shipped.

## Decisions locked in this design

- **Slot key, not date key.** A lesson belongs to
  `(program_id, phase_name, unit_index, session_label)` — the distinct
  lesson in the plan's own terms. A session label repeating inside one
  unit's week is ONE script: generated once, reused, edits stick. A new
  unit is a new lesson, as it should be — that is the escalation the
  plan already prescribes (about 6–15 scripts/week family-wide; still
  nothing against the gemma quota).
- **Checks are never stored.** Mid-lesson "got it / almost / not yet"
  taps advance the scene and nothing else. A persisted "not yet" is a
  miss record wearing a quiz's clothes — exactly the field the programs
  module refuses to have. The only persisted outcome remains
  `log_session`; the final check merely prefills the existing "log it?"
  ask. Numbers only go up.
- **Fallback ladder, always.** No script → the window's existing steps
  render as plain say/do beats + timer + end check. The player never
  blocks practice, and ships (P1) before any generation exists.
- **Renderer owns drawing; model owns parameters.** The model never
  emits SVG/HTML — it parameterizes known primitives. A wrong chord spec
  is visible and editable, not buried in prose.
- **An outage is never papered over.** A cited lesson whose page fetch
  fails gets no script, not a generated stand-in.
- **Edited scripts are never regenerated over.**

## Data model

New storage collection `program_lessons` (separate from program rows —
rows stay lean; the program document keeps its guarantee of never
accumulating how somebody is doing):

```
ProgramLesson {
  id, program_id,
  phase_name, unit_index, session_label,   -- the slot key
  origin: 'cited' | 'generated',
  source_url,                              -- cited only
  edited: bool,
  scenes: [Scene, ...],                    -- ~2-5KB JSON
  attempts, note,                          -- why there is no script yet
  created_at, model
}
```

**A replan retires the plan's lessons with it.** Re-curating replaces
`phases` wholesale, `_clean_units` renumbers `n` from 1, and phase names
and rotation labels recur — so a colliding slot would hand the new plan
the old plan's script, and generation's already-has-a-lesson skip means it
would never be replaced. The branch that replaces `phases` calls
`storage.delete_program_lessons`; a second look that finds nothing keeps
both the plan and its lessons. Dropping a program does not: dropping is
not failing, the plan stays, so its lessons still mean what they meant.

### Scene schema v1 — four beat types

```
{type: 'say',   text, emphasis?}                  -- animated text beat
{type: 'show',  primitive: {kind, ...params}, caption?}
{type: 'do',    text, seconds?, metronome_bpm?}   -- live countdown
{type: 'check', ask}                              -- fixed taps, never stored
```

### Sanitizer at the door

Same philosophy as `sanitize_slots` — bounds live in the shape, every
script passes through regardless of origin (model, edit, import):

- At most 12 scenes; per-beat text caps
- bpm clamped 30–240; `do` seconds clamped
- unknown primitive `kind` dropped
- invalid primitive params (fret over 24, key out of range) drop the
  visual, keep the caption text
- curate's body/load/dose screens run on all script text
- generated-origin scripts additionally screened for physical-technique
  prescriptions (deterministic, enforced like load/dose): a violating
  scene is dropped, not reworded

## Player component

`templates/components/lesson_player.html` — shared logic, two
presentations (kiosk-shares-logic / TripLogic pattern):

- **PWA session view:** personal, tap-through
- **`?panel=true` variant:** large type, tap-light

Entry: tapping tonight's session on the programs page / the PWA's session
sheet / the wall's programs card. Input: one row from `practice_windows`
plus its slot's `ProgramLesson` (or none → fallback ladder) — every one of
the three surfaces fetches that lesson itself, or the whole generation
half of this design is invisible behind a tap that looks identical.
`practice_windows` carries `unit_n` so the slot key can be resolved from
the window alone, which is the only way the wall can resolve it at all.
The wall reads a **scenes-only WALL projection**
(`GET /api/programs/{id}/lesson-scenes`) rather than the stored row: a
panel is a place, not a person, and what it may read is decided by what
the endpoint returns — the same call `api/programs/celebrations` makes.

The footer says where the lesson came from: a cited script names and links
its page, a generated one says the app wrote it, and a window with no
script says it is playing the plan's own steps.

Finishing **asks** (`promptConfirm`) before it dispatches, and the
whole-screen tap-to-advance goes inert on the last scene: a session log is
append-only, has no undo, and moves the rung on. On `?panel=true` the
final button says "Finish", not "Log it?" — nothing on the wall listens
for `lesson-player:done`, deliberately.

Sound is local Web Audio (metronome click, and the counter's own rep
tick). **Amended (v2.448.0):** the counter also SPEAKS its count, via the
browser's own `window.speechSynthesis` — no network, no key, no cost —
when a voice is available, falling back to the tick alone when none is
(the HA wall panel plausibly has none; every call is wrapped so a missing
or throwing speech API can never break the counter). This is narrowly a
**spoken rep count**, not narration: numbers only, nothing read from a
`say`/`do` beat's own text, and there is still no server-side or paid TTS
anywhere in this arc — "no TTS in v1" meant no *narration*, and should have
said so. Both themes, both surfaces.

## Generation pipeline

- **Trigger:** the 300s `poll_schedule` loop — the one that already owns
  slow work — once daily by an `app_state` day marker; scan
  `practice_windows(tomorrow..+2d)`; any window whose slot lacks a script
  is queued, **capped at a handful of slots per pass** (each slot is up to
  four pool candidates at a 180s gemma timeout, and the marker is a date,
  so a restart at 07:00 runs the whole sweep in the school run). Never the
  30s push loop, which exists to fire departure notifications on time.
  Background tier (gemma-first; nobody is waiting). Family scale is about
  2/day. Failure → fallback rendering; retry next pass; never announced —
  but always **recorded**: a scenes-less row carries the reason in words
  (the editor prints it) and an attempt count, so a slot that can never
  work stops costing a call a night and "the key is empty" stops being
  indistinguishable from "the sweep has not got there yet". Transient
  failures are recorded and never counted.
- **Cited plan:** generator re-reads the unit's cited page (`web.py`,
  allowance-aware; threads-arc discipline — content only from pages
  actually read). Beats built from that material; `source_url` carried;
  the player shows the link.
- **Generated plan:** source is the plan's own steps/units. The model
  expands *practice structure* (warmup / new material / review / one
  fix) and is banned from inventing physical-technique specifics.
- **Hand path:** lesson editor on the program page — reorder / edit /
  delete beats, and it names where the script came from (origin + source
  link) and why one is missing when a generation failed. Sets
  `edited: true`. Primitive PARAMS are deliberately not hand-editable in
  v1 — a fretboard dot editor is its own surface, and this form is a form,
  not the show; every field it does not expose round-trips untouched, so a
  wording fix never erases a generated chord diagram underneath it. No
  agent tools in v1 (deliberate; revisit if asked).
- **Setting:** `program_lessons` toggle in `settings_registry` plus the
  programs page (config-decentralisation rule), default ON. OFF loses
  depth, never practice.

## Primitives contract (v1)

| kind        | params (validated)                        | draws                      |
|-------------|-------------------------------------------|----------------------------|
| `timer`     | seconds                                   | countdown ring             |
| `metronome` | bpm 30–240                                | pulse + Web Audio click    |
| `keyboard`  | keys[] (note names, range-checked)        | SVG keys highlighted       |
| `fretboard` | dots[] {string, fret max 24, finger 1–4}, muted[] (optional, string numbers 1–6) | **vertical, book-convention diagram (amended v2.448.0):** strings are vertical lines, string 6 (low E) leftmost, string 1 (high E) rightmost, frets run downward; the nut is a thick top line when the window opens at fret 1, else an ordinary fret line plus an `Nfr` position marker beside it; open strings draw an O and muted strings an X, both above the nut; finger numbers stay inside a fretted dot; the window still widens to the dots' own span up to a cap, and a dot that still cannot be placed truthfully draws as a dashed amber ring with its real fret number rather than being clamped silently |
| `cards`     | pairs[] {front, back}, each capped + screened | flip cards             |
| `counter`   | target, seconds_per_rep (optional, 1–10s, default 3 — amended v2.448.0) | **paced rep count:** one tap starts it; it then advances itself on `seconds_per_rep` up to `target`, with a Web Audio tick and, where a voice exists, a spoken number (`window.speechSynthesis`); pause/resume via the same tap; reaching `target` stops itself, visibly, with no tap required |

Adding a primitive never changes the script schema — a new `kind`; old
scripts untouched. Music primitives ship first (P3a), movement/cards
next (P3b).

A stored primitive is **rebuilt from the keys its own validator checked**,
never the model's dict passed through: an invented extra key would
otherwise be stored and shipped whole, past every cap and both screens
(`counter`'s `label` was in this table for one release and was exactly
that — never validated, never rendered; a `show` scene's own `caption` is
the words above a counter). Any free text a primitive carries — today only
a card's `front`/`back` — is capped and screened exactly like a caption,
and a violating face drops the whole scene rather than being reworded.

## Book-spine flow (curate-side)

The "cited" outcome is sometimes hollow: the page read names lesson
books (Piano Adventures) and teaches nothing — the real content is a
purchase away.

- **Detector** (deterministic, in curate): a phase whose steps only name
  a purchasable artifact — "work through / complete [Title]",
  book/primer/level/volume/workbook tokens — and whose units carry no
  instructional url. Errs toward flagging.
- **Approval fork, one tap:** "This path follows *[series]*. Have it /
  will get it?"
  - **yes** → the book stays the spine; sessions cite book units; the
    app generates session *structure* around it (structure labelled
    generated, sequence labelled cited)
  - **no** → curate reruns with books excluded → usually an app-made
    plan, honestly labelled — better than "buy something"
- **Research preference:** the curate prompt ranks pages that *teach*
  above pages that *list*; retailer/roundup pages deprioritized.

## Build ladder (each slice ships alone)

1. **P1 — player, no LLM change:** existing steps render as beats +
   timer + end check, both surfaces
2. **P2 — generated scripts:** watcher trigger, slot storage, origin
   rules, screens, editor, setting
3. **P3a — music primitives** (keyboard, fretboard, metronome);
   **P3b — movement/cards** (counter, cards; timer ships in P1)
4. **Book flow** — detector + approval fork + research preference
   (independent of P1–P3; may ship first)

## Testing

- Sanitizer unit tests: caps, unknown kinds dropped, bad params degrade,
  screens fire on every origin
- Generation: mocked-pool tests (`test_agent_llm_errors` pattern) —
  origin rules, fetch-fail → no script, edited never overwritten
- Player: runtime render test on both surfaces (steps-only fallback AND
  scripted), hand-path reachability test for the editor
- Book flow: fixture plans through the detector and both fork branches
- One critical-path test that actually RUNS the watcher generation tick
  end-to-end (source-reading-tests rule)

## Out of scope (named so nobody wonders)

- Actual video generation; TTS **narration** — reading a `say`/`do` beat's
  own text aloud (announce-arc TTS, routed through Home Assistant's
  `tts.speak`, is a possible later layer for that). The counter's own
  **spoken rep count** (v2.448.0, browser `window.speechSynthesis`, numbers
  only) is a narrow, deliberate exception to that line, not a quiet
  reversal of it — see the Player component section above.
- Agent tools for lesson editing
- Per-response analytics of any kind — no streaks, no accuracy, no
  comparison; there is no field to build one from
