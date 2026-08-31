# Virtual Instructor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the lesson player Argyle's voice (locally and into the room), ears where a microphone exists, and offered — never automatic — in-session help, with nothing ever recorded.

**Architecture:** Ten generic mechanisms carried by schema additions in `services/program_lessons.py` (sanitizer-guarded), rendered by `templates/components/lesson_player.html` (speech wrapper, cue scheduler, mic engine), routed to rooms through the existing `services/announce.py` path, and taught to the model via `_SYSTEM`. Subjects are content; no subject-specific code.

**Tech Stack:** Python/FastAPI, Alpine.js, precompiled Tailwind, Web Audio + `speechSynthesis` + `getUserMedia` (all local), HA TTS via the announce machinery, Gemini free-tier pools.

**Spec:** `docs/superpowers/specs/2026-08-31-virtual-instructor-design.md` — the binding authority. Read it before any task.

## Global Constraints

- Every task ends with: bump `chauffeur/config.yaml` (Task 1 minor to `2.449.0`, later tasks patch), run the FULL sweep `python chauffeur/tools/test.py` (must print `N/N files passed`, never piped), commit with an evocative subject ending `(vX.Y.Z)`, single-quoted `-m`, no double quotes anywhere in the message, push.
- **Nothing is ever recorded**: no field, endpoint, or storage write may carry a check response, an offer decision, a hint count, a heard note, or a help question. The only persisted practice outcome remains the session log.
- **Every spoken string runs the same screens as visible text** — body language on every origin, physical-technique on generated — through the existing `_screened` in `services/program_lessons.py`.
- **Offers are offered, never automatic.** Declining is one tap.
- **Mic is local-only**, live only inside a listening scene, indicator visible, track released on scene exit and close, no buffer kept or sent. Absent/refused mic degrades the scene to tap-to-confirm.
- **No unprompted speech**: Argyle's voice exists inside an open session plus the wait announces that session explicitly set.
- Preview mode still writes nothing and stays silent into the room (local speech is fine); `hostListens`, the fallback ladder, `edited`-never-regenerated, and outage rules are untouched.
- Never `alert`/`confirm`/`prompt` — `showGlobalAlert`/`promptConfirm`/`promptInput`.
- After ANY template edit run `python chauffeur/tools/build_tailwind.py` (staleness guard hashes whole template bytes).
- Tests are `from harness import check` scenarios; EVERY new scenario added to its file's `if __name__ == '__main__':` footer; markup assertions `re.search`-anchored to the block under test, never bare substrings; geometry/timing verified by EXECUTING extracted JS in Node, not reading it.
- New settings go in `models/schemas.py` + `services/settings_registry.py` (`page='programs'`) + a control on `templates/programs.html` binding the key by name — the registry audits both and fails the sweep otherwise.
- Docstrings explain WHY in prose, in the voice of `services/programs.py`.

---

### Task 1: Scene voice fields in the sanitizer (I1)

**Files:**
- Modify: `chauffeur/services/program_lessons.py` (`sanitize_script` ~line 265 and the caps block ~line 20)
- Test: `chauffeur/tests/test_program_lessons.py`

**Interfaces:**
- Produces: every sanitized scene may carry `speak` (≤200, screened by origin), `speak_lang` (matching `^[a-z]{2}(-[A-Z]{2})?$`, else dropped), `tone` (`'coach'|'calm'`, else dropped), `chime` (`'success'|'fanfare'`, else dropped), `grownup` (bool). Constants `MAX_SPEAK = 200`, `TONES = ('coach', 'calm')`, `CHIMES = ('success', 'fanfare')`.
- Consumes: existing `_clean_text`, `_screened`.

- [ ] **Step 1: Write failing tests** — scenarios: a `say` with `speak` survives with text clamped to `MAX_SPEAK`; `speak` containing a body phrase dies on BOTH origins; `speak` containing a physical-technique phrase dies on `generated` and survives on `cited`; `speak_lang: 'es'` and `'pt-BR'` survive, `'esp'`/`'ES'`/junk dropped (field only, scene kept); `tone: 'calm'` survives, `tone: 'loud'` dropped; `chime: 'fanfare'` survives, junk dropped; `grownup: 1` normalises to `True`, absent stays absent; all five fields survive on every scene type including `show` and `wait`-less current types.
- [ ] **Step 2: Run to verify failure** — `python chauffeur/tests/test_program_lessons.py`.
- [ ] **Step 3: Implement** — one helper applied inside every scene branch before `out.append`:

```python
def _voice_fields(raw: dict, origin: str) -> dict:
    """The fields any scene may carry for Argyle's voice. Screened like
    visible text because the spoken words are the ones a kid obeys."""
    out = {}
    speak = _clean_text(raw.get('speak'), MAX_SPEAK)
    if speak and not _screened(speak, origin):
        out['speak'] = speak
    lang = str(raw.get('speak_lang') or '')
    if _LANG_RE.match(lang):
        out['speak_lang'] = lang
    if raw.get('tone') in TONES:
        out['tone'] = raw['tone']
    if raw.get('chime') in CHIMES:
        out['chime'] = raw['chime']
    if raw.get('grownup'):
        out['grownup'] = True
    return out
```

with `_LANG_RE = re.compile(r'^[a-z]{2}(-[A-Z]{2})?$')`. Merge via `scene.update(_voice_fields(raw, origin))` in each branch.
- [ ] **Step 4: Run tests, sweep, bump minor to 2.449.0, commit, push.**

---

### Task 2: The speech core in the player (I1)

**Files:**
- Modify: `chauffeur/templates/components/lesson_player.html`
- Test: `chauffeur/tests/test_lesson_player_runtime.py`

**Interfaces:**
- Produces: `say(text, lang, tone)` (cancel-before-speak, voice by lang prefix, rate/pitch by tone — `calm` ≈ rate 0.85, `coach` ≈ 1.0 — wrapped so a missing/throwing API never breaks a scene); `playChime(kind)` on the existing Web Audio context; a greeting spoken on `open()` for a REAL (non-preview) session and a send-off on `finish()` — both client template strings from the window's member/program fields, never model text; `enterScene()` speaks `scene.speak`; a mute tap in the header (`muted` flag, session-local) that silences `say` and chimes without touching scenes.
- Consumes: Task 1's fields; the existing `stopSound()` discipline — speech must also be cancelled there.

- [ ] **Step 1: Failing tests** — anchored scenarios: `say(` wrapper exists and wraps `speechSynthesis` in try/catch; `enterScene` body references `scene.speak`; mute tap present in header and gates `say`; greeting built from template strings (assert the builder function contains no fetch and interpolates the member/title fields); `stopSound` cancels speech; preview never speaks the greeting (anchor: the `open()` body's preview branch).
- [ ] **Step 2: Run to verify failure.**
- [ ] **Step 3: Implement.** Speech wrapper pattern:

```javascript
say(text, lang, tone) {
    if (this.muted || !text) return;
    try {
        const s = window.speechSynthesis;
        if (!s) return;
        s.cancel();
        const u = new SpeechSynthesisUtterance(text);
        if (lang) { const v = s.getVoices().find(v => v.lang && v.lang.startsWith(lang)); if (v) u.voice = v; u.lang = lang; }
        u.rate = tone === 'calm' ? 0.85 : 1.0;
        u.pitch = tone === 'calm' ? 0.9 : 1.0;
        s.speak(u);
    } catch (e) { /* a voiceless device still runs the scene */ }
},
```

Greeting: `Ready, ${w.member_name || 'you'}? ${w.title}.` — send-off: `That's the session. Nice work.` (final copy in the player's own voice; keep short). `playChime` reuses the metronome's AudioContext with a two-note figure for `fanfare`, one for `success`.
- [ ] **Step 4: Tailwind, tests, sweep, bump patch, commit, push.**

---

### Task 3: The prompts learn the voice (I1)

**Files:**
- Modify: `chauffeur/services/program_lessons.py` (`_SYSTEM` ~line 341, `_CITED_PROMPT`/`_GENERATED_PROMPT`, `generate_for`)
- Test: `chauffeur/tests/test_program_lessons.py`

**Interfaces:**
- Produces: `_SYSTEM` documents `speak`/`speak_lang`/`tone`/`chime`/`grownup` (and, as later tasks land, their fields — this task adds a placeholder-free description of Task 1's five only) plus a PATTERNS paragraph distilling the catalog: counts for movement, offers on the hard beat, hints for problem-solving, lines for rehearsal, dictation/echo for reading and language, waits for kitchen work, grown-up flags on knife/oven/tool beats, "follow the label — never a rate" for anything chemical. `generate_for` passes two new prompt fields: `who` (from `stages.capabilities(owner)` — `practices_alone` plus the stage/age band; owner fetched via `storage.get_member(program['member_id'])`) and `month` (`now`'s month name, for seasonal programs).
- Consumes: `services/stages.capabilities(member)` (exists, `stages.py:190`).

- [ ] **Step 1: Failing tests** — `inspect.getsource`-level: `_SYSTEM` names each new field and contains the patterns paragraph markers ('follow the label', 'grown-up'); behavioural: a fake pool capturing the prompt shows `month` and the who-line present for a child owner and `practices_alone` reflected; generation still stores clean scenes when the model echoes the new fields (round-trip through the real sanitizer).
- [ ] **Step 2: Run to verify failure.**
- [ ] **Step 3: Implement.** Keep cited discipline explicit in `_CITED_PROMPT`: spoken lines may only restate the material, same as shown ones.
- [ ] **Step 4: Tests, sweep, bump patch, commit, push.**

---

### Task 4: Timed cues (I2)

**Files:**
- Modify: `chauffeur/services/program_lessons.py`, `chauffeur/templates/components/lesson_player.html`
- Test: both test files

**Interfaces:**
- Produces: sanitizer — `do.cues: [{at, say?|count?|chime?}]`, ≤`MAX_CUES = 8`, `at` int clamped to `[0, seconds]` (cues dropped whole when the beat has no `seconds`), `say` ≤120 screened by origin, `count: true` speaks the beat's elapsed rep/second number, `chime: true` ticks. Player — `scheduleCues()` on do-enter: sorted, `setTimeout`-chained off the shared timer, paused/resumed with it, cleared in `stopSound()`.
- Consumes: Tasks 1-2 (`say`, chime path, timer).

- [ ] **Step 1: Failing tests** — sanitizer: cap, clamp, no-seconds drop, screened say-cue dies on generated; player: `scheduleCues` exists, is called from the do-enter path, cleared in `stopSound`, honours pause (anchored to function bodies). Node execution: extract the scheduler, drive it with a fake clock, assert firing order and re-offset after pause/resume.
- [ ] **Step 2-4: red, implement, green, tailwind, sweep, bump, commit, push.**

---

### Task 5: Room voice (I3)

**Files:**
- Modify: `chauffeur/main.py` (new endpoint beside `lesson-scenes`), `chauffeur/services/announce.py` (nothing structural — reuse `announce()`), `chauffeur/templates/components/lesson_player.html`, `chauffeur/templates/home.html` (room binding pass-through if needed)
- Test: `chauffeur/tests/test_lesson_endpoints.py`, `chauffeur/tests/test_lesson_player_runtime.py`

**Interfaces:**
- Produces: `POST /api/lessons/speak {room, text}` — WALL tier (register beside `lesson-scenes` in `services/auth.py`'s rules the same way), `text` ≤200 and passed through `program_lessons._clean_text` + `_screened(text, 'generated')` (the stricter screen — a speaker endpoint takes no origin's word), throttled ≥3s between calls per process (module-level timestamp), routed via `announce.announce(room, text)`. Player — `roomSay(text)` used for session-level lines (greeting, `scene.speak` on scene ENTRY, celebration, send-off) when BOTH panel mode and a room are known; in-beat cues stay local always.
- **Room resolution:** investigate first — the music tile's server-side screen-name/room binding (`home.html` ~5370-5395 and the music tile builder) is the preferred source; pass it into the board's player context if reachable. Where no binding exists, the player asks once with `promptInput` ("Which room is this screen in?") and keeps the answer in `localStorage` (a per-viewer convenience — allowed); a wrong room is recoverable, same bargain `announce.py`'s own docstring makes.
- Consumes: `announce.announce(room, message)` (exists, returns status dict).

- [ ] **Step 1: Failing tests** — endpoint: exists at WALL tier (assert via `auth.resolve` like the `lesson-scenes` tests do), refuses >200 chars with 400, screens a body-phrase text, throttles a second immediate call (fake the clock), routes through a monkeypatched `announce.announce` and returns its status. Player: `roomSay` exists, is used only on the session-level paths (anchored), never inside `scheduleCues`; preview never calls it.
- [ ] **Step 2-4: red, implement, green, tailwind, sweep, bump, commit, push.**

---

### Task 6: Wait choreography (I3)

**Files:**
- Modify: `chauffeur/services/program_lessons.py` (sanitizer: `wait` beat), `chauffeur/main.py` (30s loop + schedule endpoint), `chauffeur/templates/components/lesson_player.html`
- Test: `chauffeur/tests/test_program_lessons.py`, `chauffeur/tests/test_lesson_endpoints.py`

**Interfaces:**
- Produces: sanitizer — `{type:'wait', minutes 1-180 clamped, text ≤MAX_TEXT, announce ≤120 screened}`; offers (Task 7) must reject nested waits, so keep the type name stable. Endpoint `POST /api/lessons/wait {room, minutes, text}` — WALL tier, same screens/throttle idiom as Task 5 — appends `{fire_ts, room, text}` to `storage.get_app_state('lesson_wait_announces')` (a list; prune fired + >24h stale on every write). 30s loop: a block beside the practice-push block that pops due entries and calls `announce.announce` — survives restart because app_state persists; NOT stored on any program row. Player — a `wait` scene renders the countdown, says the "I'll call you" line via `roomSay` when room-bound, schedules through the endpoint, and its Close leaves the announce armed.
- Consumes: Tasks 1, 5.

- [ ] **Step 1: Failing tests** — sanitizer bounds; endpoint appends and prunes (drive `get_app_state`/`set_app_state` directly); loop block: extract the firing predicate into `program_lessons.due_wait_announces(now)` so a test can run it with a fake clock and assert one-shot behaviour (fired entries removed, future kept); player renders wait with countdown and no ambient advance.
- [ ] **Step 2-4: red, implement, green, tailwind, sweep, bump, commit, push.**

---

### Task 7: Offers and again-slower (I4)

**Files:**
- Modify: `chauffeur/services/program_lessons.py`, `chauffeur/templates/components/lesson_player.html`
- Test: both

**Interfaces:**
- Produces: sanitizer — `check.not_yet_offer: {label ≤60, scenes ≤4}` where offer scenes are sanitized recursively with `check`, `wait`, and further offers REJECTED (drop the whole offer, keep the check). Player — tapping "Not yet" on a check that carries an offer shows a chip pair (`label` / `Next time`); accept splices the offer's scenes immediately after the current index (session-local array only), decline advances as today; a check without an offer behaves exactly as today. Separate control: every `do` scene shows a small "Again, slower" tap that replays the beat once at 0.75× (`seconds`/1.33, `metronome_bpm`×0.75, cues re-scaled) — deterministic, no model, no offer needed.
- Consumes: Tasks 1, 4.

- [ ] **Step 1: Failing tests** — sanitizer: nesting rejected, cap enforced, offer text screened; player (anchored + Node where logic is extractable): splice inserts after current index and the spliced scenes are not re-splicable; decline path unchanged; "checks are never stored" scenario extended — `answerCheck` and the offer taps contain no fetch/localStorage/api; again-slower rescales and runs once.
- [ ] **Step 2-4: red, implement, green, tailwind, sweep, bump, commit, push.**

---

### Task 8: Hint ladders (I4)

**Files/Interfaces:** sanitizer — `show` kind `hints` `{steps: ≤4 strings ≤200 each (screened), answer ≤200 (screened)}` added to `PRIMITIVES`; player — renderer: one revealed rung at a time, "Another hint" tap, answer last, rung count shown as position only. Nothing counts or stores how many were used.
- [ ] **Steps: red (validator + anchored renderer scenarios + a no-persistence check on the tap handler), implement, green, tailwind, sweep, bump, commit, push.**

---

### Task 9: The explain-me escape hatch (I4)

**Files:**
- Modify: `chauffeur/main.py`, `chauffeur/models/schemas.py`, `chauffeur/services/settings_registry.py`, `chauffeur/templates/programs.html` (setting control), `chauffeur/templates/components/lesson_player.html`
- Test: `chauffeur/tests/test_lesson_endpoints.py`, `chauffeur/tests/test_lesson_player_runtime.py`

**Interfaces:**
- Produces: `POST /api/programs/{program_id}/lesson-help {phase_name, unit_n, session_label, scene_idx?}` — WALL-allowed (register like `lesson-scenes`), `unit_n` validated with the sibling endpoints' shared bound, builds context from the stored lesson + that scene, calls `model_pools.call_pool_json('interactive', ...)` (a person is waiting — lite pool first), returns `{"answer": ≤2-sentence text}` sanitized through `_clean_text` + `_screened(answer, 'generated')`; per-program 30s throttle; daily cap via new setting `lesson_help_daily_cap` (int, default 20, clamped 0-200; 0 disables) counted in `app_state` by date (a usage counter for a shared quota, not a per-person record — the entry holds a number, never who asked). Player — an "Explain this" tap, hidden in preview, that shows and `say()`s the answer. Nothing stored.
- Consumes: `model_pools.call_pool_json` (exists), sibling validation idiom.

- [ ] **Step 1: Failing tests** — endpoint: gate tier, throttle, daily cap decrements and refuses at 0, cap=0 disables, answer screened, nothing written to the lesson or program (assert storage untouched); settings triangle (schema+registry+page binding) — the registry audit test enforces the rest; player: tap hidden in preview, handler speaks and never writes.
- [ ] **Step 2-4: red, implement, green, tailwind, sweep, bump, commit, push.**

---

### Task 10: Mic engine + presence (I5)

**Files:** `chauffeur/templates/components/lesson_player.html`, `chauffeur/services/program_lessons.py` (validator for `listen`), tests both.

**Interfaces:**
- Produces: sanitizer — `show` kind `listen` `{mode: 'presence'|'pitch'|'tempo', target?, bpm?, seconds 5-120}` (this task validates all three modes; renders `presence` only — `pitch`/`tempo` scenes degrade to tap-confirm until Task 11, reusing the same degrade path as no-mic). Player — `micEngine`: `getUserMedia({audio:true})` lazily on first listening scene; refusal/absence flips the scene to its tap-confirm variant with an honest note; RMS threshold detection for presence ("say it back" advances when you speak); a visible mic dot while the track is live; track stopped and released on scene exit AND on `close()`; no buffer retained anywhere.
- [ ] **Step 1: Failing tests** — validator modes/bounds; player: engine acquires lazily (anchored: not in `open()`), releases in both exits, degrade path renders the tap variant, the mic dot exists, and a source-scan proves no recording API (`MediaRecorder`) and no network call in the engine.
- [ ] **Step 2-4: red, implement, green, tailwind, sweep, bump, commit, push.**

---

### Task 11: Tuner, pitch, tempo (I5)

**Files:** `chauffeur/templates/components/lesson_player.html`, `chauffeur/services/program_lessons.py` (`tuner` validator: `{target?: note}` note-format checked), tests both.

**Interfaces:**
- Produces: `autoCorrelate(buf, sampleRate) -> hz|null` (~2048 window, the standard normalized-autocorrelation approach) + `hzToNote(hz)`; `tuner` renderer — live needle, target note highlighted when given; `listen` `pitch` (advance when the target note holds ~0.5s) and `tempo` (RMS peaks against the metronome click within tolerance) now render live where a mic exists, tap-confirm otherwise.
- [ ] **Step 1: Failing tests** — **Node execution is the substance here**: synthesize sine buffers at known frequencies (A4 440, G3 196, with harmonics and a noise floor) and assert `autoCorrelate` lands within a semitone; `hzToNote` round-trips the validator's note grammar; tempo peak detection on a synthetic click train. Anchored player scenarios for both render paths.
- [ ] **Step 2-4: red, implement, green, tailwind, sweep, bump, commit, push.**

---

### Task 12: Run-lines and fade (I5)

**Files:** `chauffeur/templates/components/lesson_player.html`, `chauffeur/services/program_lessons.py`, tests both.

**Interfaces:**
- Produces: sanitizer — `show` kind `lines` `{pairs: ≤8 of {cue ≤200, line ≤200} (screened), lang?}`; `say` gains `fade: true, passes: 2-4` (ints clamped). Player — `lines`: Argyle `say()`s the cue (with `lang`), waits (presence where mic, tap otherwise), then reveals the line; position dots; `fade`: each tap re-renders the text with a deterministically larger fraction of words blanked (seeded by index, not random, so passes are stable), last pass blank.
- [ ] **Step 1: Failing tests** — validator caps/screens; Node: fade word-selection is deterministic and monotonic across passes; anchored renderer scenarios; lines taps store nothing.
- [ ] **Step 2-4: red, implement, green, tailwind, sweep, bump, commit, push.**

---

### Task 13: Phoneme assets + card voice (I6)

**Files:**
- Create: `chauffeur/static/phonics/manifest.json` (+ audio files where generatable), `chauffeur/tools/gen_phonemes.py`
- Modify: `chauffeur/services/program_lessons.py` (card pair fields), `chauffeur/templates/components/lesson_player.html`
- Test: both

**Interfaces:**
- Produces: cards pairs gain `speak` (≤120 screened), `speak_lang`, `phoneme` (key validated against the manifest's closed set — load the manifest keys server-side once). Player — a speaker tap per card face: `phoneme` plays its static file; else `speak` via `say(text, lang)`; a `phoneme` whose file is missing renders NO tap (the spec's rule: a mispronounced letter sound is worse than silence). `tools/gen_phonemes.py` renders the ~44 phoneme + letter-name set through the house's Piper TTS — **requires the live HA add-on environment; this is a flagged hand step for the user, not CI-runnable** — and writes files + manifest.
- [ ] **Step 1: Failing tests** — validator: unknown phoneme key dropped (field, not pair); manifest loads and is a closed set; player: tap absent without asset (anchored), speaker tap never fetches beyond the static file.
- [ ] **Step 2-4: red, implement (ship the manifest with whatever set can be generated in dev — an empty-but-valid manifest is acceptable and safe), green, tailwind, sweep, bump, commit, push. Note the hand step in the report.**

---

### Task 14: The grown-up flag reaches the player (I6)

**Files:** `chauffeur/services/programs.py` (`practice_windows` row gains `owner_practices_alone` via `stages.capabilities`, same lookup `list_programs_api` already does), `chauffeur/templates/components/lesson_player.html`, tests (`test_program_lessons.py` for the field, runtime for the chip).

**Interfaces:**
- Produces: window rows carry `owner_practices_alone: bool`; the player, on a scene with `grownup: true` when the window says the owner does not practise alone, shows a hand-off chip ("Get a grown-up for this part") and `say()`s it once. Advancing still works — it is a flag, not a lock.
- [ ] **Steps: red (field present in windows for a young owner and absent-capability default true; chip anchored; not a gate), implement, green, tailwind, sweep, bump, commit, push.**

---

### Task 15: The living docs (docs-only)

**Files:** `chauffeur/system_capabilities.md`, and `docs/superpowers/specs/2026-08-31-virtual-instructor-design.md` only if implementation drifted from it (correct whichever is wrong, per house rule: verify the code, then write).

- [ ] **Step 1:** Describe, in the Programs section's existing voice: the ten mechanisms as shipped, the two voice channels and where each applies, the mute tap, the mic rules and degrade, the offer flow, explain-me and its cap setting, wait choreography and its one exception to no-unprompted-speech, the phoneme hand step if still pending, and the never-list verbatim in spirit.
- [ ] **Step 2:** Docs-only commit (sweep not required), bump patch, push.

## Self-Review Notes (already applied)

- Spec coverage: mechanisms 1-10 map to T1-T14 (speak T1-3, cues T4, offers T7, listen T10-11, hints T8, room voice T5, waits T6, cross-arc taps are CONTENT patterns in T3's prompts — the add-to-list/moments taps ride existing endpoints and land as prompt guidance, not new code; tone T1-2, grownup T1+T14); run-lines/fade T12; phonemes T13; escape hatch T9; ladder I1-I6 preserved; follow-on provided-curriculum arc deliberately excluded (memory + spec both note it).
- Consistency: `_voice_fields` (T1) is consumed by T2's `enterScene` speak and T5's room routing; `listen` validator lands once in T10 and T11 only adds renderers; wait type name fixed before T7's nesting rejection references it; throttle idiom defined in T5 and reused by T6/T9.
- No placeholders: every step names exact fields, bounds, and files; the two genuinely environment-bound items (music-tile room binding in T5, Piper generation in T13) are marked as investigation/hand steps rather than pretending certainty.
