# The instructor — Argyle's voice inside a session

**Status:** design agreed 2026-08-31. Builds on the lesson player
(v2.442.0–v2.448.1): the player already draws, times, and paces a
session; this gives it a voice, ears where a microphone exists, and the
judgment to offer help without ever keeping score.

**Persona:** the instructor IS Argyle — the same assistant that chats,
announces dinner, and speaks on the satellites. One house voice
everywhere; no second identity.

**North star (the user's):** a virtual instructor. The honest version:
the lesson script, spoken in time — talking during the work, not just
before it — plus one live escape hatch. Not a face, not a conversation,
not a judge.

## Why

A lesson script today is read. A five-year-old at the kitchen wall
cannot read it, and a guitarist mid-drill should not have to look up. A
real instructor counts the reps, calls the cue at the right second,
says the letter sound out loud, offers "want to try that slower?" at
the moment it would help — and never files a report afterwards. Every
piece of that is reachable with what the house already owns: browser
speech and Web Audio locally, the announce machinery (satellite or
`tts.speak`, the Argyle pipeline's own voice) for the room, the lite
model pool for the one live question, and a microphone where one
happens to exist.

## The ten mechanisms

Programs run the gamut — school subjects, knife skills, pastries, the
lawn, the school play, the dog. Subjects are CONTENT; these mechanisms
are the code. Nothing below is subject-specific, and every magic moment
in the catalog rides one of them.

1. **Speak fields** — any scene can carry what Argyle says, separate
   from what is shown (a card showing `c` speaks /k/, not "see"), with
   a language tag picking the voice.
2. **Timed cues** — a `do` beat carries `{at, say|count|chime}` lines
   scheduled against its own timer: "switch sides" at 0:30, "last ten
   seconds" near the end.
3. **Offers** — a "not yet" check tap may OFFER a session-local splice
   (a slower repeat, a hint, a re-explanation). Offered, never
   automatic: declining is one tap, and nothing persists either way.
4. **Listen scenes** — tuner needle, "play a G", tempo against the
   click, did-you-speak presence. All local, all optional.
5. **Hint ladders** — tap for the next-narrower nudge, answer last.
6. **Room voice** — session-level lines ride the announce path into the
   room the session runs in.
7. **Wait choreography** — a `wait` beat lets the player close while
   the dough proofs; Argyle calls the kitchen when it is time.
8. **Cross-arc taps** — add-to-shopping-list on an ingredients beat,
   snap-a-moment on a before-after beat. In-session hand-offs to arcs
   that already shipped.
9. **Tone classes** — `coach` and `calm`: one persona, a practice voice
   and a wind-down voice.
10. **Grown-up flag** — a scene that needs an adult (knife out, oven
    in) shows a hand-off chip and says so, driven by the stage
    capabilities the app already holds (`practices_alone`).

Plus two small primitives the catalog demanded: **run-lines** (Argyle
speaks the other character's cue, waits, the kid delivers) and
**progressive-fade memorization** (a `say` that drops more words each
pass until you are reciting).

## Voice architecture

Two channels, split by latency:

- **Room voice** — greeting, scene `speak`s, celebration, wait
  announces. Used when the session runs ON a wall panel: the line goes
  through `services/announce.py`'s existing path — satellite `announce`
  or `tts.speak` on the room's player, in the Argyle pipeline's own
  voice, ducking and resuming whatever plays. Text in, house voice out;
  no audio files to manage.

  **AS BUILT (v2.449.4), correcting this section's first draft:** the
  panel does NOT resolve its own area, because no board-level or
  device-level room binding exists in this app. The music arc's naming is
  a per-CARD `room` option, which is right for music (a card is often
  pointed at another room on purpose) and wrong for a screen, which is in
  exactly one place and cannot have two cards in two of them. The panel
  asks whoever is standing at it, once per device, keeps the answer in
  `localStorage`, and carries a header chip showing the room or offering
  to set one. A host-set `window.chfLessonRoom` wins outright, so a board
  that ever does learn its own room has a door to land in.
- **Local voice** — in-beat material (cues, counts, phonemes, card
  taps) uses the browser's own `speechSynthesis` and the existing Web
  Audio path, because sub-second timing cannot ride an HA round trip.
  No voices installed → the tick alone.

Sessions on personal devices stay fully local — a teenager's lesson
does not play to the kitchen. Greeting and send-off lines are client
template strings (member name + program title), never model-written. A
mute tap is always visible and silences Argyle for the session without
touching the scenes. A duet mode (phone shows, room speaker talks) is
catalog, deferred.

## Script schema additions

Any scene: `speak` (≤200), `speak_lang` (validated tag),
`tone: coach|calm`, `grownup: true`, `chime: success|fanfare`.

- `do` gains `cues: [{at, say?|count?|chime?}]` — ≤8 per beat, `at`
  clamped inside the beat's seconds, `say` ≤120.
- `check` gains `not_yet_offer: {label ≤60, scenes ≤4}` — accept
  splices into THIS session only; offer scenes may not contain offers,
  checks, or waits.
- New `show` kinds: `tuner` {target?}, `listen` {mode:
  pitch|tempo|presence, target?, bpm?, seconds?}, `hints` {steps ≤4,
  answer}, `lines` {pairs ≤8, lang?}.
- `say` variant: `fade: true, passes: 2-4`.
- Cards gain per-pair `speak` / `speak_lang` / `phoneme` (closed-set
  key into the shipped asset set).
- New beat: `wait` {minutes 1-180, text, announce? ≤120}.

**Sanitizer:** every spoken string runs the SAME screens as visible
text — body language on every origin, physical-technique on generated —
because the spoken words are the ones a kid obeys. Phoneme keys are
whitelisted against the shipped set; language tags format-checked; all
caps live at the door, as ever, on every origin including hand edits.

## Player runtime

- **Speech wrapper** — `say(text, lang, tone)`: voice picked by
  language prefix, rate/pitch by tone, cancel-before-speak, wrapped so
  a missing or throwing speech API can never break a scene.
- **Cue scheduler** — rides the existing do-timer; `stopSound()` clears
  it.

  **AS BUILT (v2.449.3), and this is a design change rather than a
  detail:** cues are owed by ELAPSED TIME, not delivered by a chain of
  `setTimeout`s that would need re-offsetting. A timeout chain in a
  backgrounded tab fires late and drifts away from the countdown ring
  beside it — two clocks disagreeing about how far into a beat we are.
  `cuesDueAt(cues, elapsed, fired)` asks the beat's own countdown one
  question instead, so a clock that jumps delivers everything owed at
  once and a stop is simply a clock that stopped ticking. It is pure, and
  is executed under Node against a fake clock rather than read.
- **Mic engine** — `getUserMedia` requested lazily on the first
  listen/tuner scene. Refusal or absence degrades that scene to
  tap-to-confirm with an honest note (a panel may have no mic). Pitch
  by autocorrelation, tempo by RMS peaks against the click, presence by
  threshold. A visible dot while the mic is open; the track is released
  on scene exit and on close; no buffer is ever kept or sent.
- **Offers UI** — chip pair on "not yet"; accept splices, decline
  advances.
- **Wait beats** — countdown shown; the player may be closed and the
  announce still fires. Honest consequence of the no-persistence rule:
  reopening starts the lesson from the top. Stated on the surface, not
  hidden.
- **Phoneme assets** — the ~44 English phonemes plus letter names,
  rendered once with Piper and shipped as static files, because TTS
  mispronouncing a letter sound is worse than silence and the set is
  closed. Missing key → the speaker tap is simply absent.

  **AS BUILT (v2.449.12):** `tools/gen_phonemes.py` renders the set and
  writes `static/phonics/manifest.json`; `program_lessons.phoneme_keys()`
  validates against that manifest and holds no list of its own, so it can
  never drift from the files on disk. **The tool is a HAND STEP on the
  live add-on** and has not been run — the shipped manifest is empty,
  which is the correct empty state: cards still speak ordinary words and
  only the per-phoneme taps are absent.

## Server surface

Two thin endpoints, both WALL-tier like `lesson-scenes`, both screened
and throttled (a speaker endpoint is a prank vector):

- `POST /api/lessons/speak` — ≤200 chars, rate-limited, routed through
  announce's target picking.
- `POST /api/lessons/wait` — the wait scheduler, one-shot; nothing
  stored on the program.

  **AS BUILT (v2.449.5):** a dedicated `lesson_wait_announces` list in
  `app_state`, popped by its own block in the 30s loop beside the
  practice push, rather than riding the pending-notifications machinery.
  That machinery is keyed to drivers and departures and carries a shape a
  wait beat has nothing to put in; a plain persisted queue is one storage
  read when idle, survives a restart the same way, and prunes anything
  more than a day stale rather than announcing dough somebody has already
  thrown out.

And the escape hatch: `POST /api/programs/{id}/lesson-help` — beat
context in, two sentences back from the lite pool, spoken and shown.
Allowed from the wall (the kid stuck at the piano IS the use case),
throttled per program plus a daily cap setting (default 20). Never
stored. Hidden in preview.

## Generation

`_SYSTEM` teaches the new fields plus a PATTERNS paragraph — the
catalog distilled: counts for movement, offers on the hard beat, hints
for problem-solving, lines for rehearsal, dictation and echo for
reading and language, waits for kitchen work, grown-up flags on
knife/oven/tool beats, "follow the label" (never a rate) for anything
chemical. `generate_for` adds two context lines it already can: the
owner's `practices_alone`/age band, and the month (seasonal awareness
for lawn-shaped programs). Cited origin: spoken words come only from
the page, exactly as shown ones do.

## The magic catalog (content, not code)

Reading: letter-sound speaker taps, dictation ("write 'cat'… flip to
check"), sight-word flash, rhyme call-and-response. Language: tagged
vocab cards, count-alongs, echo drills, trip-countdown framing (the
target event already exists on programs). Music: tuner, play-a-G,
tempo checks, spoken count-along metronome. Math: spoken sprints, hint
ladders, times-table chants. Movement: paced reps (shipped), interval
coaching, breathing tone. Kitchen: mise-en-place beats with
add-to-list taps, wait choreography, grown-up flags, technique voiced
only when cited. Lawn/DIY: guided checklists, seasonal prompts,
before-after moment beats, label-not-rates. Performance: run-lines,
interview drills, progressive-fade memorization. Faith: recitation,
fade, language voices, chant meets the pitch listener. Scouts: badge
curricula are curate's ideal food; campouts meet the packing arc. Pets:
the chime is a clicker; Argyle counts while hands hold the leash.

## What it never does

- No record of anything spoken, heard, offered, hinted, or asked. The
  only persisted outcome of practice remains the session log.
- Mic is local-only, live only inside a listening scene, indicator
  always visible, released outside it.
- **No spaced repetition** — remembering what you missed is exactly the
  record this app refuses to keep. Decks rotate by unit; nothing
  remembers your misses. Test-prep families will ask; this is the
  answer.
- No quality judgment: pitch detection knows WHAT note, never whether
  it was good.
- No unprompted speech: Argyle's voice exists inside an open session
  and the wait announces that session explicitly set. Nothing else,
  ever.
- No face, no avatar, no free conversation. A script plus one escape
  hatch.

## Build ladder (each slice ships alone)

1. **I1 — speech core:** speak/tone/lang fields, wrapper,
   greeting/send-off, chimes, sanitizer, prompts. Local only.
2. **I2 — cues:** the cue scheduler and counts on do-beats.
3. **I3 — room voice:** speak endpoint, panel→area routing, wait
   choreography.
4. **I4 — interaction:** offers, again-slower, hint ladders, the
   explain-me endpoint and its cap setting.
5. **I5 — listening:** mic engine, presence, tuner, pitch/tempo,
   echo/lines. Degrades to taps wherever a mic is absent.
6. **I6 — content polish:** fade memorization, phoneme assets, card
   speak taps, grown-up flag, seasonal line.

**Follow-on arc, deliberately separate:** provided curriculum — the PT
sheet, the teacher's assignment book, the badge workbook. A photo
becomes a third origin (`provided`) via the intake vision path, trusted
like cited, spoken only from what the page actually says. The biggest
gap this design surfaced, and too big to smuggle into it.

## Testing

- Sanitizer scenarios for every new field, cap, and screen-on-speak,
  on every origin.
- Node execution of the cue scheduler and the fade logic — geometry and
  timing are verified by running, the lesson this arc's fretboard
  taught.
- Speech wrapper never-throws without a speech API; mic-degrade markup
  where `getUserMedia` is absent.
- Endpoint gates, throttles, caps; the wait one-shot on a fake clock;
  lesson-help writes nothing.
- Announce routing against a fake HA; anchored template scans; the
  full sweep before every commit.
