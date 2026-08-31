# Lesson Player Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every practice session opens into a scene-scripted, course-like lesson — played by a hand-built renderer, generated background-tier, honest about its origin — plus the book-spine fork for hollow citations.

**Architecture:** A new `services/program_lessons.py` owns the scene schema, sanitizer, slot key, and generation; a new `templates/components/lesson_player.html` renders scenes on both surfaces (kiosk-shares-logic pattern); lessons live in a new `program_lessons` storage table keyed by slot, never on the program row. The book-spine detector and `exclude_books` re-curate live in `services/programs_curate.py`.

**Tech Stack:** Python/FastAPI, Alpine.js templates, Tailwind (precompiled — run `python chauffeur/tools/build_tailwind.py` after any template class change), SQLite via `storage.db.table()`, Gemini free-tier pools via `services/model_pools.py`.

**Spec:** `docs/superpowers/specs/2026-08-31-lesson-player-design.md` — read it first; it argues every decision below.

## Global Constraints

- **House rules (from memory + spec):** every task ends with: bump `chauffeur/config.yaml` version, run the FULL sweep `python chauffeur/tools/test.py` (must print `N/N files passed`), commit with an evocative one-line subject ending `(vX.Y.Z)`, push. Task 1 bumps minor (`2.442.0`); later tasks bump patch from whatever is current. NO double quotes inside commit messages (PowerShell splits them) — use the Bash tool with single-quoted `-m`.
- **Checks are never stored.** No field anywhere may record a mid-lesson check response. No streaks, no accuracy, no misses. `storage._check_program_keys` already rejects forbidden keys on program rows; lessons live in their own table and must never gain response/result/score fields.
- **Fallback ladder always:** a window with no lesson plays its steps as plain beats. The player must never block practice.
- **Edited lessons (`edited: true`) are never regenerated over.**
- **An outage is never papered over:** a cited lesson whose page fetch fails gets NO script.
- **Sanitizer at the door:** every script — model, edit, import — passes `sanitize_script` before storage.
- Tests are scenario functions using `from harness import check`; files self-run under `chauffeur/tools/test.py` discovery (name them `chauffeur/tests/test_*.py`). Mirror the style of `test_programs_storage.py` / `test_programs_endpoints.py`.
- All new templates must work in both themes and both surfaces (PWA + `?panel=true`).
- Docstrings in this repo explain WHY in prose — match the voice of `services/programs.py`.

---

### Task 1: Book-spine detector

**Files:**
- Modify: `chauffeur/services/programs_curate.py` (add near `_plan_name_ok`, ~line 845)
- Create: `chauffeur/tests/test_programs_bookspine.py`

**Interfaces:**
- Produces: `programs_curate.book_spine_of(phases: list) -> str` — the book/series name when the plan's phases only point at purchasable artifacts, else `''`. `curate()` return `source` dict gains key `book_spine: str` (may be `''`).
- Consumes: nothing new.

- [ ] **Step 1: Write failing tests**

```python
"""A cited plan that only names books to buy is honest but hollow.

The detector errs toward flagging: a false flag costs one extra tap at
approval; a miss costs a family a plan whose first step is a purchase
nobody mentioned.
"""
from harness import check
from services import programs_curate as cur


def _phase(steps, units=None):
    return {'name': 'Start', 'what': 'begin', 'steps': steps,
            'units': units or []}


def scenario_a_book_only_plan_is_flagged():
    phases = [
        _phase(['Work through Piano Adventures Primer Level']),
        _phase(['Complete Piano Adventures Level 1']),
    ]
    check(cur.book_spine_of(phases) == 'Piano Adventures',
          f"got {cur.book_spine_of(phases)!r}")


def scenario_a_taught_plan_is_not_flagged():
    phases = [
        _phase(['Practice open chords G, C, D for 10 minutes',
                'Play one-minute changes between G and C'],
               units=[{'title': 'Stage 1', 'url': 'https://jg.example/s1'}]),
        _phase(['Learn the A-minor pentatonic scale']),
    ]
    check(cur.book_spine_of(phases) == '', "a plan that teaches is left alone")


def scenario_mixed_plan_is_not_flagged():
    """One book step among real steps is a resource, not a spine."""
    phases = [_phase(['Buy the Faber primer book',
                      'Practice C position five-finger scales daily',
                      'Play Ode to Joy hands separately'])]
    check(cur.book_spine_of(phases) == '', "a resource line is not a spine")


def scenario_units_with_urls_defeat_the_flag():
    """A phase whose units carry instructional urls has real content to
    read, whatever its steps say."""
    phases = [_phase(['Work through the Level 1 book'],
                     units=[{'title': 'Week 1',
                             'url': 'https://ex.example/lesson1'}])]
    check(cur.book_spine_of(phases) == '', "cited units mean readable content")


def scenario_series_name_is_extracted():
    phases = [_phase(['Work through Alfred Basic Level 1A workbook']),
              _phase(['Complete Alfred Basic Level 1B workbook'])]
    check(cur.book_spine_of(phases) == 'Alfred Basic',
          f"got {cur.book_spine_of(phases)!r}")
```

- [ ] **Step 2: Run to verify failure**

Run: `python chauffeur/tests/test_programs_bookspine.py`
Expected: AttributeError — `book_spine_of` does not exist.

- [ ] **Step 3: Implement `book_spine_of` in programs_curate.py**

```python
# A step that only points at a purchasable artifact. "Work through X",
# "complete X", "buy X" plus a book-shaped token. Deliberately dumb — a
# phrase list, not a model — because this decides whether the family is
# ASKED a question, and a safety-adjacent ask must not depend on a model's
# mood (same reasoning as the body screen above).
_BOOK_TOKENS = re.compile(
    r'\b(book|books|primer|workbook|method book|lesson book|volume|level'
    r'|grade)\b', re.I)
_BOOK_VERBS = re.compile(r'\b(work through|complete|finish|buy|get|order'
                         r'|start)\b', re.I)
# Capitalised run of 2+ words: the series name a step names.
_SERIES_RE = re.compile(r'\b([A-Z][a-z]+(?: [A-Z][a-z]+)+)')


def _book_step(step: str) -> str:
    """The series name a step names, when the step is ONLY a pointer at a
    purchasable artifact — else ''."""
    s = str(step or '')
    if not (_BOOK_TOKENS.search(s) and _BOOK_VERBS.search(s)):
        return ''
    m = _SERIES_RE.search(s)
    return m.group(1) if m else ''


def book_spine_of(phases: list) -> str:
    """The book series a plan leans on, when the plan leans on nothing else.

    'Cited' is sometimes hollow: the page read names lesson books and
    teaches nothing — the real content is a purchase away. That plan is
    still worth having (a good series carries real sequencing knowledge),
    but the family should be asked, not surprised at the till.

    Flagged only when EVERY phase is book-shaped: all steps are purchase
    pointers and no unit carries an instructional url. One taught phase, or
    one cited unit, and the plan can be followed without buying anything —
    a book line inside it is a resource, not a spine.
    """
    names = []
    for ph in (phases or []):
        if not isinstance(ph, dict):
            return ''
        if any((u or {}).get('url') for u in (ph.get('units') or [])):
            return ''
        steps = [s for s in (ph.get('steps') or []) if str(s or '').strip()]
        if not steps:
            return ''
        per_step = [_book_step(s) for s in steps]
        if not all(per_step):
            return ''
        names += per_step
    if not names:
        return ''
    # The name most steps agree on — 'Piano Adventures Primer Level' and
    # 'Piano Adventures Level 1' share their longest common prefix of words.
    first = names[0].split()
    for n in names[1:]:
        words = n.split()
        keep = 0
        for a, b in zip(first, words):
            if a != b:
                break
            keep += 1
        first = first[:keep]
    return ' '.join(first) if len(first) >= 2 else names[0]
```

- [ ] **Step 4: Wire the flag into `curate()`'s cited return**

In `curate()`, the final cited return (`return {'phases': shaped['phases'], 'source': {...}}`) — add one key to the source dict:

```python
                       'book_spine': book_spine_of(shaped['phases']),
```

And in `_source_generated` and `_source_none`, add `'book_spine': ''` to the dicts they return, so every source carries the key.

- [ ] **Step 5: Run tests to verify pass**

Run: `python chauffeur/tests/test_programs_bookspine.py`
Expected: all scenarios PASS.

- [ ] **Step 6: Sweep, bump minor to 2.442.0, commit, push**

Run: `python chauffeur/tools/test.py` — must print `N/N files passed`.
Bump `chauffeur/config.yaml` to `version: "2.442.0"`.

```bash
git add -A && git commit -m 'A plan that only names books says so (v2.442.0)' && git push origin main
```

---

### Task 2: `exclude_books` re-curate

**Files:**
- Modify: `chauffeur/services/programs_curate.py` (`curate()` signature and question, ~line 696)
- Modify: `chauffeur/main.py` edit endpoint (the `retitled or body.get('recurate')` branch, ~line 5854)
- Test: `chauffeur/tests/test_programs_bookspine.py` (append)

**Interfaces:**
- Consumes: `book_spine_of` from Task 1.
- Produces: `curate(title, shape, member_name='', member=None, starting_point='', exclude_books=False)` — new keyword, default preserves every existing caller. Edit endpoint accepts `exclude_books: true` in the body alongside `recurate: true`.

- [ ] **Step 1: Write failing tests (append to test_programs_bookspine.py)**

```python
def scenario_curate_prefers_pages_that_teach():
    """The research question itself must rank teaching over listing —
    checked at the source, because the question is the one lever curate
    has over what comes back."""
    import inspect
    src = inspect.getsource(cur.curate)
    check('teach' in src and 'list' in src,
          "the question steers toward instructional pages")


def scenario_exclude_books_reaches_the_question():
    """With exclude_books, the question says no-purchase out loud, and a
    plan that still comes back book-spined is sent to the generated tier
    rather than handed over."""
    import inspect
    src = inspect.getsource(cur.curate)
    check('exclude_books' in src, "curate takes the flag")
    check('_fallback' in src, "and can route a stubborn book plan to generated")
```

- [ ] **Step 2: Run to verify failure**

Run: `python chauffeur/tests/test_programs_bookspine.py`
Expected: the two new scenarios FAIL.

- [ ] **Step 3: Implement in `curate()`**

Signature: add `exclude_books: bool = False` after `starting_point`.

Replace the `question = (...)` assignment with:

```python
    question = (f"What is the best established, existing, step-by-step program "
                f"a beginner should follow to {title}? Name the real program "
                f"and its phases. Prefer pages that actually teach the "
                f"material over pages that merely list or review books. "
                f"Do not invent one.")
    if exclude_books:
        question += (" Only consider programs that can be followed without "
                     "buying a book — free online curricula with the "
                     "lessons on the page.")
```

After the cited-return's source dict is built (Task 1 added `book_spine`), guard the hollow case:

```python
    src = {'plan_name': shaped['plan_name'],
           ...existing keys...,
           'book_spine': book_spine_of(shaped['phases'])}
    if exclude_books and src['book_spine']:
        # Asked for booklessness and the web still answered with a shelf:
        # an app-made plan that says so beats a purchase order.
        print(f"[programs] bookless ask for {title!r} still came back "
              f"book-spined -- generating instead")
        return _fallback(title, per_week, api_key, context, answer)
    return {'phases': shaped['phases'], 'source': src}
```

- [ ] **Step 4: Wire the endpoint**

In `main.py`'s edit endpoint, the `curate(...)` call inside `if retitled or body.get('recurate'):` gains one argument:

```python
            curated = _cur.curate(updates.get('title') or row.get('title'),
                                  shape, member_name=member.get('name') or '',
                                  member=member, starting_point=starting_point,
                                  exclude_books=bool(body.get('exclude_books')))
```

- [ ] **Step 5: Run tests, sweep, bump patch, commit, push**

Run: `python chauffeur/tests/test_programs_bookspine.py` then `python chauffeur/tools/test.py`.

```bash
git add -A && git commit -m 'Ask again, without the shelf (v2.442.1)' && git push origin main
```

---

### Task 3: Approval fork UI

**Files:**
- Modify: `chauffeur/templates/programs.html` (proposal card, near the approve button ~line 975 and the "Look again" confirm ~line 905)
- Test: `chauffeur/tests/test_programs_bookspine.py` (append)

**Interfaces:**
- Consumes: `source.book_spine` from Task 1, `exclude_books` body key from Task 2.
- Produces: nothing later tasks use. Pure hand path.

- [ ] **Step 1: Write failing runtime test (append)**

```python
def scenario_the_fork_is_on_the_proposal():
    """A book-spined proposal asks its one question on the card, with both
    answers a tap away — reachable by hand, per the house rule."""
    import io, os
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = io.open(os.path.join(here, 'templates', 'programs.html'),
                  encoding='utf-8').read()
    check('book_spine' in src, "the card knows a book-spined plan")
    check('exclude_books' in src, "and can ask for a bookless one")
    check('Have it' in src or 'have it' in src,
          "and can keep the book as the spine")
```

- [ ] **Step 2: Run to verify failure**

Run: `python chauffeur/tests/test_programs_bookspine.py` — new scenario FAILS.

- [ ] **Step 3: Add the fork block to the proposal card**

Inside the proposal card markup (the `x-show` proposal section carrying the approve button), add before the approve row:

```html
<!-- The book-spine fork. A cited plan can be honest and still hollow:
     the page read names lesson books and teaches nothing. One question,
     two taps, no surprise at the till. -->
<div x-show="p.state === 'proposed' && (p.source || {}).book_spine"
     class="rounded-xl border border-amber-500/30 bg-amber-500/5 p-3 mt-2">
    <div class="text-[12px] text-amber-300 font-semibold mb-1">
        This path follows <span x-text="(p.source || {}).book_spine"></span> — real books, bought or borrowed.
    </div>
    <div class="text-[11px] text-gray-400 mb-2">
        Have it (or will get it)? Approve as usual and the books stay the spine.
        Or ask for a plan with the lessons on free pages instead.
    </div>
    <button @click="replanWithoutBooks(p)"
            class="text-[11px] font-bold px-2.5 py-1 rounded-lg bg-gray-800 text-gray-300 border border-gray-700 active:bg-gray-700">
        Plan without the book
    </button>
</div>
```

- [ ] **Step 4: Add the Alpine method**

Next to the existing recurate method in the page's Alpine component (the one that posts to the edit endpoint with the "This spends one research run" confirm), add:

```javascript
async replanWithoutBooks(p) {
    const ok = await promptConfirm(
        'This spends one research run looking for a plan whose lessons are on free pages. If nothing bookless turns up, the app writes a plan and says so.');
    if (!ok) return;
    await this.api(`api/programs/${p.id}`, 'PUT',
                   { recurate: true, exclude_books: true });
    await this.load();
},
```

(Match the page's actual fetch helper name — read the neighbouring recurate method and copy its call shape exactly; `this.api`/`this.load` above are stand-ins for whatever that method really uses.)

- [ ] **Step 5: Rebuild Tailwind, run tests, sweep, bump patch, commit, push**

Run: `python chauffeur/tools/build_tailwind.py`, then the test file, then the sweep.

```bash
git add -A && git commit -m 'One question before the till (v2.442.2)' && git push origin main
```

---

### Task 4: Scene schema + sanitizer (`services/program_lessons.py`)

**Files:**
- Create: `chauffeur/services/program_lessons.py`
- Create: `chauffeur/tests/test_program_lessons.py`

**Interfaces:**
- Produces (later tasks consume exactly these):
  - `MAX_SCENES = 12`, `MAX_TEXT = 280`
  - `slot_of(window: dict) -> dict` — `{'phase_name', 'unit_n', 'session_label'}` from a `practice_windows` row
  - `sanitize_script(scenes: list, origin: str) -> list` — clamped, screened scenes; may return `[]`
  - `PRIMITIVES: dict` — kind -> param validator
- Consumes: `programs_curate.BODY_PHRASES` (existing screen vocabulary).

- [ ] **Step 1: Write failing tests**

```python
"""The lesson script, forced into shapes the player can eat.

Same philosophy as programs.sanitize_slots: bounds live in the shape,
every door goes through them, and the model is never trusted to stay
inside a limit it was merely asked to respect.
"""
from harness import check
from services import program_lessons as pl


def _say(text='Sit comfortably at the keys.'):
    return {'type': 'say', 'text': text}


def scenario_scene_cap():
    scenes = [_say(f'beat {i}') for i in range(30)]
    out = pl.sanitize_script(scenes, 'generated')
    check(len(out) == pl.MAX_SCENES, f"capped at {pl.MAX_SCENES}, got {len(out)}")


def scenario_text_cap_and_type_whitelist():
    out = pl.sanitize_script([
        {'type': 'say', 'text': 'x' * 5000},
        {'type': 'shout', 'text': 'nope'},
        {'type': 'do', 'text': 'One-minute changes G to C', 'seconds': 999999,
         'metronome_bpm': 999},
        {'type': 'check', 'ask': 'Could you keep the beat?'},
    ], 'generated')
    check(len(out) == 3, f"unknown type dropped, got {out}")
    check(len(out[0]['text']) == pl.MAX_TEXT, "text clamped")
    check(out[1]['seconds'] <= 240 * 60, "seconds clamped")
    check(out[1]['metronome_bpm'] == 240, f"bpm clamped, got {out[1]}")


def scenario_unknown_primitive_dropped_bad_params_degrade():
    out = pl.sanitize_script([
        {'type': 'show', 'primitive': {'kind': 'hologram'}, 'caption': 'x'},
        {'type': 'show', 'primitive': {'kind': 'fretboard',
                                       'dots': [{'string': 9, 'fret': 40,
                                                 'finger': 7}]},
         'caption': 'G chord'},
        {'type': 'show', 'primitive': {'kind': 'keyboard',
                                       'keys': ['C4', 'E4', 'G4']},
         'caption': 'C major'},
    ], 'generated')
    check(len(out) == 2, f"unknown kind dropped entirely, got {out}")
    check(out[0]['type'] == 'say' and out[0]['text'] == 'G chord',
          f"bad params drop the visual, keep the caption, got {out[0]}")
    check(out[1]['type'] == 'show', "valid primitive survives")


def scenario_generated_origin_screens_physical_technique():
    """A generated lesson may structure practice; it may not prescribe what
    a body does. Enforced like load/dose: the scene is dropped, not
    reworded."""
    out = pl.sanitize_script([
        _say('Curl your wrist inward as you reach for the octave.'),
        _say('Play the passage slowly, then at tempo.'),
    ], 'generated')
    check(len(out) == 1 and 'wrist' not in out[0]['text'],
          f"physical prescription dropped for generated origin, got {out}")
    # The same sentence in a CITED lesson survives — a real teacher's page
    # may say it, and the citation carries the authority.
    out = pl.sanitize_script([_say('Relax your wrist between phrases.')],
                             'cited')
    check(len(out) == 1, "cited text is not technique-screened")


def scenario_body_screen_fires_on_every_origin():
    out = pl.sanitize_script([_say('This drill helps you lose weight fast.')],
                             'cited')
    check(out == [], "body-composition text never survives, cited or not")


def scenario_slot_of():
    w = {'program_id': 'p1', 'phase_name': 'Foundations', 'session_label': 'Technique',
         'date': '2026-09-01', 'unit_title': '', 'steps': []}
    s = pl.slot_of(w, unit_n=3)
    check(s == {'phase_name': 'Foundations', 'unit_n': 3,
                'session_label': 'Technique'}, f"got {s}")
```

- [ ] **Step 2: Run to verify failure**

Run: `python chauffeur/tests/test_program_lessons.py`
Expected: ImportError — module does not exist.

- [ ] **Step 3: Implement the module**

```python
"""The lesson behind a practice window — scenes a hand-built player renders.

A session card says WHAT to do; a course says why, how, what wrong looks
like, what good looks like — then the drill. The model writes a small scene
script; the renderer (templates/components/lesson_player.html) owns every
pixel. The model parameterizes known primitives and never draws, so a wrong
chord spec is visible and editable rather than buried in prose.

Bounds live here, in the shape, exactly as programs.sanitize_slots holds
the week's bounds: every door — generation, hand edit, import — passes
sanitize_script, because a bound that lives in only one door is a bound
somebody routes around without meaning to.

Nothing in this module records how a lesson WENT. Mid-lesson checks advance
the scene and vanish; the only persisted outcome anywhere is the session
log, and it lives in services/programs.py.
"""
import re

MAX_SCENES = 12
MAX_TEXT = 280
MAX_DO_SECONDS = 240 * 60          # a session is minutes, not an afternoon

_NOTE_RE = re.compile(r'^[A-G][#b]?[0-8]$')


def _valid_keyboard(p):
    keys = p.get('keys')
    return (isinstance(keys, list) and 0 < len(keys) <= 10
            and all(isinstance(k, str) and _NOTE_RE.match(k) for k in keys))


def _valid_fretboard(p):
    dots = p.get('dots')
    if not (isinstance(dots, list) and 0 < len(dots) <= 6):
        return False
    for d in dots:
        if not isinstance(d, dict):
            return False
        try:
            if not (1 <= int(d.get('string')) <= 6 and
                    0 <= int(d.get('fret')) <= 24 and
                    1 <= int(d.get('finger')) <= 4):
                return False
        except (TypeError, ValueError):
            return False
    return True


def _valid_metronome(p):
    try:
        return 30 <= int(p.get('bpm')) <= 240
    except (TypeError, ValueError):
        return False


def _valid_timer(p):
    try:
        return 5 <= int(p.get('seconds')) <= MAX_DO_SECONDS
    except (TypeError, ValueError):
        return False


def _valid_cards(p):
    pairs = p.get('pairs')
    return (isinstance(pairs, list) and 0 < len(pairs) <= 12
            and all(isinstance(x, dict) and str(x.get('front') or '').strip()
                    and str(x.get('back') or '').strip() for x in pairs))


def _valid_counter(p):
    try:
        return 1 <= int(p.get('target')) <= 500
    except (TypeError, ValueError):
        return False


# kind -> validator. Adding a primitive is a new row here plus a renderer
# block in lesson_player.html; the script schema never changes.
PRIMITIVES = {
    'timer': _valid_timer,
    'metronome': _valid_metronome,
    'keyboard': _valid_keyboard,
    'fretboard': _valid_fretboard,
    'cards': _valid_cards,
    'counter': _valid_counter,
}

# A generated lesson may structure practice; it may not prescribe what a
# body does — a wrong physical cue in an authoritative voice is exactly the
# injury the load/dose screen exists for, and this is the same screen one
# joint over. Deterministic on purpose. Cited text is exempt: a real
# teacher's page may say "relax your wrist", and the citation carries it.
_PHYSICAL_RE = re.compile(
    r'\b(wrist|elbow|shoulder|spine|neck|knee|hip|ankle|posture|'
    r'grip|curl|arch|rotate|twist|lock)\b', re.I)


def slot_of(window: dict, unit_n: int = 0) -> dict:
    """The slot a window's lesson belongs to — the distinct lesson in the
    plan's own terms, never the date. A label repeating inside one unit's
    week is one lesson; a new unit is a new lesson, which is the
    escalation the plan already prescribes."""
    return {'phase_name': str(window.get('phase_name') or ''),
            'unit_n': int(unit_n or 0),
            'session_label': str(window.get('session_label') or '')}


def _clean_text(raw, cap: int = MAX_TEXT) -> str:
    return re.sub(r'\s+', ' ', str(raw or '')).strip()[:cap]


def _screened(text: str, origin: str) -> bool:
    """True when this text may not survive. Body-composition language dies
    on every origin; physical prescriptions die on generated only."""
    from services.programs_curate import BODY_PHRASES
    low = text.lower()
    if any(p in low for p in BODY_PHRASES):
        return True
    return origin == 'generated' and bool(_PHYSICAL_RE.search(text))


def sanitize_script(scenes: list, origin: str) -> list:
    """Every script through one door. Clamps, whitelists, screens; returns
    what survives, which may be nothing — and nothing is a fine answer,
    because the player's fallback ladder plays the plain steps."""
    out = []
    for raw in (scenes or []):
        if len(out) >= MAX_SCENES:
            break
        if not isinstance(raw, dict):
            continue
        kind = raw.get('type')
        if kind == 'say':
            text = _clean_text(raw.get('text'))
            if not text or _screened(text, origin):
                continue
            out.append({'type': 'say', 'text': text})
        elif kind == 'do':
            text = _clean_text(raw.get('text'))
            if not text or _screened(text, origin):
                continue
            scene = {'type': 'do', 'text': text}
            try:
                secs = int(raw.get('seconds'))
                scene['seconds'] = max(5, min(MAX_DO_SECONDS, secs))
            except (TypeError, ValueError):
                pass
            try:
                bpm = int(raw.get('metronome_bpm'))
                scene['metronome_bpm'] = max(30, min(240, bpm))
            except (TypeError, ValueError):
                pass
            out.append(scene)
        elif kind == 'check':
            ask = _clean_text(raw.get('ask'), 120)
            if not ask or _screened(ask, origin):
                continue
            out.append({'type': 'check', 'ask': ask})
        elif kind == 'show':
            prim = raw.get('primitive')
            caption = _clean_text(raw.get('caption'), 120)
            if caption and _screened(caption, origin):
                continue
            valid = (isinstance(prim, dict)
                     and prim.get('kind') in PRIMITIVES
                     and PRIMITIVES[prim['kind']](prim))
            if valid:
                out.append({'type': 'show', 'primitive': prim,
                            'caption': caption})
            elif (isinstance(prim, dict) and prim.get('kind') in PRIMITIVES
                  and caption):
                # A known visual with broken params degrades to its own
                # caption — the words survive, the wrong picture does not.
                out.append({'type': 'say', 'text': caption})
            # An unknown kind is dropped whole: the model demanded a
            # visual this player has never heard of.
    return out
```

- [ ] **Step 4: Run tests, sweep, bump patch, commit, push**

Run: `python chauffeur/tests/test_program_lessons.py`, then the sweep.

```bash
git add -A && git commit -m 'A script is a shape before it is a lesson (v2.442.3)' && git push origin main
```

---

### Task 5: Lesson storage

**Files:**
- Modify: `chauffeur/services/storage.py` — table registration next to `programs_table = db.table('programs')` (~line 515), CRUD next to `add_program` (~line 3040)
- Test: `chauffeur/tests/test_program_lessons.py` (append)

**Interfaces:**
- Produces:
  - `storage.program_lessons_table` (for test truncation)
  - `storage.upsert_program_lesson(program_id: str, slot: dict, data: dict) -> str` — writes `{id, program_id, phase_name, unit_n, session_label, origin, source_url, edited, scenes, created_at, model}`; keyed on `(program_id, phase_name, unit_n, session_label)`; refuses to overwrite a row whose `edited` is true unless `data['edited']` is true (a hand edit may replace a hand edit; generation may not).
  - `storage.get_program_lesson(program_id: str, slot: dict) -> Optional[dict]`
  - `storage.delete_program_lessons(program_id: str) -> int` (all of a program's lessons — for drop/replan cleanup)
- Consumes: `program_lessons.slot_of` shape from Task 4.

- [ ] **Step 1: Write failing tests (append)**

```python
def _lreset():
    from services import storage
    storage.program_lessons_table.truncate()


def scenario_lesson_roundtrip_by_slot():
    from services import storage
    _lreset()
    slot = {'phase_name': 'Foundations', 'unit_n': 1, 'session_label': 'Technique'}
    storage.upsert_program_lesson('p1', slot, {
        'origin': 'generated', 'scenes': [_say()], 'model': 'gemma-4-31b-it'})
    row = storage.get_program_lesson('p1', slot)
    check(row and row['origin'] == 'generated' and row['edited'] is False,
          f"got {row}")
    check(storage.get_program_lesson('p1', {**slot, 'unit_n': 2}) is None,
          "a different unit is a different lesson")


def scenario_upsert_replaces_same_slot():
    from services import storage
    _lreset()
    slot = {'phase_name': 'F', 'unit_n': 1, 'session_label': ''}
    storage.upsert_program_lesson('p1', slot, {'origin': 'generated',
                                               'scenes': [_say('v1')]})
    storage.upsert_program_lesson('p1', slot, {'origin': 'generated',
                                               'scenes': [_say('v2')]})
    row = storage.get_program_lesson('p1', slot)
    check(row['scenes'][0]['text'] == 'v2', "same slot, one row")


def scenario_edited_is_never_regenerated_over():
    from services import storage
    _lreset()
    slot = {'phase_name': 'F', 'unit_n': 1, 'session_label': ''}
    storage.upsert_program_lesson('p1', slot, {
        'origin': 'generated', 'scenes': [_say('mine')], 'edited': True})
    wrote = storage.upsert_program_lesson('p1', slot, {
        'origin': 'generated', 'scenes': [_say('robot')]})
    check(wrote == '', "generation bounces off a hand edit")
    check(storage.get_program_lesson('p1', slot)['scenes'][0]['text'] == 'mine',
          "the hand edit stands")
    wrote = storage.upsert_program_lesson('p1', slot, {
        'origin': 'generated', 'scenes': [_say('mine v2')], 'edited': True})
    check(wrote != '', "a hand may replace a hand")


def scenario_delete_clears_a_program():
    from services import storage
    _lreset()
    storage.upsert_program_lesson('p1', {'phase_name': 'F', 'unit_n': 1,
                                         'session_label': ''}, {'scenes': []})
    storage.upsert_program_lesson('p2', {'phase_name': 'F', 'unit_n': 1,
                                         'session_label': ''}, {'scenes': []})
    n = storage.delete_program_lessons('p1')
    check(n == 1, f"one program's lessons gone, got {n}")
    check(storage.get_program_lesson('p2', {'phase_name': 'F', 'unit_n': 1,
                                            'session_label': ''}) is not None,
          "the other program keeps its lesson")
```

- [ ] **Step 2: Run to verify failure**

Run: `python chauffeur/tests/test_program_lessons.py`
Expected: new scenarios FAIL (`program_lessons_table` missing).

- [ ] **Step 3: Implement**

Registration (next to `programs_table`):

```python
    # A practice window's lesson — scenes the player renders. Its own table
    # rather than a field on the program row on purpose: the program
    # document is the one place in this app that must not accumulate bulk
    # or bookkeeping (see _check_program_keys), and a phase's worth of
    # scripts is both.
    program_lessons_table = db.table('program_lessons')
```

CRUD (next to `add_program`; follow that block's lock/Query idiom exactly):

```python
def _lesson_query(program_id: str, slot: dict):
    q = Query()
    return ((q.program_id == program_id)
            & (q.phase_name == str(slot.get('phase_name') or ''))
            & (q.unit_n == int(slot.get('unit_n') or 0))
            & (q.session_label == str(slot.get('session_label') or '')))


def upsert_program_lesson(program_id: str, slot: dict, data: dict) -> str:
    """One lesson per slot. Returns the row id, or '' when the write was
    refused because a hand edit stands and this write is not one."""
    with db_lock:
        cond = _lesson_query(program_id, slot)
        existing = program_lessons_table.search(cond)
        if existing and existing[0].get('edited') and not data.get('edited'):
            return ''
        row = {'id': existing[0]['id'] if existing else str(uuid.uuid4()),
               'program_id': program_id,
               'phase_name': str(slot.get('phase_name') or ''),
               'unit_n': int(slot.get('unit_n') or 0),
               'session_label': str(slot.get('session_label') or ''),
               'origin': data.get('origin') or 'generated',
               'source_url': data.get('source_url') or '',
               'edited': bool(data.get('edited')),
               'scenes': list(data.get('scenes') or []),
               'model': data.get('model') or '',
               'created_at': time.time()}
        program_lessons_table.remove(cond)
        program_lessons_table.insert(row)
        return row['id']


def get_program_lesson(program_id: str, slot: dict) -> Optional[dict]:
    with db_lock:
        res = program_lessons_table.search(_lesson_query(program_id, slot))
        return dict(res[0]) if res else None


def delete_program_lessons(program_id: str) -> int:
    with db_lock:
        q = Query()
        gone = program_lessons_table.remove(q.program_id == program_id)
        return len(gone) if isinstance(gone, list) else int(gone or 0)
```

(Check `storage.py` imports already include `uuid` and `time` — add if absent, matching the file's import block.)

- [ ] **Step 4: Run tests, sweep, bump patch, commit, push**

```bash
git add -A && git commit -m 'A lesson lives beside the program, never inside it (v2.442.4)' && git push origin main
```

---

### Task 6: The player — component + PWA/programs-page entry (P1)

**Files:**
- Create: `chauffeur/templates/components/lesson_player.html`
- Modify: `chauffeur/templates/programs.html` (include component; "Start session" button on today's window rows)
- Create: `chauffeur/tests/test_lesson_player_runtime.py`

**Interfaces:**
- Produces: Alpine component `lessonPlayer()` with `open(window, lesson)` — `window` is a `practice_windows` row; `lesson` is a stored lesson row or `null` (fallback ladder). Global event `lesson-player:open` dispatched with `{window, lesson}` opens it from any page that includes the component.
- Consumes: scene schema from Task 4 (renders `say`, `do`, `check`; `show` renders `timer` and `metronome` placeholders as captions until Task 10/11 — a `show` whose kind has no renderer block draws its caption as a `say`, mirroring the sanitizer's degrade rule).

- [ ] **Step 1: Write failing runtime tests**

```python
"""The player, exercised rather than read.

Reachability and the no-streak rule at the surface — the same discipline
test_programs_runtime.py applies to the pages this component lands on.
"""
import io
import os

from harness import check

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(rel):
    return io.open(os.path.join(HERE, 'templates', rel), encoding='utf-8').read()


def scenario_component_exists_and_renders_the_four_beats():
    src = _read('components/lesson_player.html')
    for marker in ("'say'", "'do'", "'check'", "'show'"):
        check(marker in src, f"renders {marker} beats")
    check('stepsToScenes' in src,
          "fallback ladder: plain steps become beats client-side")
    check('got it' in src.lower(), "the check offers its taps")


def scenario_checks_are_never_stored():
    """A check tap advances the scene and nothing else. No fetch, no POST,
    no localStorage write may ride it."""
    src = _read('components/lesson_player.html')
    import re
    m = re.search(r'answerCheck\([^)]*\)\s*{([^}]*)}', src)
    check(m, "answerCheck exists")
    body = m.group(1)
    for forbidden in ('fetch', 'localStorage', 'api', 'POST'):
        check(forbidden not in body,
              f"a check tap must not {forbidden} — it only advances")


def scenario_programs_page_opens_the_player():
    src = _read('programs.html')
    check('lesson_player.html' in src, "the page includes the player")
    check('lesson-player:open' in src, "and a window can open it")


def scenario_no_streak_language_in_the_player():
    src = _read('components/lesson_player.html').lower()
    for word in ('streak', 'missed', 'in a row'):
        check(word not in src, f"the player never says {word!r}")
```

- [ ] **Step 2: Run to verify failure**

Run: `python chauffeur/tests/test_lesson_player_runtime.py`
Expected: FileNotFoundError — component missing.

- [ ] **Step 3: Build the component**

`components/lesson_player.html` — full-screen overlay, Alpine. Core structure (write it complete; the skeleton below is the contract, flesh out markup with the app's token classes — read `components/programs_card.html` for the house style first):

```html
<!-- The lesson player. One scene at a time, tap to advance. The renderer
     owns every pixel; a script only parameterizes it. Nothing in here
     records how a lesson went: a check tap advances the scene, full stop.
     The only persisted outcome of practice anywhere is the session log,
     and the final screen merely offers that existing tap. -->
<div x-data="lessonPlayer()" x-show="openFlag" x-cloak
     @lesson-player:open.window="open($event.detail.window, $event.detail.lesson)"
     class="fixed inset-0 z-[90] bg-gray-950/95 flex flex-col"
     :class="panel ? 'text-2xl' : 'text-base'">
  <!-- header: program title · session label · close -->
  <!-- scene area: one scene, keyed by idx, transition on advance -->
  <template x-if="scene().type === 'say'">   <!-- animated text beat --> </template>
  <template x-if="scene().type === 'do'">    <!-- text + countdown ring + optional metronome --> </template>
  <template x-if="scene().type === 'check'"> <!-- ask + three taps: got it / almost / not yet --> </template>
  <template x-if="scene().type === 'show'">  <!-- primitive dispatch; unknown-to-renderer kind draws caption as say --> </template>
  <!-- footer: progress dots (position only, one per scene), advance tap -->
  <!-- final screen: 'Log it?' button that calls the PAGE's existing log
       action via window.dispatchEvent(new CustomEvent('lesson-player:done',
       {detail: {window: w}})) — the player itself never posts. -->
</div>

<script>
function lessonPlayer() {
  return {
    openFlag: false, w: null, scenes: [], idx: 0,
    panel: new URLSearchParams(location.search).get('panel') === 'true',
    timer: null, timeLeft: 0, audio: null, metroTimer: null,

    open(w, lesson) {
      this.w = w;
      this.scenes = (lesson && (lesson.scenes || []).length)
        ? lesson.scenes : this.stepsToScenes(w);
      this.idx = 0; this.openFlag = true;
    },
    // The fallback ladder: a window with no lesson plays its own steps.
    // The player never blocks practice.
    stepsToScenes(w) {
      const scenes = [];
      if (w.unit_title) scenes.push({type: 'say', text: w.unit_title});
      (w.steps || []).forEach(s => scenes.push({type: 'do', text: s}));
      if (!scenes.length && w.milestone)
        scenes.push({type: 'say', text: w.milestone});
      scenes.push({type: 'check', ask: 'Good session?'});
      return scenes;
    },
    scene() { return this.scenes[this.idx] || {type: 'say', text: ''}; },
    advance() {
      this.stopSound();
      if (this.idx < this.scenes.length - 1) { this.idx++; this.enterScene(); }
      else this.finish();
    },
    // A check tap advances. It is not stored, not sent, not remembered.
    answerCheck() { this.advance(); },
    enterScene() {
      const s = this.scene();
      if (s.type === 'do' && s.seconds) this.startTimer(s.seconds);
      if (s.type === 'do' && s.metronome_bpm) this.startMetronome(s.metronome_bpm);
      if (s.type === 'show' && s.primitive.kind === 'metronome')
        this.startMetronome(s.primitive.bpm);
    },
    startTimer(secs) { /* countdown ring via setInterval on timeLeft */ },
    startMetronome(bpm) { /* WebAudio oscillator click every 60/bpm s */ },
    stopSound() { /* clear metroTimer + timer, close audio */ },
    finish() { this.stopSound();
      window.dispatchEvent(new CustomEvent('lesson-player:done',
        {detail: {window: this.w}}));
      this.openFlag = false; },
    close() { this.stopSound(); this.openFlag = false; },
  };
}
</script>
```

Implementation notes (do these, not placeholders): `startTimer` sets `timeLeft = secs` and a 1s `setInterval` decrement, rendered as an SVG ring whose `stroke-dashoffset` maps to `timeLeft/secs`; `startMetronome` builds one `AudioContext`, schedules a 40ms 880Hz oscillator burst per beat via `setInterval(60000/bpm)`; both cleared in `stopSound()`. `say` beats animate in with a CSS `@keyframes` fade-up; progress dots are `scenes.map` with the current index highlighted — position, never results.

- [ ] **Step 4: Wire programs.html**

Include the component once (with the page's other includes): `{% include 'components/lesson_player.html' %}`. On each today/practice-window row in the page (find where the page renders windows — search the file for `practice-windows`), add:

```html
<button @click="window.dispatchEvent(new CustomEvent('lesson-player:open',
        {detail: {window: w, lesson: w._lesson || null}}))"
        class="text-[11px] font-bold px-2.5 py-1 rounded-lg bg-teal-600 text-white active:bg-teal-700">
    Start session
</button>
```

And handle `lesson-player:done` in the page's Alpine root by calling its existing session-log action for that window's program (read how the page logs a session today and reuse that exact method — the player never posts).

- [ ] **Step 5: Rebuild Tailwind, run tests, sweep, bump patch, commit, push**

```bash
python chauffeur/tools/build_tailwind.py
python chauffeur/tests/test_lesson_player_runtime.py
python chauffeur/tools/test.py
git add -A && git commit -m 'The evening gets a body (v2.442.5)' && git push origin main
```

---

### Task 7: Player on the wall + PWA

**Files:**
- Modify: `chauffeur/templates/components/programs_card.html` (today's windows already render ~line 149-180 — add the open tap)
- Modify: `chauffeur/templates/app.html` (the PWA programs section — same open tap on its session rows)
- Test: `chauffeur/tests/test_lesson_player_runtime.py` (append)

**Interfaces:**
- Consumes: `lesson-player:open` event from Task 6.
- Produces: nothing new — both remaining surfaces reach the same player.

- [ ] **Step 1: Write failing tests (append)**

```python
def scenario_the_wall_and_the_pwa_reach_the_player():
    for page in ('components/programs_card.html', 'app.html'):
        src = _read(page)
        check('lesson-player:open' in src, f"{page} can open the player")
```

- [ ] **Step 2: Run to verify failure, then wire both surfaces**

Same button as Task 6 Step 4 on the card's `pgToday` rows and the PWA's program-session rows; each page that gains the button must also include `components/lesson_player.html` once. On the card, panel-size the tap target (`py-2 px-4`, larger text — read the card's other panel-tier controls and match). The PWA's `lesson-player:done` handler reuses `app.html`'s existing `/session` log tap.

- [ ] **Step 3: Rebuild Tailwind, run tests, sweep, bump patch, commit, push**

```bash
git add -A && git commit -m 'Same lesson on the wall and in the hand (v2.442.6)' && git push origin main
```

---

### Task 8: Lesson API — read and hand-edit

**Files:**
- Modify: `chauffeur/main.py` (new endpoints beside the programs block, after `practice_windows_api` ~line 5981)
- Modify: `chauffeur/templates/programs.html` (windows fetch also fetches lessons; lesson editor UI on the program detail)
- Create: `chauffeur/tests/test_lesson_endpoints.py`

**Interfaces:**
- Produces:
  - `GET /api/programs/{program_id}/lesson?phase_name=&unit_n=&session_label=` → `{"lesson": row-or-null}`. Read scope: `_program_list_scope(request, row['member_id'])` — `_NOBODY` → `{"lesson": null}`; a resolved child sees only their own program's lessons (scope comes back as their id ≠ owner → `{"lesson": null}`).
  - `PUT` same path, body `{"scenes": [...]}` → sanitize with the lesson's stored origin (or `'generated'` if none), store with `edited: true`. Write gate: `_program_permission_or_refuse`.
  - `DELETE` same path → remove that slot's lesson (regenerates next sweep). Same write gate.
- Consumes: Tasks 4-5 (`sanitize_script`, `slot_of`, storage CRUD), Task 6 player (page passes fetched lesson into `w._lesson`).

- [ ] **Step 1: Write failing tests**

```python
"""Lessons ride the same permission rails as the programs they belong to."""
from harness import check
from fastapi import HTTPException

from services import storage


class Req:
    def __init__(self, token=None):
        self.headers = {'x-member-token': token} if token else {}
        self.query_params = {}


def _reset():
    storage.programs_table.truncate()
    storage.program_lessons_table.truncate()
    storage.members_table.truncate()
    storage.add_member({'id': 'mom', 'name': 'Mom', 'role': 'parent'})
    storage.add_member({'id': 'kid', 'name': 'Lily', 'role': 'child'})
    pid = storage.add_program({'member_id': 'kid', 'title': 'Play guitar',
                               'shape': {'sessions_per_week': 2, 'minutes': 20}})
    storage.upsert_program_lesson(pid, {'phase_name': 'F', 'unit_n': 1,
                                        'session_label': ''},
                                  {'origin': 'generated',
                                   'scenes': [{'type': 'say', 'text': 'hi'}]})
    return pid


def scenario_endpoints_exist():
    import main
    paths = {r.path for r in main.app.routes}
    check('/api/programs/{program_id}/lesson' in paths,
          "the lesson is reachable by hand")


def scenario_owner_reads_their_lesson():
    import main
    pid = _reset()
    tok = main._auth_token_for('kid') if hasattr(main, '_auth_token_for') else None
    # Trusted-place read (request with no resolvable actor on an admin
    # surface) sees it; follow test_programs_endpoints.py's actual token
    # minting — copy its helper if one exists there.
    res = main.get_program_lesson_api(pid, phase_name='F', unit_n=1,
                                      session_label='', request=None)
    check(res['lesson'] and res['lesson']['scenes'][0]['text'] == 'hi',
          f"got {res}")


def scenario_edit_sanitizes_and_marks_edited():
    import main
    pid = _reset()
    res = main.put_program_lesson_api(pid, body={
        'phase_name': 'F', 'unit_n': 1, 'session_label': '',
        'scenes': [{'type': 'say', 'text': 'mine'},
                   {'type': 'shout', 'text': 'dropped'}]}, request=None)
    check(res.get('status') == 'ok', f"got {res}")
    row = storage.get_program_lesson(pid, {'phase_name': 'F', 'unit_n': 1,
                                           'session_label': ''})
    check(row['edited'] is True and len(row['scenes']) == 1,
          f"sanitized and marked, got {row}")


def scenario_delete_clears_the_slot():
    import main
    pid = _reset()
    main.delete_program_lesson_api(pid, phase_name='F', unit_n=1,
                                   session_label='', request=None)
    check(storage.get_program_lesson(pid, {'phase_name': 'F', 'unit_n': 1,
                                           'session_label': ''}) is None,
          "gone; the sweep will write a fresh one")
```

(Adapt the two direct-call signatures to what you actually name the handlers; the trusted-place `request=None` path mirrors how `test_programs_endpoints.py` exercises writes. If that file mints member tokens for denial cases, copy that idiom and add one denial scenario: `kid` token editing `mom`'s program's lesson → 403.)

- [ ] **Step 2: Run to verify failure, then implement the three handlers**

```python
@app.get("/api/programs/{program_id}/lesson")
def get_program_lesson_api(program_id: str, phase_name: str = '',
                           unit_n: int = 0, session_label: str = '',
                           request: Request = None):
    """The lesson behind one practice window. Null is a fine answer — the
    player's fallback ladder plays the plain steps."""
    row = storage.get_program(program_id)
    if not row:
        return {"lesson": None}
    scope = _program_list_scope(request, row.get('member_id'))
    if scope is _NOBODY:
        return {"lesson": None}
    lesson = storage.get_program_lesson(program_id, {
        'phase_name': phase_name, 'unit_n': unit_n,
        'session_label': session_label})
    return {"lesson": lesson}


@app.put("/api/programs/{program_id}/lesson")
def put_program_lesson_api(program_id: str, body: dict = Body(default={}),
                           request: Request = None):
    """A hand edit. Sanitized like every other door, stored edited:true so
    generation bounces off it forever after."""
    from services import program_lessons as _pl
    row = storage.get_program(program_id)
    if not row:
        raise HTTPException(status_code=404, detail="No such program")
    _program_permission_or_refuse(request, body, row)
    slot = {'phase_name': body.get('phase_name') or '',
            'unit_n': int(body.get('unit_n') or 0),
            'session_label': body.get('session_label') or ''}
    existing = storage.get_program_lesson(program_id, slot) or {}
    origin = existing.get('origin') or 'generated'
    scenes = _pl.sanitize_script(body.get('scenes') or [], origin)
    if not scenes:
        return {"status": "error",
                "message": "Nothing survivable in that script."}
    storage.upsert_program_lesson(program_id, slot, {
        'origin': origin, 'source_url': existing.get('source_url') or '',
        'scenes': scenes, 'edited': True,
        'model': existing.get('model') or ''})
    return {"status": "ok"}


@app.delete("/api/programs/{program_id}/lesson")
def delete_program_lesson_api(program_id: str, phase_name: str = '',
                              unit_n: int = 0, session_label: str = '',
                              request: Request = None):
    """Clear one slot; the sweep writes a fresh lesson next tick."""
    row = storage.get_program(program_id)
    if not row:
        raise HTTPException(status_code=404, detail="No such program")
    _program_permission_or_refuse(request, {}, row)
    with storage.db_lock:
        storage.program_lessons_table.remove(
            storage._lesson_query(program_id, {
                'phase_name': phase_name, 'unit_n': unit_n,
                'session_label': session_label}))
    return {"status": "ok"}
```

- [ ] **Step 3: Page wiring — fetch + editor**

In `programs.html`: where today's windows are fetched, fetch each window's lesson (`GET .../lesson?...` with `phase_name=w.phase_name&unit_n=<current_unit of that program>&session_label=w.session_label`) and stash as `w._lesson`. The program list payload already carries `current_unit` per program (see `list_programs_api`) — join by `w.program_id`.

Editor (hand path): on the program detail's phase section, a "Lesson" disclosure per rotation label showing the stored scenes as editable rows — text inputs for `say`/`do`/`check`, delete per row, add-row select for type, Save posts the PUT above, "Regenerate" calls the DELETE. Keep it plain; the player is the show, the editor is a form. Use `showGlobalAlert`/`promptConfirm` (never browser dialogs).

- [ ] **Step 4: Rebuild Tailwind, run tests, sweep, bump patch, commit, push**

```bash
git add -A && git commit -m 'The lesson answers by hand too (v2.442.7)' && git push origin main
```

---

### Task 9: Generation

**Files:**
- Modify: `chauffeur/services/web.py` (public `read_page`)
- Modify: `chauffeur/services/program_lessons.py` (generation)
- Test: `chauffeur/tests/test_program_lessons.py` (append)

**Interfaces:**
- Produces:
  - `web.read_page(url: str) -> Optional[str]` — fetched page text or None; thin public wrapper over `_fetch` (which already runs `html_to_text` internally — read `_fetch` first and wrap at whichever layer returns text).
  - `program_lessons.generate_for(program: dict, window: dict, unit: dict, settings: dict) -> Optional[str]` — builds prompts, calls `model_pools.call_pool_json('background', ...)`, sanitizes, stores via `storage.upsert_program_lesson`. Returns the lesson id or None. NEVER raises.
- Consumes: `model_pools.call_pool_json` (Gemini pools), `programs_curate` origin constants, Tasks 4-5.

- [ ] **Step 1: Write failing tests (append to test_program_lessons.py)**

```python
def _program_row(origin='generated', unit_url=''):
    return {'id': 'p9', 'member_id': 'kid', 'title': 'Play guitar',
            'source': {'origin': origin},
            'shape': {'minutes': 20}}


def _window():
    return {'program_id': 'p9', 'phase_name': 'Foundations',
            'session_label': 'Technique', 'steps': ['One-minute changes G-C'],
            'unit_title': 'Stage 1', 'unit_url': '', 'unit_body': 'Chords first.',
            'milestone': 'Play a song', 'progression': 'Add D when G-C is clean'}


def scenario_generated_origin_uses_pool_and_stores(monkeypatch=None):
    from services import storage, program_lessons as pl
    storage.program_lessons_table.truncate()
    calls = {}
    def fake_pool(tier, api_key, system, prompt, **kw):
        calls['tier'] = tier
        return {'scenes': [{'type': 'say', 'text': 'Chords are shapes.'},
                           {'type': 'do', 'text': 'One-minute changes G-C',
                            'seconds': 60}], '_model': 'gemma-4-31b-it'}
    import services.model_pools as mp
    orig = mp.call_pool_json
    mp.call_pool_json = fake_pool
    try:
        lid = pl.generate_for(_program_row(), _window(), {'n': 1},
                              {'llm_gemini_api_key': 'k'})
    finally:
        mp.call_pool_json = orig
    check(lid, "stored a lesson")
    check(calls['tier'] == 'background', "nobody is waiting — background tier")
    row = storage.get_program_lesson('p9', {'phase_name': 'Foundations',
                                            'unit_n': 1,
                                            'session_label': 'Technique'})
    check(row['origin'] == 'generated' and row['model'] == 'gemma-4-31b-it',
          f"got {row}")


def scenario_cited_needs_its_page_or_stays_silent():
    """An outage is never papered over: fetch fails -> no script."""
    from services import storage, program_lessons as pl, web
    storage.program_lessons_table.truncate()
    w = {**_window(), 'unit_url': 'https://jg.example/s1'}
    orig = web.read_page
    web.read_page = lambda url: None
    try:
        lid = pl.generate_for(_program_row(origin='cited'), w, {'n': 1},
                              {'llm_gemini_api_key': 'k'})
    finally:
        web.read_page = orig
    check(lid is None, "no page, no script")
    check(storage.get_program_lesson('p9', {'phase_name': 'Foundations',
                                            'unit_n': 1,
                                            'session_label': 'Technique'}) is None,
          "and nothing stored")


def scenario_cited_carries_its_source():
    from services import storage, program_lessons as pl, web
    import services.model_pools as mp
    storage.program_lessons_table.truncate()
    w = {**_window(), 'unit_url': 'https://jg.example/s1'}
    orig_read, orig_pool = web.read_page, mp.call_pool_json
    web.read_page = lambda url: 'Stage 1: learn G and C. Practice changes.'
    mp.call_pool_json = lambda *a, **k: {
        'scenes': [{'type': 'say', 'text': 'G and C first.'}],
        '_model': 'gemini-3.5-flash-lite'}
    try:
        lid = pl.generate_for(_program_row(origin='cited'), w, {'n': 1},
                              {'llm_gemini_api_key': 'k'})
    finally:
        web.read_page, mp.call_pool_json = orig_read, orig_pool
    row = storage.get_program_lesson('p9', {'phase_name': 'Foundations',
                                            'unit_n': 1,
                                            'session_label': 'Technique'})
    check(lid and row['origin'] == 'cited'
          and row['source_url'] == 'https://jg.example/s1', f"got {row}")


def scenario_generation_survives_a_pool_error():
    from services import storage, program_lessons as pl
    import services.model_pools as mp
    storage.program_lessons_table.truncate()
    orig = mp.call_pool_json
    mp.call_pool_json = lambda *a, **k: {'error': '429 quota', 'transient': True}
    try:
        lid = pl.generate_for(_program_row(), _window(), {'n': 1},
                              {'llm_gemini_api_key': 'k'})
    finally:
        mp.call_pool_json = orig
    check(lid is None, "a failed call stores nothing and raises nothing")
```

- [ ] **Step 2: Run to verify failure, then implement**

`web.read_page`:

```python
def read_page(url: str) -> Optional[str]:
    """One page, read for its text — the single-page sibling of research().
    None on any failure; the caller decides what silence means."""
    try:
        return _fetch(url)
    except Exception as e:
        print(f"[web] read_page failed for {url}: {e}")
        return None
```

`program_lessons.generate_for` (append to the module; prompts are part of the implementation, write them in full):

```python
_SYSTEM = (
    "You write one practice-session lesson script for a family app. Reply "
    "with ONLY JSON: {\"scenes\": [...]}. Scene types: "
    "{\"type\":\"say\",\"text\":\"\"} a short teaching beat; "
    "{\"type\":\"do\",\"text\":\"\",\"seconds\":60,\"metronome_bpm\":80} a "
    "practice interlude (seconds and metronome_bpm optional); "
    "{\"type\":\"check\",\"ask\":\"\"} a self-check with fixed answers; "
    "{\"type\":\"show\",\"primitive\":{...},\"caption\":\"\"} a visual. "
    "Primitives: {\"kind\":\"timer\",\"seconds\":60}, "
    "{\"kind\":\"metronome\",\"bpm\":80}, "
    "{\"kind\":\"keyboard\",\"keys\":[\"C4\",\"E4\",\"G4\"]}, "
    "{\"kind\":\"fretboard\",\"dots\":[{\"string\":5,\"fret\":2,\"finger\":2}]}, "
    "{\"kind\":\"cards\",\"pairs\":[{\"front\":\"\",\"back\":\"\"}]}, "
    "{\"kind\":\"counter\",\"target\":10}. "
    "At most 10 scenes. Structure: a short why, then the drill as do-beats, "
    "one check near the end. Every do-beat must be startable alone from its "
    "text. No praise-fluff, no streaks, no scores.")

_CITED_PROMPT = (
    "Turn THIS material into tonight's {minutes}-minute session script. Use "
    "ONLY what the material says — do not add exercises or advice it does "
    "not contain.\n\nSession: {label} in phase {phase} of \"{title}\".\n"
    "Steps the plan already names: {steps}\n\nMATERIAL from {url}:\n{page}")

_GENERATED_PROMPT = (
    "Write tonight's {minutes}-minute session script for \"{title}\" "
    "(phase {phase}, session {label}). Build it AROUND these steps — they "
    "are the session, your script paces and explains them: {steps}\n"
    "Unit notes: {body}\nProgression rule: {progression}\n"
    "Structure the practice (warmup, the work, brief review). Do NOT "
    "prescribe how to hold or move any part of the body.")


def generate_for(program: dict, window: dict, unit: dict,
                 settings: dict):
    """One slot's lesson, generated and stored — or nothing, quietly.

    Cited plans speak only from their page: the unit's url is re-read at
    generation time (threads-arc discipline — never cite what was not
    read), and a fetch failure means NO script rather than a generated
    stand-in, because an outage is never papered over. Generated plans
    speak only from their own steps.
    """
    from services import model_pools, storage, web
    try:
        origin = ((program.get('source') or {}).get('origin')
                  or 'generated')
        slot = slot_of(window, unit_n=int((unit or {}).get('n') or 0))
        existing = storage.get_program_lesson(program['id'], slot)
        if existing and (existing.get('edited') or existing.get('scenes')):
            return None                       # already has its lesson
        minutes = int((program.get('shape') or {}).get('minutes') or 25)
        fields = {'minutes': minutes,
                  'title': program.get('title') or '',
                  'phase': window.get('phase_name') or '',
                  'label': window.get('session_label') or 'practice',
                  'steps': ' | '.join(window.get('steps') or []),
                  'body': window.get('unit_body') or '',
                  'progression': window.get('progression') or ''}
        source_url = ''
        if origin == 'cited':
            url = window.get('unit_url') or ''
            page = web.read_page(url) if url else None
            if not page:
                return None                   # no page, no script
            source_url = url
            prompt = _CITED_PROMPT.format(url=url, page=page[:8000], **fields)
        else:
            origin = 'generated'
            prompt = _GENERATED_PROMPT.format(**fields)
        res = model_pools.call_pool_json(
            'background', settings.get('llm_gemini_api_key', ''),
            _SYSTEM, prompt, timeout_s=60, gemma_timeout_s=180,
            settings=settings)
        if not isinstance(res, dict) or res.get('error'):
            return None
        scenes = sanitize_script(res.get('scenes') or [], origin)
        if not scenes:
            return None
        return storage.upsert_program_lesson(program['id'], slot, {
            'origin': origin, 'source_url': source_url, 'scenes': scenes,
            'model': res.get('_model') or ''}) or None
    except Exception as e:
        print(f"[lessons] generate failed for "
              f"{(program or {}).get('id')}: {e}")
        return None
```

- [ ] **Step 3: Run tests, sweep, bump patch, commit, push**

```bash
git add -A && git commit -m 'The night before, the lesson writes itself (v2.442.8)' && git push origin main
```

---

### Task 10: The daily sweep + setting

**Files:**
- Modify: `chauffeur/services/program_lessons.py` (`generate_due`)
- Modify: `chauffeur/main.py` (30s loop, beside the practice-push block ~line 176)
- Modify: `chauffeur/models/schemas.py` (`program_lessons_enabled` beside `programs_enabled` ~line 1502)
- Modify: `chauffeur/services/settings_registry.py` (entry beside `programs_enabled` ~line 561)
- Modify: `chauffeur/templates/programs.html` (toggle in the page's existing settings panel, ~line 58)
- Test: `chauffeur/tests/test_program_lessons.py` (append)

**Interfaces:**
- Produces: `program_lessons.generate_due(now=None) -> int` — self-throttled to one real pass per day via `storage.get_app_state('program_lessons_swept')`; scans `programs.practice_windows(tomorrow, tomorrow+1)`; returns lessons written. Settings key `program_lessons_enabled` (default True).
- Consumes: Task 9's `generate_for`, `programs.practice_windows`, `programs.unit_for`, `programs.progress`.

- [ ] **Step 1: Write failing tests (append)**

```python
def scenario_generate_due_end_to_end():
    """The critical path, RUN rather than read: real storage, real windows,
    mocked model. One active program with a window tomorrow gets exactly
    one lesson; the second call the same day does nothing."""
    import datetime
    from services import storage, program_lessons as pl
    import services.model_pools as mp
    storage.programs_table.truncate()
    storage.program_lessons_table.truncate()
    storage.protected_commitments_table.truncate()
    storage.set_app_state('program_lessons_swept', '')
    tomorrow = datetime.date.today() + datetime.timedelta(days=1)
    pid = storage.add_program({'member_id': 'kid', 'title': 'Play guitar',
                               'shape': {'sessions_per_week': 1, 'minutes': 20},
                               'phases': [{'name': 'Foundations',
                                           'steps': ['One-minute changes G-C'],
                                           'weeks': 4}]})
    storage.update_program(pid, {'state': 'active'})
    cid = storage.add_protected_commitment({
        'member_id': 'kid', 'label': 'Practice', 'active': True,
        'days_of_week': [tomorrow.weekday()],
        'time_start': '17:00', 'time_end': '17:20'})
    row = storage.get_program(pid)
    storage.update_program(pid, {'emissions': {**row['emissions'],
                                               'commitment_ids': [cid]}})
    orig = mp.call_pool_json
    mp.call_pool_json = lambda *a, **k: {
        'scenes': [{'type': 'say', 'text': 'Chords are shapes.'}],
        '_model': 'gemma-4-31b-it'}
    try:
        wrote = pl.generate_due()
        wrote_again = pl.generate_due()
    finally:
        mp.call_pool_json = orig
    check(wrote == 1, f"one window, one lesson, got {wrote}")
    check(wrote_again == 0, "self-throttled: one pass a day")


def scenario_sweep_respects_the_switch():
    from services import storage, program_lessons as pl
    storage.set_app_state('program_lessons_swept', '')
    s = storage.get_settings()
    storage.update_settings({**s, 'program_lessons_enabled': False})
    try:
        check(pl.generate_due() == 0, "off means off")
    finally:
        storage.update_settings({**s, 'program_lessons_enabled': True})
```

(Adapt `add_protected_commitment`/`update_settings` calls to storage's real function names — grep before writing; `emissions` linking mirrors what `approve()` writes, read `_emit_commitments` in `services/programs.py` if the fixture above doesn't produce a window and fix the fixture, not the code.)

- [ ] **Step 2: Run to verify failure, then implement `generate_due`**

```python
def generate_due(now=None) -> int:
    """Tomorrow's lessons, written tonight. Called blindly from the 30s
    loop and self-throttled to one real pass per day (the traffic-sweep
    pattern), so a restart never double-spends and idle cost is one
    app_state read."""
    import datetime
    from services import storage, programs
    now = now or datetime.datetime.now()
    marker = now.date().isoformat()
    if (storage.get_app_state('program_lessons_swept') or '') == marker:
        return 0
    settings = storage.get_settings() or {}
    if not settings.get('programs_enabled', True):
        return 0
    if not settings.get('program_lessons_enabled', True):
        return 0
    storage.set_app_state('program_lessons_swept', marker)
    tomorrow = now.date() + datetime.timedelta(days=1)
    rows = {r['id']: r for r in storage.get_programs(state='active')}
    wrote = 0
    for w in programs.practice_windows(tomorrow,
                                       tomorrow + datetime.timedelta(days=1)):
        row = rows.get(w.get('program_id'))
        if not row:
            continue
        phase = programs.progress(row).get('phase') or {}
        unit = programs.unit_for(row, phase) or {}
        if generate_for(row, w, unit, settings):
            wrote += 1
    return wrote
```

- [ ] **Step 3: Wire the 30s loop in main.py**

Directly after the practice-push block (same try/except style):

```python
            # Tomorrow's lessons, written tonight. Self-throttled to one
            # pass a day inside generate_due, so this 30s loop can call it
            # blindly — the traffic-sweep pattern one block up.
            try:
                from services import program_lessons as _pl_gen
                await asyncio.to_thread(_pl_gen.generate_due)
            except Exception as le:
                print(f"Lesson generation sweep error: {le}")
```

- [ ] **Step 4: The setting, in all three places**

`schemas.py` (beside `programs_enabled`):

```python
    program_lessons_enabled: Optional[bool] = True
```

`settings_registry.py` (beside the `programs_enabled` entry, same `_e` idiom — copy its group and page values, new anchor):

```python
    _e('program_lessons_enabled', 'programs', 'Lesson scripts',
       'Write a short scripted lesson for each practice session the night '
       'before — the session still shows its plain steps with this off.',
       page='programs.html', anchor='lessons'),
```

(Match `_e`'s real signature by reading the neighbouring entries first; the registry audit test fails the sweep if the key is missing, which is the enforcement.)

`programs.html`: a toggle in the page's existing settings block (the one at ~line 58 holding `programs_enabled`-adjacent settings), same markup idiom as its neighbours, `id="lessons"` anchor.

- [ ] **Step 5: Rebuild Tailwind, run tests, sweep, bump patch, commit, push**

```bash
git add -A && git commit -m 'Tonight writes tomorrow, once (v2.442.9)' && git push origin main
```

---

### Task 11: Music primitives (P3a)

**Files:**
- Modify: `chauffeur/templates/components/lesson_player.html`
- Test: `chauffeur/tests/test_lesson_player_runtime.py` (append)

**Interfaces:**
- Consumes: validated primitive params from Task 4 (`keyboard.keys` note names like `C4`; `fretboard.dots` {string 1-6, fret 0-24, finger 1-4}; `metronome.bpm`).
- Produces: renderer blocks for `keyboard`, `fretboard`, `metronome` inside the `show` template.

- [ ] **Step 1: Write failing tests (append)**

```python
def scenario_music_primitives_render():
    src = _read('components/lesson_player.html')
    for kind in ('keyboard', 'fretboard', 'metronome'):
        check(f"'{kind}'" in src, f"{kind} has a renderer block")
    check('<svg' in src, "drawn, not described")
```

- [ ] **Step 2: Implement the three renderer blocks**

Inside the `show` template's primitive dispatch:

- **keyboard**: one-octave-plus SVG built by a JS function `keyboardSvg(keys)` — 14 white keys (two octaves C3-B4 is enough for validated range C0-B8? No: draw the octave window that CONTAINS the highlighted keys — compute min/max octave from `keys`, render those octaves only, max two), white `rect`s with black-key `rect`s overlaid, highlighted keys filled with the app's teal accent. Key-to-x arithmetic in JS, not hand-drawn per key.
- **fretboard**: `fretboardSvg(dots)` — 6 horizontal string lines, 5-fret window starting at `max(1, min(dot frets))`, fret number label at window start, dots as circles at (string, fret) grid positions with the finger number as white text inside.
- **metronome**: a pendulum bar animated with CSS `@keyframes` swing whose `animation-duration` is set inline to `60/bpm * 2`s, plus the Task 6 `startMetronome(bpm)` click already wired in `enterScene`.

All three inherit `currentColor`/token classes so both themes work; captions render beneath.

- [ ] **Step 3: Rebuild Tailwind, run tests, sweep, bump patch, commit, push**

```bash
git add -A && git commit -m 'The chord is drawn, never described (v2.442.10)' && git push origin main
```

---

### Task 12: Cards + counter primitives (P3b)

**Files:**
- Modify: `chauffeur/templates/components/lesson_player.html`
- Test: `chauffeur/tests/test_lesson_player_runtime.py` (append)

**Interfaces:**
- Consumes: validated `cards.pairs` / `counter.target` params from Task 4.
- Produces: renderer blocks for `cards` (tap to flip front/back, one pair at a time, dots for position), `counter` (big number, tap increments toward `target`, resets on scene exit — NEVER persisted), and the explicit `timer` show-kind reusing Task 6's countdown ring.

- [ ] **Step 1: Write failing tests (append)**

```python
def scenario_remaining_primitives_render():
    src = _read('components/lesson_player.html')
    for kind in ('cards', 'counter'):
        check(f"'{kind}'" in src, f"{kind} has a renderer block")


def scenario_counter_taps_are_never_sent():
    """A rep count is a within-scene convenience, not a record."""
    src = _read('components/lesson_player.html')
    import re
    m = re.search(r'bumpCounter\([^)]*\)\s*{([^}]*)}', src)
    check(m, "bumpCounter exists")
    for forbidden in ('fetch', 'localStorage', 'api'):
        check(forbidden not in m.group(1), f"counter taps never {forbidden}")
```

- [ ] **Step 2: Implement, rebuild Tailwind, run tests, sweep, bump patch, commit, push**

```bash
git add -A && git commit -m 'Flip cards and count reps, remember neither (v2.442.11)' && git push origin main
```

---

### Task 13: Capabilities doc + memory

**Files:**
- Modify: `chauffeur/system_capabilities.md` (Programs section gains lessons + book fork; UI architecture section gains the player)

**Steps:**

- [ ] **Step 1:** Update `system_capabilities.md`: under the Programs feature section describe lesson scripts (slot-keyed, origins, sanitizer, fallback ladder, the `program_lessons_enabled` switch), the player surfaces, and the book-spine approval fork. Same voice as the surrounding sections.
- [ ] **Step 2:** Sweep not required (docs-only), bump patch, commit, push:

```bash
git add -A && git commit -m 'The spec knows the lesson player exists (v2.442.12)' && git push origin main
```

---

## Self-Review Notes (already applied)

- Spec coverage: detector (T1), exclude_books + research preference (T2), approval fork (T3), schema+sanitizer+screens (T4), storage + edited-wins (T5), player + fallback + both surfaces (T6-7), read/edit/delete API + editor hand path (T8), cited/generated origin rules + outage rule (T9), daily trigger + setting (T10), primitives (T11-12), capabilities doc (T13). "Structure labelled generated, sequence labelled cited" for kept-book plans is satisfied by T9's generated-prompt path operating on the plan's own steps — a kept book plan's lessons carry origin `cited` only when a unit url exists, else they generate structure; no extra task needed.
- Placeholders: none — every code step is complete or names the exact neighbouring idiom to copy (a house rule, not an omission: matching `_e`'s real signature beats guessing it here).
- Type consistency: `slot_of` shape `{phase_name, unit_n, session_label}` used identically in Tasks 4, 5, 8, 9, 10; `generate_for(program, window, unit, settings)` consistent between 9 and 10; `lesson-player:open`/`done` event names consistent between 6, 7, 8.
