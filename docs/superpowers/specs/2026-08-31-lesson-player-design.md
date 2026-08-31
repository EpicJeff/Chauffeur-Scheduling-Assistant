# Lesson player — a session teaches, not just claims the evening

**Status:** design agreed 2026-08-31. Extends the Programs arc
(v2.433.0–v2.436.0): programs already know the phases, the units, the
rotation, and the evenings; this gives the evening itself a body.

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
  created_at, model
}
```

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

Entry: tapping tonight's session on the programs page / programs card.
Input: one row from `practice_windows` plus its slot's `ProgramLesson`
(or none → fallback ladder). Sound is local Web Audio (metronome click);
no TTS in v1. Both themes, both surfaces.

## Generation pipeline

- **Trigger:** watcher tick, once daily — scan
  `practice_windows(tomorrow..+2d)`; any window whose slot lacks a script
  is queued. Background tier (gemma-first; nobody is waiting). Family
  scale is about 2/day. Failure → fallback rendering; retry next tick;
  never announced.
- **Cited plan:** generator re-reads the unit's cited page (`web.py`,
  allowance-aware; threads-arc discipline — content only from pages
  actually read). Beats built from that material; `source_url` carried;
  the player shows the link.
- **Generated plan:** source is the plan's own steps/units. The model
  expands *practice structure* (warmup / new material / review / one
  fix) and is banned from inventing physical-technique specifics.
- **Hand path:** lesson editor on the program page — reorder/edit/delete
  beats, edit primitive params. Sets `edited: true`. No agent tools in
  v1 (deliberate; revisit if asked).
- **Setting:** `program_lessons` toggle in `settings_registry` plus the
  programs page (config-decentralisation rule), default ON. OFF loses
  depth, never practice.

## Primitives contract (v1)

| kind        | params (validated)                        | draws                      |
|-------------|-------------------------------------------|----------------------------|
| `timer`     | seconds                                   | countdown ring             |
| `metronome` | bpm 30–240                                | pulse + Web Audio click    |
| `keyboard`  | keys[] (note names, range-checked)        | SVG keys highlighted       |
| `fretboard` | dots[] {string, fret max 24, finger 1–4}  | SVG neck + dots            |
| `cards`     | pairs[] {front, back}                     | flip cards                 |
| `counter`   | target, label                             | rep/interval counter       |

Adding a primitive never changes the script schema — a new `kind`; old
scripts untouched. Music primitives ship first (P3a), movement/cards
next (P3b).

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

- Actual video generation; TTS narration (announce-arc TTS is a possible
  later layer)
- Agent tools for lesson editing
- Per-response analytics of any kind — no streaks, no accuracy, no
  comparison; there is no field to build one from
