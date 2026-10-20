# Lesson depth and program-owned scripts

**Status:** rev 1, 2026-10-20. Design approved in chat with two corrections (the session arc and the curation wording were de-biased from language learning to every program type). Next: Codex adversarial review, then the user's review of this file, then the plan.

**Why.** The user's Brazilian Portuguese run was set to 30-minute sessions. Generation produced six scenes, about five minutes of material, three greeting beats and no explanation of anything. The same day the user said scripts belong to the program, not to a run: "There is no way to write the lessons without starting a run of the program in a project. That seems wrong since the lessons are part of the program." This spec fixes both.

## Diagnosis (program_lessons.py as of v2.499.607)

1. **No budget.** The system prompt is a drill template ("a short why, then the drill as do-beats, one check near the end", "at most 10 scenes"); `MAX_SCENES` is 12, `MAX_TEXT` 280, `MAX_SPEAK` 200. `{minutes}` appears as a word in the user prompt. Nothing scales scene count or text to the session length and nothing measures the result.
2. **Thin spine.** The prompt says "build it AROUND these steps, they are the session". The library lesson's steps for that rung were one line: "three common greetings". Curation's GENERATE_SYSTEM asks each unit for a body of "a few sentences" capped at 600 characters, and the script prompt never sees the phase's `what`, the neighbouring lessons or the profile's `assumes` line.
3. **No teaching beat.** `say` is a 280-character memorisation beat with fade passes. The language-shaped primitives (cards with spoken words, cue-and-line rehearsal, listen) exist, but PATTERNS says only "say the word and let them answer". No scene type explains a rule, gives examples or says why.
4. **Weakest pool.** Scripts run on the `background` tier (gemma, then lite); curation runs on `heavy` (flash, lite, gemma).
5. **Per-run scripts.** Keyed `(run id, lesson_id, variant_label)`, written by a nightly sweep or the synchronous `POST /api/programs/lessons/sweep`, which can run for minutes and outlasts the ingress proxy during a model outage (device-found 2026-10-19). Two children on one program get two scripts for the same lesson, and no lesson exists until a run is approved and has windows.

## Decisions (user, 2026-10-20)

- **The library owns scripts.** One script per `(library_id, lesson_id, variant_label)`, written from the public profile. No per-run copies: "otherwise you could end up with different scripts for each run".
- **Scripts are templates.** Personalisation is variable substitution at read time (`{name}`, `{project}`), not a per-run generation with the private starting point.
- **Per-program Write lessons runs as a background job** with visible state on the library card. The synchronous household sweep and its report go.
- **A setting picks the model pool** for script writing.
- **Existing thin lessons** catch up by hand edit or by making a new program. No "fill in the lessons" pass. Curation changes apply to new programs only.
- **Codex agents on this run:** gpt-6-astra, effort high.

Locked rules kept, from the programs, lesson player, instructor and library arcs: no completion count or fraction anywhere; a milestone is the person's call; rotation variants are dealt by date; Back stays; nothing records how a session went (no check, no hint, no help question); an outage is never papered over (a cited lesson whose page will not load gets no script); a hand edit is never regenerated over; the voice ladder is done and is not reopened here (a cue and a scene carry `speak_lang` since v2.499.607).

## 1. Data model

**`library_scripts` (new table, `services/storage.py`).** One row per `(library_id, lesson_id, variant_label)`:
`id, library_id, lesson_id, variant_label, origin (cited | generated), source_url, scenes, edited, model, attempts, note, minutes (the estimate, see §3), created_at`.
Same chokepoint shape as today's `program_lessons`: `_library_script_query`, `upsert_library_script` (refuses to overwrite `edited` unless the write is itself an edit), `get_library_script`, `delete_library_script`, `delete_library_scripts(library_id)`. `scenes` holds the **template**: variables unsubstituted.

**`program_lessons` (existing)** keeps only legacy rows for runs with no `library_id` (unconverted runs). The migration (§7) moves every library run's rows into `library_scripts` and drops them. The table and `storage._lesson_query`'s legacy branch are removed in the release after this one together with the legacy tuple translation already slated.

**Library row.** Unchanged schema. `library._view` adds a read-only projection for the UI: `scripts: {lesson_id: {variant_label: {state, minutes, note, origin, edited}}}` where `state` is `ready | writing | failed | none`, and `writing: {done, total, started_at} | null` from the job state (§6). Script rows never bump the library row's `updated_at`, so a script write never invalidates warm boards; boards do not draw scripts.

**Job state** lives in `app_state['library_script_jobs']`: `{library_id: {started_at, total, done, failed, lesson_id, variant_label}}`. Not on the library row (public, whitelisted fields) and not on any run (the banned-key rule).

## 2. Variables

A script is a template. The closed set:

| token | filled with |
|---|---|
| `{name}` | the runner's first name (run reads); the viewer's first name (library preview) |
| `{project}` | the run's project title (run reads); the library program's title (library preview) |

- `sanitize_script` keeps the two known tokens as written and **strips any other single-word brace token** (`{nome}`, `{age}`), braces included, from every text field. A token that is not a single word (`{a b}`) is left alone: it is text, not a variable.
- `program_lessons.fill(scenes, vars) -> scenes` substitutes in every free-text field a scene can carry: `text`, `speak`, `ask`, `caption`, `announce`, `title`, cue `say`, card `front`/`back`/`speak`, line `cue`/`line`, hint `steps`/`answer`, offer `label`, teach `examples[].text`. Pure, deep-copies, never mutates the stored row.
- Filling happens **server-side at read time**: `GET /api/programs/{id}/lesson`, `GET /api/programs/{id}/lesson-scenes`, `POST /api/programs/{id}/lesson-help` (the beat it reads) and the library preview route. The speak and voice routes receive already-filled text from the client, so a spoken line says the name.
- The hand editor shows the raw template. The system prompt tells the model: "Write {name} wherever a teacher would say the learner's name, and {project} for what they are working towards. Nothing else goes in braces."
- Consequence (user ruling): a run's private `starting_point` no longer feeds script generation. It still feeds nothing else and stays on the run.

## 3. Time budget

`program_lessons.estimate_seconds(scenes) -> int`, pure, from a per-kind table:

| scene | seconds |
|---|---|
| say | 4 + words(text) / 2.5 + words(speak) / 2.5; fading: passes × words(text) / 2.5 |
| teach | 6 + words(text) / 2.5 + words(speak) / 2.5 + 6 × len(examples) |
| do | `seconds` when set, else 60; cues add nothing |
| check | 8 (plus nothing for an offer: offered, not taken) |
| wait | minutes × 60 |
| show: timer, listen | their `seconds` |
| show: metronome | 45 |
| show: keyboard, fretboard, tuner | 20 |
| show: cards | 8 × pairs |
| show: lines | 12 × pairs |
| show: counter | target × seconds_per_rep |
| show: hints | 30 |

Words are whitespace-split. Minutes shown to people are `round(seconds / 60)`.

- **Scene cap scales:** `scene_cap(minutes) = max(12, min(40, minutes))`, replacing the constant `MAX_SCENES` in `sanitize_script(scenes, origin, minutes=None)`; `minutes=None` keeps 12 (hand edits with no run context pass the library's `made_for.minutes`).
- **The prompt states the target:** "This session is {minutes} minutes. Write a script that runs between {0.8 × minutes} and {1.2 × minutes} minutes by this reckoning: {the table above, in words}. Up to {cap} scenes." The old "at most 10 scenes" line goes.
- **Shortfall retry.** After sanitizing, `generate_for` computes the estimate. Under 50 percent of the target it asks once more with the shortfall named: "Your last script ran about {n} minutes of the {minutes} asked. Keep what works and add teaching, practice and review until it fills the session." The longer of the two survives. Still under half: stored anyway with `note = "runs about {n} minutes of {minutes}"`. A short script is never refused for length; it beats plain steps. The retry is one chargeable call like the first and obeys the attempt cap.
- **Caps.** `say`/`do` text stays 280; `teach` text 700, `teach` speak 500; `MAX_SPEAK` 200 for every other scene. Scene text caps are not scaled by minutes: depth comes from more scenes and the teach type, not longer drill beats.

## 4. The teach scene

```json
{"type":"teach","title":"","text":"","examples":[{"text":"","speak_lang":"pt-BR"}],"speak":"","tone":"coach"}
```

- `title` ≤ 80 (optional), `text` ≤ 700 (required, screened), `examples` up to 5 entries of ≤ 160 characters each (optional; an entry is a dict with `text` and an optional `speak_lang` matching `_LANG_RE`; a bare string is accepted as `{text}`), `speak` ≤ 500. Both screens run on title, text, speak and every example; a screened text or title drops the scene, a screened example drops that example, a screened speak drops the speak (the existing voice-field asymmetry).
- **Render** (`lesson_player.html`): heading, paragraph at reading size (not the say beat's display size), examples as a list; tapping an example says it through the existing `say` path in its own language, the same way a card's `speak` plays. Continue as usual. `sayText()`-style helpers are not reused for the paragraph: a teach reads, a say shouts.
- **Help** (`lesson-help`) reads a teach's `title`, `text` and examples as the beat.
- Estimate per §3. The player needs no new timing.

## 5. Session arc and patterns

The system prompt's structure line becomes a four-part arc that fits every program type:

1. **Open** — connect to the previous lesson, only when this lesson builds on it (a language, music, maths, reading); cooking and lawn mostly skip it. Cards or lines from the previous lesson's material. Never more than two scenes.
2. **Teach** — what is new, why it matters, what good looks like. At least one `teach` scene per new idea. The missing piece in every domain.
3. **Work** — the drill as do-beats and primitives. Most of the budget.
4. **Wrap** — one check or one fade.

PATTERNS, by what the session is, says what Teach and Work look like in each domain:

- **music:** teach names the notes or chords and is followed by a keyboard or fretboard show before metronome do-beats; strings tune up first (tuner).
- **movement (anything moved or held):** teach says what the exercise is for and its pacing, never how to hold or move a joint (the physical screen stays); work is counters with spoken counts and switch-overs.
- **cooking and crafts:** teach the technique before the step it applies to; waits carry `announce`; `grownup: true` on heat, blades, power tools.
- **reading and phonics:** teach the sound or rule with cards; work is cards and lines.
- **problem-shaped (maths, puzzles):** teach the rule with one worked example; work is hint ladders, smallest nudge first.
- **language:** teach the rule with examples in both languages (`speak_lang` on the target-language examples); controlled practice through lines (`lang` set) and cards (`speak` + `speak_lang`); free production through a presence `listen`; at most one greeting beat in a session; Open reviews last lesson's words as cards.
- **chemical (fertiliser, cleaner, weedkiller):** follow the label, never a rate or amount. Unchanged.

No praise-fluff, no streaks, no scores, no body composition: unchanged.

## 6. Generation: inputs, pool, job, nightly retry

**Inputs.** `generate_script(library_row, lesson, variant_label, settings)` replaces `generate_for(program, window, unit, settings)`. The user prompt carries: the program title; the phase `name` and `what`; this lesson's title, steps (lesson or variant), body or url and progression; the **previous lesson's** title and body (first 300 characters) when one exists in the ladder; the **next lesson's** title; the public profile's `assumes`, age band label (`library.age_bands`), minutes and sessions per week; the variable instruction (§2). `_context_block(program)` (birthdate, practices-alone, month) is retired: a library script is written once for a profile, not for a person or a month. The grownup flag instruction stays in the system prompt. Cited lessons keep the cited prompt and `web.read_page` rule unchanged; a cited lesson with no url falls through to generated as today.

**Curation (new programs only).** GENERATE_SYSTEM's `units[].body` instruction becomes: "the material itself in the activity's own terms, enough to run the session without looking anything up: the words, the rule and example sentences for a language; the notes, chords or the section of the piece for music; the exercises with sets and reps for movement; the recipe steps for cooking; the sound and the words for phonics". `UNIT_BODY_CHARS` 600 → 1500. `_clean_units` unchanged otherwise. (Pre-existing and out of scope: the load screen `_LOAD_RE` drops any `ml`/`mg` figure, so recipe quantities in millilitres already cannot survive curation.)

**Pool setting.** `lesson_pool` in `settings_registry` (group programs, page `work?tab=projects`, anchor `lessons`): `heavy` ("best available: Flash first, then Lite, then Gemma", default) or `background` ("low cost: Gemma first"). Every script call reads it: the creation job, Write lessons, Regenerate, the nightly retry. The Lessons drawer (`programs_settings.html`) shows it as a two-option select beside Tries per lesson.

**Job.** `library_scripts.write(library_id, lesson_id=None, variant_label=None, actor)`:
- `POST /api/library/{id}/scripts/write` with an optional `{lesson_id, variant_label}` body. Permission: `library.can_edit` (adult creator or parent). Refuses when `programs_enabled` or `program_lessons_enabled` is off, in words.
- With no lesson named: every `(lesson, variant)` of the library row that `needs_script` (no scenes, not edited, attempts under `lesson_max_attempts`), in ladder order. With a lesson named (Regenerate): deletes that script first (a hand edit asks the person to confirm in the UI, `promptConfirm`) and writes it alone.
- Answers 202 at once with the job state. A second request while a job runs for that library answers `{"status":"error","message":"Already writing lessons for this program."}`.
- Runs on one `threading.Thread` per library, daemon. It does not use `deletion.acting_for`: `deletion.KINDS` has no library kind and a library in use cannot be deleted. The job re-reads the library row before each lesson and **stops when the row is gone or archived**, and `storage.delete_library_program` deletes its scripts and clears its job entry.
- State per §1; `done` advances after each lesson whether it wrote or failed; `failed` counts lessons whose call produced nothing (the row's `note` carries the reason as today's `_record_attempt`). The entry is removed when the job ends. **Dead-job guard:** an entry with no progress for 30 minutes is treated as absent by the next read and the next write request may start again.
- Each lesson's call uses `timeout_s=60, gemma_timeout_s=180` as today, so a 12-lesson program with a retry each is bounded at under an hour and a half on the slowest path, and the person is never waiting on the request.

**Triggers.** The job starts automatically after `library.create` (hand), after the run edit's `recurate` branch mints a new library row (Look again), and after Argyle's `propose_program` curates a new row. It is not started by `add_lesson` or `update_lesson` (a new lesson has no content yet; an edited lesson keeps its script until Regenerate, as today).

**Nightly retry.** `generate_due` keeps its 300-second-loop call, day marker, two switches and per-pass limit, and becomes the retry path: for each active run's practice windows in the next two days, resolve the run's library lesson and variant, and when `needs_script` write it on the chosen pool. `sweep_report`, `POST /api/programs/lessons/sweep`, `_LESSON_SWEEP_PARAM_MAX`, the Config button `runLessonSweep`, its report and `playSweepSlot` are removed. The route leaves `services/auth.py`.

**Attempts.** `needs_script`, `_record_attempt` (transient and `deferred` never counted; `migrate_lesson_attempts_paused_v2499` semantics kept), `max_attempts()` and the `lesson_max_attempts` setting carry over to library scripts unchanged.

## 7. Migration and compatibility

`migrate_library_scripts_v2499` (appended to `run_all_migrations`, after `migrate_program_library_v2499`):
- For each library row, gather every `program_lessons` row whose `program_id` is a run with this `library_id`, grouped by `(lesson_id, variant_label)`.
- Per group: an `edited` row wins; else the newest row with scenes; else the newest failure row (its `attempts` and `note` preserved). Insert into `library_scripts` once; a group whose library script already exists is skipped (idempotent). Its `minutes` is computed by `estimate_seconds`.
- Then drop every `program_lessons` row belonging to a run with a `library_id`. Runs with no `library_id` are untouched and keep today's legacy read path.
- One transaction per library row; a row that fails rolls back alone and is logged, never blocking later rows.

**Routes.**
- Kept: `GET /api/programs/{id}/lesson` (now `{"lesson": {scenes (filled), origin, source_url, edited, minutes, note}}`, no model name), `GET /api/programs/{id}/lesson-scenes` (filled scenes, origin, source_url; WALL), `POST /api/programs/{id}/lesson-help`. The legacy `(phase_name, unit_n, session_label)` translation through `resolve_slot` stays for this one release as promised.
- Removed: `PUT` and `DELETE /api/programs/{id}/lesson` (the capability moves to the library routes below), `POST /api/programs/lessons/sweep`.
- New (`SIGNED_IN`, under the existing `/api/library/*` rule): `GET /api/library/{id}/lessons/{lesson_id}/script?variant_label=` (template, any member; `?fill=1` returns the preview filled for the viewer), `PUT` (hand edit, `can_edit`, sanitized with the stored origin and the profile's minutes, `edited: true`), `DELETE` (`can_edit`), `POST /api/library/{id}/scripts/write` (§6).
- Deletion: `deletion.py`'s run cleanup no longer deletes scripts (a run owns none); library delete does. `remove_matches` over `program_lessons_table` stays for legacy rows until the table goes.

## 8. UI

- **Library page and phone More → Library** (`library_page.html`, `library_card.html`): each lesson row gains a script line: a state chip (`writing…`, `ready · about 12 min`, `failed · {note}`, `no script yet`), **Play** (preview, filled for the viewer, opens the player with `preview: true`), **Edit** and **Regenerate** for `can_edit` viewers. Edit is the existing scene editor from `programs_page.html` (`lessonDraft`, per-scene rows, Save) moved into the library page; the phone shows chips and Play only (buttons, not anchors). The card header shows **Write lessons** (`can_edit`), or `Writing lessons · 3 of 12` while the job runs, polled every 10 seconds while a job is visible.
- **Rhythms / programs_page.html:** the per-slot script editor section is replaced by one button "Scripts live in the library: {title}" that opens the library page. Play from a run card is unchanged (it reads the run routes).
- **Settings drawer (`programs_settings.html`):** `lesson_pool` select; Write lessons now and the sweep report removed.
- **Player:** teach render per §4.
- Tailwind rebuilt after the template changes.

## 9. Tests (written first)

`tests/test_program_lessons.py` (extended) and new `tests/test_library_scripts.py`, `tests/test_library_scripts_live.py`:

- Sanitizer: a teach scene survives with title, text, examples, speak; caps 80/700/160/500; a screened example drops only itself; a bare-string example becomes `{text}`; `{name}` and `{project}` survive; `{nome}` is stripped braces and all; `{a b}` is left as text; `scene_cap(30) == 30`, `scene_cap(5) == 12`, `scene_cap(90) == 40`; `sanitize_script(..., minutes=None)` keeps 12.
- Estimate: the table, kind by kind; a fade counts passes; a wait counts minutes; a do without seconds counts 60.
- Fill: every field in §2 substituted; stored row unmutated; unknown vars untouched.
- Generation: the system prompt names the arc, the four domain patterns, the teach scene, the variables; the user prompt carries the target range, the cap, the phase `what`, previous and next lesson, `assumes`, age band; a script under half the target triggers exactly one retry naming the shortfall; the longer survives; still short stores with the note; a full-length script costs one call; a cited lesson still needs its page; the `lesson_pool` setting picks the tier (`heavy` default, `background` when set).
- Routes (TestClient): run `GET lesson` and `lesson-scenes` return filled scenes for the run's member and project; a panel gets filled scenes through lesson-scenes; `lesson-help` reads a teach beat; `PUT /api/programs/{id}/lesson` and `DELETE` answer 404/405; `POST /api/programs/lessons/sweep` is gone and absent from `services/auth.py`; library script `GET` for any member, `PUT`/`DELETE`/`write` refused for a child and for a non-creator adult, allowed for the creator and a parent; `?fill=1` fills with the viewer; `write` answers 202 and a second call "Already writing"; the switches refuse in words.
- Job: writes every lesson lacking a script in ladder order; skips edited and exhausted; Regenerate on one lesson deletes then writes that one; `done`/`failed` advance; the entry clears at the end; a dead entry (31 minutes, no progress) is ignored; the job stops when the library row is deleted mid-run; library delete removes its scripts and job entry.
- Nightly retry: bounded per pass; counts calls not windows; two days out; both switches; uses the pool setting; writes to `library_scripts`, never `program_lessons`.
- Migration: one run → moved; two runs, one edited → the edited one wins; two runs, neither edited → the newest with scenes; failure rows carry attempts; an unconverted run keeps its legacy rows; a second run is a no-op; a corrupt row rolls back alone.
- Curation: GENERATE_SYSTEM names the material-in-its-own-terms instruction; `UNIT_BODY_CHARS == 1500`; a 1400-character body survives `_clean_units`.
- Player (node run of extracted JS): a teach scene renders title, paragraph and examples; an example tap calls `say` with its `speak_lang`; a teach is not drawn through the say branch.
- Live (`test_library_scripts_live.py`, Playwright): the library page shows the chips and the Write lessons button, Writing · n of m while a job is faked, the phone width at light and dark, screenshot; Rhythms shows the "Scripts live in the library" button and no editor.

## 10. Split

- Codex adversarial review of this spec (gpt-6-astra, high) before the plan; findings folded as rev 2.
- Plan by writing-plans. Claude writes every test first. Codex (gpt-6-astra, high) implements each task; a Claude subagent reviews each; Claude runs the live tests locally (Codex's sandbox cannot open the sqlite data dir for Playwright), looks at the screenshots, then the gate (the change's own tests plus `test_lesson_endpoints.py`, `test_library_flows.py`, `test_library_model.py`, `test_programs_curate.py`, `test_lesson_player_runtime.py`, `test_settings_drawer.py`), updates `system_capabilities.md`, bumps and commits.

## 11. Rulings for the user to confirm

(a) A child can no longer hand-edit a script: script edits follow the library's `can_edit` (adult creator or parent).
(b) A run's private starting point no longer feeds scripts; `{name}` and `{project}` are the only personalisation.
(c) A script under half the target after one retry is stored with its minutes shown, never refused.
(d) The run-side `PUT`/`DELETE /api/programs/{id}/lesson` routes and the Rhythms per-slot editor retire; the capability moves to the library page.
(e) The Config "Write lessons now" button and its report retire in favour of the per-program job (approved in chat).
(f) `add_lesson` and `update_lesson` do not start the job; a person taps Write lessons or Regenerate, or the nightly retry picks it up.

## 12. Out of scope

Filling thin bodies on existing programs by model; a per-run personalised script; curriculum re-curation of existing library rows; the voice ladder; spaced repetition or any record of how a session went; removing the legacy tuple translation and `program_lessons` table (next release, already slated); recipe quantities and the load screen.
