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


def _to_int(value):
    """int() that never raises. A plain try/except (TypeError, ValueError)
    still lets one shape through: int(float('inf')) raises OverflowError
    instead, and JSON hands this door exactly that shape for free -- the
    bare token `Infinity` parses under json.loads, and so does any numeral
    past a double's range (`1e400`). One helper, six call sites, so the fix
    lives once rather than once per validator that forgot it."""
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


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
        string, fret, finger = (_to_int(d.get('string')), _to_int(d.get('fret')),
                                 _to_int(d.get('finger')))
        if string is None or fret is None or finger is None:
            return False
        if not (1 <= string <= 6 and 0 <= fret <= 24 and 1 <= finger <= 4):
            return False
    return True


def _valid_metronome(p):
    bpm = _to_int(p.get('bpm'))
    return bpm is not None and 30 <= bpm <= 240


def _valid_timer(p):
    secs = _to_int(p.get('seconds'))
    return secs is not None and 5 <= secs <= MAX_DO_SECONDS


def _valid_cards(p):
    pairs = p.get('pairs')
    return (isinstance(pairs, list) and 0 < len(pairs) <= 12
            and all(isinstance(x, dict) and str(x.get('front') or '').strip()
                    and str(x.get('back') or '').strip() for x in pairs))


def _valid_counter(p):
    target = _to_int(p.get('target'))
    return target is not None and 1 <= target <= 500


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
    on every origin -- both halves of curate's own screen, phrases matched
    as substrings (`BODY_PHRASES`) and single words matched on a boundary
    (`_BODY_WORD_RE`), because screening only the phrases let "this drill
    burns calories" straight through. Physical prescriptions die on
    generated only."""
    from services.programs_curate import BODY_PHRASES, _BODY_WORD_RE
    low = text.lower()
    if any(p in low for p in BODY_PHRASES) or _BODY_WORD_RE.search(low):
        return True
    return origin == 'generated' and bool(_PHYSICAL_RE.search(text))


def sanitize_script(scenes: list, origin: str) -> list:
    """Every script through one door. Clamps, whitelists, screens; returns
    what survives, which may be nothing — and nothing is a fine answer,
    because the player's fallback ladder plays the plain steps."""
    out = []
    # `scenes or []` only coalesces FALSY junk (None, 0, ''); a truthy
    # scalar -- an int, a float, a bare True -- is not a list and would
    # otherwise reach the for and raise. Anything that is not actually a
    # list of scenes becomes no scenes, the same way a malformed scene
    # inside the list becomes no scene below.
    for raw in (scenes if isinstance(scenes, list) else []):
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
            secs = _to_int(raw.get('seconds'))
            if secs is not None:
                scene['seconds'] = max(5, min(MAX_DO_SECONDS, secs))
            bpm = _to_int(raw.get('metronome_bpm'))
            if bpm is not None:
                scene['metronome_bpm'] = max(30, min(240, bpm))
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


# --- generation ---------------------------------------------------------
# A script has exactly one source, decided by the plan's own origin. A
# cited plan may only speak from the unit's page, re-read HERE rather than
# trusted from whatever curate happened to read months ago -- the same
# threads-arc discipline that never cites a page nobody actually read.
# A generated plan may only speak from the plan's own steps; it may
# structure the practice, never invent what a body does with it, and that
# half is the sanitizer's job, not this one's -- generate_for only has to
# pick the right origin and hand it through.

_SYSTEM = (
    "You write one practice-session lesson script for a family app. Reply "
    'with ONLY JSON: {"scenes": [...]}. Scene types: '
    '{"type":"say","text":""} a short teaching beat; '
    '{"type":"do","text":"","seconds":60,"metronome_bpm":80} a '
    "practice interlude (seconds and metronome_bpm optional); "
    '{"type":"check","ask":""} a self-check with fixed answers; '
    '{"type":"show","primitive":{...},"caption":""} a visual. '
    'Primitives: {"kind":"timer","seconds":60}, '
    '{"kind":"metronome","bpm":80}, '
    '{"kind":"keyboard","keys":["C4","E4","G4"]}, '
    '{"kind":"fretboard","dots":[{"string":5,"fret":2,"finger":2}]}, '
    '{"kind":"cards","pairs":[{"front":"","back":""}]}, '
    '{"kind":"counter","target":10}. '
    "At most 10 scenes. Structure: a short why, then the drill as do-beats, "
    "one check near the end. Every do-beat must be startable alone from its "
    "text. No praise-fluff, no streaks, no scores. Never write about "
    "weight, calories, body composition, or dieting -- any scene that does "
    "is dropped before it ever reaches a family, so writing one only "
    "wastes this call."
)

_CITED_PROMPT = (
    "Turn THIS material into tonight's {minutes}-minute session script. Use "
    "ONLY what the material says — do not add exercises or advice it does "
    'not contain.\n\nSession: {label} in phase {phase} of "{title}".\n'
    "Steps the plan already names: {steps}\n\nMATERIAL from {url}:\n{page}"
)

_GENERATED_PROMPT = (
    "Write tonight's {minutes}-minute session script for "
    '"{title}" '
    "(phase {phase}, session {label}). Build it AROUND these steps — they "
    "are the session, your script paces and explains them: {steps}\n"
    "Unit notes: {body}\nProgression rule: {progression}\n"
    "Structure the practice (warmup, the work, brief review). Do NOT "
    "prescribe how to hold or move any part of the body."
)


def generate_for(program: dict, window: dict, unit: dict, settings: dict):
    """One slot's lesson, written and stored — or nothing, quietly.

    A cited plan speaks only from its page: the unit's url is re-read HERE,
    at generation time, rather than trusted from whatever curate happened
    to read months ago -- a citation is only as good as the read behind
    it. A cited unit that HAS a url and fails to load gets no script at
    all, ever: an outage is never papered over with a generated stand-in,
    and that rule is absolute.

    A cited unit with NO url at all is a different fact about the world,
    not an outage, and it is not an edge case -- programs_curate's own
    anti-hallucination guard (`_clean_units`) legitimately emits exactly
    this shape whenever a unit's claimed source was never actually read,
    which is the book-spine situation the design names outright:
    "structure generated, sequence cited." Treating that the same as a
    dead fetch would leave the slot permanently silent for a reason that
    has nothing to do with an outage, so it falls through to the generated
    path instead -- this one slot's origin becomes 'generated', its
    source_url stays empty, and `read_page` is never called for a page
    that was never claimed. A generated plan, whether the whole program is
    one or a single cited slot fell through to it, speaks only from the
    plan's own steps; keeping it from prescribing how a body moves is the
    sanitizer's job, not this function's -- generate_for only has to pass
    the right origin through.

    Storage already refuses to overwrite a hand edit. What it cannot know
    on its own is whether a slot has any lesson at all, edited or not --
    so that check happens here, first, before either a page fetch or a
    model call is spent on a slot that does not need one. The
    'background' tier is deliberate too: this is meant to be called from a
    nightly sweep with nobody waiting on the other end, so it spends the
    huge, slow gemma quota first and leaves the fast lite models free for
    whoever actually is waiting, elsewhere.

    Never raises. Any failure -- a malformed program row, an exhausted
    model pool, a page that will not load -- comes back as a printed line
    and a None, so a sweep calling this in a loop never needs a
    try/except of its own.
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
        url = (window.get('unit_url') or '') if origin == 'cited' else ''
        if origin == 'cited' and url:
            page = web.read_page(url)
            if not page:
                return None                   # a url exists and would not
                                               # load: an outage, never
                                               # papered over
            source_url = url
            prompt = _CITED_PROMPT.format(url=url, page=page[:8000], **fields)
        else:
            # Either this plan was never cited, or it was and THIS unit
            # carries no url at all -- not a fetch that failed, a slot with
            # nothing to fetch. Falls through to the same generated path a
            # generated plan already uses; see the docstring above for why
            # that is correct rather than a workaround.
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


# --- the nightly sweep ---------------------------------------------------
# generate_for is a single slot; this is what actually runs, once a day,
# with nobody watching. It exists because "a lesson generates itself"
# (Task 9) is only half a feature until something calls it -- and calls it
# exactly once, not once per 30-second tick forever.

def generate_due(now=None) -> int:
    """Tomorrow's lessons, written tonight. Called blindly from the 30s
    loop (main.py) and self-throttled to one real pass per day, so a
    restart never double-spends and idle cost is one app_state read.

    The day-marker check comes FIRST, ahead of both settings reads --
    self-throttling is the whole point of a function a 30s loop calls
    unconditionally forever, the same traffic-sweep shape
    maps.run_day_of_traffic_sweep already uses one block up in that loop.
    Neither settings check sets the marker: only a real pass earns it, so
    flipping a switch back on later gets tonight's sweep rather than
    waiting out a day a disabled sweep never actually ran.

    Never raises. `generate_for` already promises that per slot; the loop
    over `practice_windows` here carries no other risk beyond what
    `due_practice_pushes` already runs unguarded from the same caller, and
    main.py wraps this call the same way it wraps that one.
    """
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
    for w in programs.practice_windows(
            tomorrow, tomorrow + datetime.timedelta(days=1)):
        row = rows.get(w.get('program_id'))
        if not row:
            continue
        phase = programs.progress(row).get('phase') or {}
        unit = programs.unit_for(row, phase) or {}
        if generate_for(row, w, unit, settings):
            wrote += 1
    return wrote
