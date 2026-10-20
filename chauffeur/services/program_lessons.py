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
from functools import wraps
from contextlib import nullcontext

from services import deletion

MAX_SCENES = 12
MAX_TEACH_TITLE = 80
MAX_TEACH_TEXT = 700
MAX_TEACH_SPEAK = 500
MAX_TEACH_EXAMPLES = 5
MAX_TEACH_EXAMPLE = 160
VARIABLES = ('name', 'project')
VARIABLE_RE = re.compile(r'\{[A-Za-z_]+\}')
BUDGET_LOW, BUDGET_HIGH, SHORTFALL = 0.8, 1.2, 0.5
MAX_TEXT = 280
MAX_SHORT_TEXT = 120               # a check's ask, a show's caption, a card face
# One BEAT, not one session -- the longest a single countdown may run.
# This used to be 240*60, which is `programs.MAX_MINUTES` in seconds: the
# ceiling on a whole session, handed to one drill inside it, under a comment
# saying the opposite. An hour is already longer than any beat a real
# session holds and is unmistakably minutes rather than an afternoon.
MAX_DO_SECONDS = 60 * 60

# A counter's own pace, in seconds between one rep and the next -- see
# _valid_counter's own comment for why 1/10/3. Exists so a slot's session
# length (`shape.minutes`) and its own primitive's pace can both be
# validated by a number, never left to whatever a model happened to write.
COUNTER_MIN_SPR = 1
COUNTER_MAX_SPR = 10
COUNTER_DEFAULT_SPR = 3

# What Argyle SAYS on a scene, separate from what the scene shows. Capped
# shorter than MAX_TEXT on purpose: a spoken line is heard once, at the
# pace a voice reads it, over whatever else is happening in the room --
# past a couple of sentences nobody is still listening, and a beat's own
# visible text is where the long version belongs.
MAX_SPEAK = 200

# Two voices for one persona, not two personas: `coach` paces a drill,
# `calm` winds one down. The player maps them to rate and pitch; nothing
# here knows or cares how.
TONES = ('coach', 'calm')

# The two audio figures the player can draw, closed-set for exactly the
# reason every primitive kind is: a chime the renderer has never heard of
# is silence with a name.
CHIMES = ('success', 'fanfare')

_NOTE_RE = re.compile(r'^[A-G][#b]?[0-8]$')

# Cues: the lines Argyle says WHILE a drill runs, scheduled against that
# beat's own clock. Eight is already more than any one beat can carry
# without becoming a monologue over the top of the work, and the say cap
# is well under a beat's own text because a cue arrives unprompted, over
# whatever is happening, and has to be understood in one pass.
MAX_CUES = 8
MAX_CUE_SAY = 120

# A wait beat: the dough proofs, the glue sets, the paint dries. Three
# hours is the ceiling because past that a household is not "in a
# session" any more, they are doing something else and will come back
# tomorrow -- and a timer promising to call a room in the middle of the
# night is a promise this app should not make.
MAX_WAIT_MINUTES = 180
MAX_WAIT_ANNOUNCE = 120

# How many armed calls the queue may hold at once, and how long past its
# time an unfired one is still worth saying. The cap is a runaway guard,
# not a product limit -- one household cannot plausibly have twenty
# things proofing at once, and a panel looping on a bug can. The staleness
# window is the answer to an app that was off overnight: a call about
# dough somebody has already thrown out is not news, it is a confusing
# voice in an empty kitchen.
MAX_WAIT_QUEUE = 20
WAIT_STALE_S = 24 * 3600

# An offer: what a "not yet" tap may propose. Four beats, because a
# detour longer than that is not a detour, it is a second lesson nobody
# chose; and a label short enough to read on a chip while standing at a
# piano.
MAX_OFFER_LABEL = 60
MAX_OFFER_SCENES = 4

# A hint ladder: rungs from the widest nudge to the narrowest, then the
# answer. Four is the ceiling because a fifth rung is nearly always the
# answer with a question mark on it -- and because the point of a ladder
# is to stop before the answer, not to walk somebody down a staircase.
MAX_HINT_STEPS = 4

# Listening. Three modes, and the split between them is what a microphone
# can HONESTLY answer: presence knows somebody made a sound, pitch knows
# which note, tempo knows whether the peaks line up with the click. None
# of them knows whether it was any good, and none of them ever will -- a
# quality judgment is the one thing this app refuses to make about a
# person practising.
#
# The window is bounded at both ends for the same reason a do-beat is:
# under five seconds nobody has finished a phrase, and past two minutes an
# open microphone in a family's living room has stopped being a scene and
# started being a fixture.
# Run-lines: Argyle says the other character's cue, you deliver yours.
# Eight exchanges is a scene, not a play -- past that nobody is
# rehearsing, they are reading.
MAX_LINE_PAIRS = 8

# The rendered letter-sound set, read from disk ONCE and never listed
# here. A key with no file behind it must be dropped, and the only thing
# that actually knows which files exist is the manifest
# tools/gen_phonemes.py writes -- a second list in this module would be a
# second thing to keep in step, and the failure mode of it drifting is a
# card offering a sound that plays nothing.
_PHONEME_KEYS = None
PHONICS_MANIFEST = 'static/phonics/manifest.json'

# Progressive fade: the same words, with more of them blanked each pass,
# until you are reciting rather than reading. Two passes is the smallest
# thing that is a fade at all; four is where a long passage stops being
# learnable in one sitting.
MIN_FADE_PASSES = 2
MAX_FADE_PASSES = 4

LISTEN_MODES = ('presence', 'pitch', 'tempo')
MIN_LISTEN_SECONDS = 5
MAX_LISTEN_SECONDS = 120
DEFAULT_LISTEN_SECONDS = 20

# A BCP-47 tag only as far as this app can actually act on one: a language
# and, optionally, a region. The player picks a voice by prefix, so the
# region half is a preference the browser may ignore and the language half
# is the part that has to be right.
_LANG_RE = re.compile(r'^[a-z]{2}(-[A-Z]{2})?$')


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


def scene_cap(minutes) -> int:
    """How many scenes a session this long may hold: one a minute between 12 and 40."""
    m = _to_int(minutes)
    return 12 if m is None else max(12, min(40, m))


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
    # `muted` is OPTIONAL -- most chords name none -- and, unlike a dot,
    # never carries a fret or a finger: a muted string is "do not play
    # this", not a position. Held to the same all-or-nothing rule as
    # `dots` itself: present but malformed (wrong type, an out-of-range
    # string number) fails the whole primitive rather than silently
    # dropping the bad entries, the same as every other primitive here.
    muted = p.get('muted')
    if muted is not None:
        if not (isinstance(muted, list) and len(muted) <= 6):
            return False
        for m in muted:
            s = _to_int(m)
            if s is None or not (1 <= s <= 6):
                return False
    return True


def _valid_metronome(p):
    bpm = _to_int(p.get('bpm'))
    return bpm is not None and 30 <= bpm <= 240


def _valid_timer(p):
    secs = _to_int(p.get('seconds'))
    return secs is not None and 5 <= secs <= MAX_DO_SECONDS


def _valid_cards(p):
    # Validity is asked of the CLEANED face, never the raw one, so this and
    # `_build_primitive` below can never disagree about whether a pair has
    # words on it: a face that is only whitespace collapses to '' here
    # exactly as it does there.
    pairs = p.get('pairs')
    return (isinstance(pairs, list) and 0 < len(pairs) <= 12
            and all(isinstance(x, dict)
                    and _clean_text(x.get('front'), MAX_SHORT_TEXT)
                    and _clean_text(x.get('back'), MAX_SHORT_TEXT)
                    for x in pairs))


def phoneme_keys() -> frozenset:
    """Which letter sounds this install actually has audio for.

    Empty until `tools/gen_phonemes.py` has been run on the live add-on,
    where the household's own Piper voice is reachable -- and empty is the
    correct empty state rather than a gap: an unlisted key is dropped at
    the door and the player draws no speaker tap, because a letter sound
    said wrong by a general TTS voice is worse than silence and a
    five-year-old will believe it either way.

    Read once and cached for the process. The manifest only changes when
    somebody runs that tool by hand, which is a restart-shaped event.
    """
    global _PHONEME_KEYS
    if _PHONEME_KEYS is None:
        import json
        import os
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        try:
            with open(os.path.join(here, PHONICS_MANIFEST),
                      encoding='utf-8') as f:
                data = json.load(f) or {}
            _PHONEME_KEYS = frozenset((data.get('phonemes') or {}).keys())
        except deletion.Cancelled:
            raise
        except Exception as e:
            print(f"[lessons] no phoneme manifest ({e}); cards stay silent")
            _PHONEME_KEYS = frozenset()
    return _PHONEME_KEYS


def _valid_lines(p):
    # BOTH halves of every pair. A cue with no line prompts a silence,
    # and a line with no cue arrives out of nowhere -- neither is a
    # rehearsal, and the scene degrades to its caption rather than
    # half-running one.
    pairs = p.get('pairs')
    return (isinstance(pairs, list) and 0 < len(pairs) <= MAX_LINE_PAIRS
            and all(isinstance(x, dict) and _clean_text(x.get('cue'))
                    and _clean_text(x.get('line')) for x in pairs))


def _valid_tuner(p):
    # A tuner needs nothing at all -- "tune up" is a complete instruction
    # and the needle draws whatever it hears. `target` is optional and,
    # when unparseable, simply absent: a highlighted note the player
    # cannot name is worse than no highlight, and it is never worth
    # failing a whole scene over.
    return True


def _valid_listen(p):
    # The mode is the whole contract; everything else is optional and
    # mode-shaped. A target that is not a note and a bpm out of range are
    # dropped by _build_primitive rather than failing the primitive: a
    # scene that listens without a target still listens, and refusing a
    # whole beat over a decoration would cost more than it saves.
    return p.get('mode') in LISTEN_MODES


def _valid_hints(p):
    # BOTH halves or nothing. Rungs with no answer strand somebody at the
    # bottom of a ladder; an answer with no rungs is a `say` beat that
    # thinks it is one. The scene degrades to its caption either way,
    # which is the same answer every other broken primitive gets.
    steps = p.get('steps')
    if not (isinstance(steps, list) and 0 < len(steps) <= MAX_HINT_STEPS):
        return False
    if not all(_clean_text(s) for s in steps):
        return False
    return bool(_clean_text(p.get('answer')))


def _valid_counter(p):
    # `target` is the whole contract. The design's primitives table once
    # promised a `label` too; nothing ever validated one and nothing ever
    # drew one -- a `show` scene's own caption is the words above a counter
    # (lesson_player.html renders it directly above the dial), so a second
    # unscreened text field would have been a duplicate with a hole in it.
    target = _to_int(p.get('target'))
    if target is None or not (1 <= target <= 500):
        return False
    # `seconds_per_rep` is OPTIONAL -- a counter without one still means
    # something (_build_primitive fills in COUNTER_DEFAULT_SPR) -- but
    # when the model DOES set it, it is clamped like every other numeric
    # param: 1s floor (fast enough that a slow browser TTS call can still
    # keep pace, once it is cancelled and restarted per tick -- see
    # lesson_player.html's speakCount()) and 10s ceiling (a deliberately
    # slow, controlled rep -- a held stretch, an eccentric-focused strength
    # rep -- past which "paced counting" stops helping and starts
    # dragging). 3s is the default: close to how a person actually counts
    # reps out loud with a beat of space between them, per the report this
    # primitive was added to answer.
    spr = p.get('seconds_per_rep')
    if spr is not None:
        spr_i = _to_int(spr)
        if spr_i is None or not (COUNTER_MIN_SPR <= spr_i <= COUNTER_MAX_SPR):
            return False
    return True


# kind -> validator. Adding a primitive is a new row here plus a renderer
# block in lesson_player.html; the script schema never changes.
PRIMITIVES = {
    'timer': _valid_timer,
    'metronome': _valid_metronome,
    'keyboard': _valid_keyboard,
    'fretboard': _valid_fretboard,
    'cards': _valid_cards,
    'counter': _valid_counter,
    'hints': _valid_hints,
    'listen': _valid_listen,
    'tuner': _valid_tuner,
    'lines': _valid_lines,
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
    if window.get('lesson_id'):
        return {'lesson_id': window['lesson_id'],
                'variant_label': str(window.get('variant_label') or '')}
    return {'phase_name': str(window.get('phase_name') or ''),
            'unit_n': int(unit_n or 0),
            'session_label': str(window.get('session_label') or '')}


def resolve_slot(program: dict, slot: dict) -> dict:
    """Translate the old tuple for one release; named lessons never follow the bookmark.

    Unconverted runs retain their old keys until Task 5 migrates their scripts.
    An unknown legacy tuple stays a missing slot, rather than opening today's lesson.
    """
    from services import programs
    row = programs.load(program) or {}
    slot = slot or {}
    if slot.get('lesson_id'):
        if not any(l['id'] == slot['lesson_id'] for l in row.get('lessons') or []):
            raise ValueError(programs.MOVED_LESSON)
        return {'lesson_id': str(slot['lesson_id']),
                'variant_label': str(slot.get('variant_label') or '')}
    try:
        unit_n = int(slot.get('unit_n') or 0)
    except (ValueError, TypeError, OverflowError):
        unit_n = -1  # Unknown slot; never the phase-only zero alias.
    legacy = {'phase_name': str(slot.get('phase_name') or ''),
              'unit_n': unit_n,
              'session_label': str(slot.get('session_label') or '')}
    if not row.get('library_id'):
        return legacy
    phase = next((p for p in row.get('phases') or [] if p.get('name') == legacy['phase_name']), {})
    units = phase.get('units') or []
    unit = next((u for u in units if u.get('n') == legacy['unit_n']), None)
    if not unit and legacy['unit_n'] == 0 and len(units) == 1:
        unit = units[0]  # the old phase-only slot had no unit number
    if not unit:
        return legacy
    return {'lesson_id': unit['lesson_id'], 'variant_label': legacy['session_label']}


def _clean_text(raw, cap: int = MAX_TEXT) -> str:
    text = VARIABLE_RE.sub(lambda m: m.group(0) if m.group(0)[1:-1] in VARIABLES else '', str(raw or ''))
    return re.sub(r'\s+', ' ', text).strip()[:cap]


def _build_primitive(prim):
    """A stored primitive, REBUILT from the keys its own validator checked.

    The first cut stored the model's own dict verbatim
    (`{'primitive': prim}`), which quietly cost two things. Any extra key
    the model invented -- `{"kind":"cards","pairs":[...],"note":"keep your
    wrist straight"}` -- was stored and shipped whole, past every cap and
    past both screens, because nothing here ever looked at a key it had not
    asked for. And the dict that reached storage was the very object the
    caller still held, so a later mutation of the input would silently
    rewrite a sanitized scene. Rebuilding from the validated keys closes
    both at once, and it means a primitive's own free text (a card face) is
    capped exactly like every other string in a script.

    Returns None for an unknown kind or for params the validator refuses;
    the caller decides whether that degrades to a caption or drops the
    scene. Screening is deliberately NOT here -- it needs the script's
    origin, and `sanitize_script` runs it over `_primitive_text` below.
    """
    if not isinstance(prim, dict):
        return None
    kind = prim.get('kind')
    if kind not in PRIMITIVES or not PRIMITIVES[kind](prim):
        return None
    if kind == 'timer':
        return {'kind': 'timer',
                'seconds': max(5, min(MAX_DO_SECONDS, _to_int(prim.get('seconds'))))}
    if kind == 'metronome':
        return {'kind': 'metronome',
                'bpm': max(30, min(240, _to_int(prim.get('bpm'))))}
    if kind == 'keyboard':
        return {'kind': 'keyboard', 'keys': [str(k) for k in prim['keys']]}
    if kind == 'fretboard':
        built = {'kind': 'fretboard',
                 'dots': [{'string': _to_int(d.get('string')),
                           'fret': _to_int(d.get('fret')),
                           'finger': _to_int(d.get('finger'))}
                          for d in prim['dots']]}
        # Only added when the model actually sent one -- an omitted
        # `muted` stays omitted here too, the same "exactly the validated
        # keys survive" rule every other primitive follows (see the
        # docstring above). `set(...)` first so a duplicate string number
        # can't draw the same X twice.
        if prim.get('muted') is not None:
            built['muted'] = sorted({_to_int(m) for m in prim['muted']})
        return built
    if kind == 'cards':
        # A pair may also carry its own voice: `speak` for the words a
        # browser says correctly, `phoneme` for the letter sounds no
        # general voice does. Both optional, both dropped rather than
        # guessed at, and the card itself is never lost over either --
        # a silent card is a card, a missing card is a gap in a lesson.
        # `speak` is NOT screened here: _primitive_text below hands it to
        # the same screens the faces go through, so a screened spoken
        # face drops its whole scene exactly as a screened written one
        # does, in one place rather than two.
        pairs = []
        for x in prim['pairs']:
            pair = {'front': _clean_text(x.get('front'), MAX_SHORT_TEXT),
                    'back': _clean_text(x.get('back'), MAX_SHORT_TEXT)}
            speak = _clean_text(x.get('speak'), MAX_SHORT_TEXT)
            if speak:
                pair['speak'] = speak
            lang = x.get('speak_lang')
            if isinstance(lang, str) and _LANG_RE.match(lang):
                pair['speak_lang'] = lang
            if x.get('phoneme') in phoneme_keys():
                pair['phoneme'] = x['phoneme']
            pairs.append(pair)
        return {'kind': 'cards', 'pairs': pairs}
    if kind == 'lines':
        built = {'kind': 'lines',
                 'pairs': [{'cue': _clean_text(x.get('cue')),
                            'line': _clean_text(x.get('line'))}
                           for x in prim['pairs']]}
        lang = prim.get('lang')
        if isinstance(lang, str) and _LANG_RE.match(lang):
            built['lang'] = lang
        return built
    if kind == 'tuner':
        built = {'kind': 'tuner'}
        target = str(prim.get('target') or '')
        if _NOTE_RE.match(target):
            built['target'] = target
        return built
    if kind == 'listen':
        built = {'kind': 'listen', 'mode': prim['mode'],
                 'seconds': max(MIN_LISTEN_SECONDS,
                                min(MAX_LISTEN_SECONDS,
                                    _to_int(prim.get('seconds'))
                                    or DEFAULT_LISTEN_SECONDS))}
        target = str(prim.get('target') or '')
        if _NOTE_RE.match(target):
            built['target'] = target
        bpm = _to_int(prim.get('bpm'))
        if bpm is not None and 30 <= bpm <= 240:
            built['bpm'] = bpm
        return built
    if kind == 'hints':
        return {'kind': 'hints',
                'steps': [_clean_text(x) for x in prim['steps'][:MAX_HINT_STEPS]],
                'answer': _clean_text(prim.get('answer'))}
    # counter: seconds_per_rep always ends up in the rebuilt primitive,
    # model-supplied and clamped or defaulted to COUNTER_DEFAULT_SPR when
    # absent -- so the player never has to guess a pace for a script this
    # door just built (a fallback for an OLDER stored row, written before
    # this field existed, still lives client-side; see lesson_player.html).
    spr = _to_int(prim.get('seconds_per_rep'))
    return {'kind': 'counter', 'target': _to_int(prim.get('target')),
            'seconds_per_rep': max(COUNTER_MIN_SPR,
                                   min(COUNTER_MAX_SPR, spr or COUNTER_DEFAULT_SPR))}


def _primitive_text(prim: dict) -> list:
    """Every free-text field a primitive carries. Card faces are the only
    ones today -- every other primitive is numbers and note names -- and
    they were the hole: a card `back` reading "About 300 calories - great
    for weight loss. Keep your wrist straight." survived verbatim, because
    the `show` branch screened the caption and nothing else. The design says
    the screens run on ALL script text, whatever shape it arrives in."""
    if prim.get('kind') == 'cards':
        return [f for pair in prim.get('pairs') or []
                for f in (pair.get('front') or '', pair.get('back') or '',
                          pair.get('speak') or '')]
    # A hint ladder is nothing BUT free text -- every rung, and the answer
    # at the bottom of it. Exactly the hole card faces had before this
    # function existed: a screened caption over an unscreened payload.
    if prim.get('kind') == 'hints':
        return list(prim.get('steps') or []) + [prim.get('answer') or '']
    # Both halves of a run-line: the cue is SPOKEN, which makes it the
    # more important of the two to screen, not the less.
    if prim.get('kind') == 'lines':
        return [f for pair in prim.get('pairs') or []
                for f in (pair.get('cue') or '', pair.get('line') or '')]
    return []


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


def _voice_fields(raw: dict, origin: str) -> dict:
    """The fields any scene may carry for Argyle's voice.

    Screened exactly like visible text, because the spoken words are the
    ones a kid obeys -- a line nobody can read is still a line somebody
    hears and does, and screening only what is drawn would have left the
    louder half of a lesson unguarded. Same answer as `_primitive_text`
    gives a card face, one field over.

    A field that fails is DROPPED; the scene is not. That asymmetry is
    deliberate and it is the opposite of what a screened `text` gets: the
    visible half already passed its own screen, so the beat is sound and
    practice is never blocked over a spoken line nobody needed. A scene
    that plays silently is a smaller loss than a scene that vanishes.
    """
    out = {}
    speak = _clean_text(raw.get('speak'), MAX_SPEAK)
    if speak and not _screened(speak, origin):
        out['speak'] = speak
    lang = raw.get('speak_lang')
    if isinstance(lang, str) and _LANG_RE.match(lang):
        out['speak_lang'] = lang
    if raw.get('tone') in TONES:
        out['tone'] = raw['tone']
    if raw.get('chime') in CHIMES:
        out['chime'] = raw['chime']
    if raw.get('grownup'):
        out['grownup'] = True
    return out


def _clean_cues(raw, seconds, origin: str) -> list:
    """The lines a beat says to itself while it runs.

    A cue is scheduled against the beat's OWN clock, so a beat with no
    `seconds` has no clock to schedule against and its cues go entirely --
    the alternative is firing them at some moment nobody specified, which
    is worse than a silent drill. The beat itself always survives; a cue
    is an addition to a beat, never a condition of one.

    `at` is clamped INTO the beat rather than dropped when it falls
    outside it, because a model that writes 90 for a 60-second beat means
    "at the end" far more often than it means nothing, and the clamp says
    that unambiguously. Sorted here, once, so the player's own scheduler
    can be a cursor over an ordered list rather than a search.

    A screened `say` takes the WHOLE cue with it, not just its words: a
    cue is one utterance, and the half of one that survives -- a bare
    chime at 0:30 where a sentence was meant to be -- is noise with no
    explanation attached. Same reason `sanitize_script` drops a `show`
    outright when its primitive text is screened rather than degrading it
    to the caption it just refused.
    """
    if not isinstance(raw, list) or not seconds:
        return []
    out = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        at = _to_int(item.get('at'))
        if at is None:
            continue
        cue = {'at': max(0, min(int(seconds), at))}
        say = _clean_text(item.get('say'), MAX_CUE_SAY)
        if say:
            if _screened(say, origin):
                continue
            cue['say'] = say
        # A cue's own language, the same tag a scene's `speak_lang` takes.
        # Dropped here until 2026-10-20, so a Portuguese cue inside an
        # English beat could only ever be read in the English voice.
        lang = item.get('speak_lang')
        if cue.get('say') and isinstance(lang, str) and _LANG_RE.match(lang):
            cue['speak_lang'] = lang
        if item.get('count'):
            cue['count'] = True
        if item.get('chime'):
            cue['chime'] = True
        # A cue with nothing to say, count or sound is a scheduled
        # silence: a timestamp and no event.
        if len(cue) > 1:
            out.append(cue)
    out.sort(key=lambda c: c['at'])
    return out[:MAX_CUES]


def _clean_offer(raw, origin: str):
    """What a "not yet" may propose: a label and a short detour.

    Offered, never automatic -- that is a player rule, but this is where
    the shape that makes it possible is bounded. Three things may not be
    inside an offer, and all three are the same mistake at different
    sizes: a `check` is a second decision inside a decision, a `wait` is a
    timer inside a detour nobody planned to be on, and another offer is
    unbounded recursion wearing a label. The inner scenes go through
    `sanitize_script` itself (so every cap and both screens apply exactly
    once, in one place) at depth 1, which is where that function refuses
    to read an offer at all -- so the bound is structural rather than a
    counter somebody has to remember to decrement.

    A failed offer drops the OFFER, never the check it hangs off. The
    check asked a real question and its own text already passed its own
    screen; losing the beat because the detour behind it was malformed
    would be the tail refusing the dog.
    """
    if not isinstance(raw, dict):
        return None
    label = _clean_text(raw.get('label'), MAX_OFFER_LABEL)
    if not label or _screened(label, origin):
        return None
    inner = [s for s in sanitize_script(raw.get('scenes'), origin, _depth=1)
             if s.get('type') not in ('check', 'wait')]
    if not inner:
        return None
    return {'label': label, 'scenes': inner[:MAX_OFFER_SCENES]}


def sanitize_script(scenes: list, origin: str, minutes=None, _depth: int = 0) -> list:
    """Every script through one door. Clamps, whitelists, screens; returns
    what survives, which may be nothing — and nothing is a fine answer,
    because the player's fallback ladder plays the plain steps.

    `_depth` is not a caller's argument. It is 1 exactly once, when
    `_clean_offer` above runs an offer's own scenes back through here, and
    all it does is refuse to read a further offer at that depth. That
    makes "an offer may not contain an offer" a property of the shape
    rather than a rule anybody has to enforce twice.
    """
    cap = scene_cap(minutes)
    out = []
    # `scenes or []` only coalesces FALSY junk (None, 0, ''); a truthy
    # scalar -- an int, a float, a bare True -- is not a list and would
    # otherwise reach the for and raise. Anything that is not actually a
    # list of scenes becomes no scenes, the same way a malformed scene
    # inside the list becomes no scene below.
    for raw in (scenes if isinstance(scenes, list) else []):
        if len(out) >= cap:
            break
        if not isinstance(raw, dict):
            continue
        kind = raw.get('type')
        # Computed once per scene and merged by every branch below,
        # degrade paths included -- the voice rides the SCENE, not one
        # type of it, so a `show` that speaks past its caption and a
        # `check` that reads its ask aloud cost nothing extra here.
        voice = _voice_fields(raw, origin)
        if kind == 'say':
            text = _clean_text(raw.get('text'))
            if not text or _screened(text, origin):
                continue
            scene = {'type': 'say', 'text': text}
            # A fading beat is the same words with more of them blanked
            # each pass, until you are reciting rather than reading.
            # `passes` alone means nothing -- it is a parameter of the
            # fade, not a beat of its own -- so it only survives beside it.
            if raw.get('fade'):
                scene['fade'] = True
                scene['passes'] = max(MIN_FADE_PASSES,
                                      min(MAX_FADE_PASSES,
                                          _to_int(raw.get('passes'))
                                          or MIN_FADE_PASSES))
            scene.update(voice)
            out.append(scene)
        elif kind == 'teach':
            text = _clean_text(raw.get('text'), MAX_TEACH_TEXT)
            title = _clean_text(raw.get('title'), MAX_TEACH_TITLE)
            if not text or _screened(text, origin) or (title and _screened(title, origin)):
                continue
            scene = {'type': 'teach', 'text': text}
            if title:
                scene['title'] = title
            examples = []
            for ex in (raw.get('examples') if isinstance(raw.get('examples'), list) else []):
                if isinstance(ex, str):
                    ex = {'text': ex}
                if not isinstance(ex, dict):
                    continue
                etext = _clean_text(ex.get('text'), MAX_TEACH_EXAMPLE)
                if not etext or _screened(etext, origin):
                    continue
                entry = {'text': etext}
                lang = ex.get('speak_lang')
                if isinstance(lang, str) and _LANG_RE.match(lang):
                    entry['speak_lang'] = lang
                examples.append(entry)
                if len(examples) >= MAX_TEACH_EXAMPLES:
                    break
            if examples:
                scene['examples'] = examples
            voice = dict(voice)
            speak = _clean_text(raw.get('speak'), MAX_TEACH_SPEAK)
            voice.pop('speak', None)
            if speak and not _screened(speak, origin):
                voice['speak'] = speak
            scene.update(voice)
            out.append(scene)
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
            cues = _clean_cues(raw.get('cues'), scene.get('seconds'), origin)
            if cues:
                scene['cues'] = cues
            scene.update(voice)
            out.append(scene)
        elif kind == 'check':
            ask = _clean_text(raw.get('ask'), MAX_SHORT_TEXT)
            if not ask or _screened(ask, origin):
                continue
            scene = {'type': 'check', 'ask': ask, **voice}
            offer = (_clean_offer(raw.get('not_yet_offer'), origin)
                     if not _depth else None)
            if offer:
                scene['not_yet_offer'] = offer
            out.append(scene)
        elif kind == 'wait':
            # A beat whose whole content is that nothing happens for a
            # while. It needs BOTH halves or it is not a wait: minutes
            # with no words is a blank screen counting down, and words
            # with no minutes is a `say` that thinks it is a timer.
            text = _clean_text(raw.get('text'))
            mins = _to_int(raw.get('minutes'))
            if not text or mins is None or _screened(text, origin):
                continue
            scene = {'type': 'wait',
                     'minutes': max(1, min(MAX_WAIT_MINUTES, mins)),
                     'text': text}
            announce = _clean_text(raw.get('announce'), MAX_WAIT_ANNOUNCE)
            if announce and not _screened(announce, origin):
                scene['announce'] = announce
            scene.update(voice)
            out.append(scene)
        elif kind == 'show':
            prim = raw.get('primitive')
            caption = _clean_text(raw.get('caption'), MAX_SHORT_TEXT)
            if caption and _screened(caption, origin):
                continue
            built = _build_primitive(prim)
            # The screens run on the primitive's own text as well as the
            # caption, and a violating scene is DROPPED rather than
            # reworded -- the same answer a screened caption already gets
            # two lines up, and the same one a screened say/do/check gets.
            # Degrading to the caption here would keep a scene the screen
            # just refused, one field short of the reason it refused it.
            if built and any(_screened(t, origin)
                             for t in _primitive_text(built)):
                continue
            if built:
                out.append({'type': 'show', 'primitive': built,
                            'caption': caption, **voice})
            elif (isinstance(prim, dict) and prim.get('kind') in PRIMITIVES
                  and caption):
                # A known visual with broken params degrades to its own
                # caption — the words survive, the wrong picture does not.
                out.append({'type': 'say', 'text': caption, **voice})
            # An unknown kind is dropped whole: the model demanded a
            # visual this player has never heard of.
    return out


def _words(text) -> float:
    return len(str(text or '').split())


def estimate_seconds(scenes) -> int:
    total = 0.0
    for s in (scenes if isinstance(scenes, list) else []):
        if not isinstance(s, dict):
            continue
        kind = s.get('type')
        if kind == 'say':
            if s.get('fade'):
                total += (_to_int(s.get('passes')) or MIN_FADE_PASSES) * _words(s.get('text')) / 2.5
            else:
                total += 4 + _words(s.get('text')) / 2.5
            total += _words(s.get('speak')) / 2.5
        elif kind == 'teach':
            total += 6 + _words(s.get('text')) / 2.5 + _words(s.get('speak')) / 2.5 + 6 * len(s.get('examples') or [])
        elif kind == 'do':
            total += _to_int(s.get('seconds')) or 60
        elif kind == 'check':
            total += 8
        elif kind == 'wait':
            total += (_to_int(s.get('minutes')) or 0) * 60
        elif kind == 'show':
            p = s.get('primitive') or {}
            k = p.get('kind')
            if k in ('timer', 'listen'):
                total += _to_int(p.get('seconds')) or 0
            elif k == 'metronome':
                total += 45
            elif k in ('keyboard', 'fretboard', 'tuner'):
                total += 20
            elif k == 'cards':
                total += 8 * len(p.get('pairs') or [])
            elif k == 'lines':
                total += 12 * len(p.get('pairs') or [])
            elif k == 'counter':
                total += (_to_int(p.get('target')) or 0) * (_to_int(p.get('seconds_per_rep')) or COUNTER_DEFAULT_SPR)
            elif k == 'hints':
                total += 30
    return int(round(total))


def fill(scenes, vars: dict) -> list:
    """Substitute the closed variable set in every free-text field. Pure."""
    import copy
    values = {'name': str((vars or {}).get('name') or '').strip() or 'you',
              'project': str((vars or {}).get('project') or '').strip()}

    def sub(text):
        if not isinstance(text, str):
            return text
        for k, v in values.items():
            text = text.replace('{' + k + '}', v)
        return text

    def walk(node):
        if isinstance(node, dict):
            return {k: (walk(v) if k in ('examples', 'cues', 'pairs', 'steps', 'scenes', 'primitive', 'not_yet_offer')
                        else sub(v) if k in ('text', 'speak', 'ask', 'caption', 'announce', 'title', 'say', 'front', 'back',
                                              'cue', 'line', 'answer', 'label') else v)
                    for k, v in node.items()}
        if isinstance(node, list):
            return [walk(x) if isinstance(x, (dict, list)) else sub(x) for x in node]
        return node
    return walk(copy.deepcopy(scenes if isinstance(scenes, list) else []))


# --- the wait's one-shot call --------------------------------------------
# The single exception to "Argyle never speaks unprompted", and it is an
# exception a person asked for by name, out loud, in this session: the
# dough does not care that the player was closed and the tablet went to
# sleep. So the call outlives the session that armed it.
#
# It lives in `app_state` and on NO program row. That is the same rule the
# rest of this module keeps -- a lesson records nothing about how it went
# -- and it buys the one property this needs: app_state persists, so a
# restart between the arming and the firing loses nothing, while a program
# row would have turned an armed timer into a fact about somebody's plan.
#
# The queue carries its source program solely to cancel delivery when that
# program is deleted. It records no outcome or progress in the program.

WAIT_STATE_KEY = 'lesson_wait_announces'


def arm_wait_announce(room: str, text: str, minutes: int, now_ts=None,
                      program_id: str = None, lesson_id: str = None,
                      variant_label: str = '') -> dict:
    """Queue one call into a room, `minutes` from now.

    Pruned on every write rather than on a schedule of its own: the queue
    is only ever touched by an arm or a fire, so there is no third moment
    at which stale entries could be swept, and doing it here means the
    list cannot grow across an app that never fires anything (every panel
    unreachable, HA down for a week).
    """
    with (deletion.acting_for('program', program_id) if program_id else nullcontext()):
        import time
        from services import storage, programs
        if program_id and not lesson_id:
            import datetime
            projection = programs.lesson_for(storage.get_program(program_id), datetime.date.today())
            lesson_id, variant_label = projection.get('lesson_id'), projection.get('variant_label') or ''
        now_ts = float(now_ts if now_ts is not None else time.time())
        mins = max(1, min(MAX_WAIT_MINUTES, _to_int(minutes) or 0))
        entry = {'fire_ts': now_ts + mins * 60,
                 'room': str(room or '')[:60],
                 'text': _clean_text(text, MAX_WAIT_ANNOUNCE),
                 'program_id': program_id, 'lesson_id': lesson_id,
                 'variant_label': variant_label}
        queue = storage.get_app_state(WAIT_STATE_KEY) or []
        if not isinstance(queue, list):
            queue = []
        queue = [e for e in queue
                 if isinstance(e, dict)
                 and float(e.get('fire_ts') or 0) > now_ts - WAIT_STALE_S]
        queue.append(entry)
        # Newest wins when the cap bites: an overflowing queue is a bug
        # somewhere upstream, and the sentence a person just asked for is more
        # likely to matter than one from an hour ago that never fired.
        storage.set_app_state(WAIT_STATE_KEY, queue[-MAX_WAIT_QUEUE:])
        return entry


def due_wait_announces(now_ts=None) -> list:
    """Everything owed by now, POPPED. One shot: an entry this returns is
    already gone from the queue, so a caller that crashes between reading
    and speaking loses a sentence rather than repeating one forever.

    A call more than a day past its time is dropped rather than said. An
    app that was off overnight coming back to announce that dough somebody
    has already thrown out is a confusing voice in an empty kitchen, and
    the timer it belonged to is long past being useful.

    Never raises -- it is called from the 30s loop, which has real work
    behind it.
    """
    import time
    from services import storage, access, programs
    now_ts = float(now_ts if now_ts is not None else time.time())
    try:
        queue = storage.get_app_state(WAIT_STATE_KEY) or []
        if not isinstance(queue, list) or not queue:
            return []
        due, keep = [], []
        for e in queue:
            if not isinstance(e, dict):
                continue
            if e.get('program_id') and access.gone('program', storage.get_program(e['program_id']), rid=e['program_id']):
                continue
            if e.get('program_id'):
                row = programs.load(storage.get_program(e['program_id']))
                if row and (row.get('unresolved') or (e.get('lesson_id') and not any(
                        l['id'] == e['lesson_id'] for l in row.get('lessons') or []))):
                    continue
            ts = float(e.get('fire_ts') or 0)
            if ts > now_ts:
                keep.append(e)
            elif ts > now_ts - WAIT_STALE_S:
                due.append(e)
            # else: stale, dropped without a word
        if len(keep) != len(queue):
            storage.set_app_state(WAIT_STATE_KEY, keep)
        return due
    except deletion.Cancelled:
        raise
    except Exception as e:
        print(f"[lessons] wait queue read failed: {e}")
        return []


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
    '{"type":"say","text":"","fade":true,"passes":3} a short '
    "teaching beat (\"fade\" repeats the same words with more of "
    "them blanked each pass, 2-4, for anything learned by heart); "
    '{"type":"teach","title":"","text":"","examples":[{"text":"","speak_lang":"pt-BR"}],"speak":""} '
    "a teaching beat: what is new, why it matters, what good looks like, in up to 700 characters, with up to 5 short "
    "examples (each may carry speak_lang when it is in another language; a tap says it) and up to 500 spoken characters; "
    '{"type":"do","text":"","seconds":60,"metronome_bpm":80,'
    '"cues":[{"at":30,"say":"Switch sides","speak_lang":"pt-BR"}]} a '
    "practice interlude (seconds and metronome_bpm optional; \"cues\" are "
    "lines said out loud DURING the beat, each at its own second into it "
    "-- up to 8, and only on a beat that has seconds. A cue carries "
    "\"say\" (with \"speak_lang\" when those words are not in the session "
    "language, so they are said in the right voice), or \"count\": true to "
    "say the seconds elapsed, or \"chime\": true for a tick); "
    '{"type":"check","ask":"","not_yet_offer":{"label":"Try it slower",'
    '"scenes":[...]}} a self-check with fixed answers -- "not_yet_offer" '
    "is optional and is what gets OFFERED (never forced) when the answer "
    "is not yet: a label and up to 4 ordinary beats, no checks and no "
    "waits inside it; "
    '{"type":"wait","minutes":45,"text":"","announce":""} time in which '
    "nothing happens (the dough rises, the glue sets) -- the app calls the "
    "room with \"announce\" when it is up, so use this instead of making "
    "somebody stand and watch a clock; "
    '{"type":"show","primitive":{...},"caption":""} a visual. '
    'Primitives: {"kind":"timer","seconds":60}, '
    '{"kind":"metronome","bpm":80}, '
    '{"kind":"keyboard","keys":["C4","E4","G4"]}, '
    '{"kind":"fretboard","dots":[{"string":5,"fret":2,"finger":2}],"muted":[6]} '
    '(string 1=high E .. string 6=low E; muted is optional, string numbers '
    "that are not played at all -- never a fret or a finger for those), "
    '{"kind":"cards","pairs":[{"front":"","back":"","speak":"",'
    '"speak_lang":"es"}]} '
    "(a pair may carry \"speak\", the words said out loud when the "
    "card is tapped, with an optional language tag), "
    '{"kind":"hints","steps":["widest nudge","narrower"],"answer":""} '
    '{"kind":"lines","pairs":[{"cue":"","line":""}],"lang":"en-GB"} '
    "(rehearsal: the app says the cue out loud, they answer with the "
    "line -- up to 8 exchanges), "
    '{"kind":"tuner","target":"E2"} '
    "(a live tuner needle; target is optional), "
    '{"kind":"listen","mode":"presence","seconds":20} '
    "(listens through the microphone where there is one and becomes a "
    "tap where there is not -- mode is presence, meaning they said or "
    "played something, or pitch with a target note like G3, or tempo "
    "with a bpm. It never judges whether it was any good), "
    "(a ladder for a problem: up to 4 rungs, each narrower than the "
    "last, and the answer only at the bottom -- never the answer "
    "straight away), "
    '{"kind":"counter","target":10,"seconds_per_rep":3} '
    "(seconds_per_rep is optional, 1-10, how long one rep takes so the "
    "count can pace itself hands-free -- default 3). "
    "STRUCTURE, four parts: OPEN connects to the previous lesson only when this one builds on it (cards or lines from its "
    "material, never more than two scenes; cooking and lawn mostly skip it). TEACH: at least one teach scene per new idea. "
    "WORK: the drill as do-beats and primitives, most of the time. WRAP: one check or one fade. "
    "VARIABLES: write {name} wherever a teacher would say the learner's name, and {project} for what they are working "
    "towards. Nothing else goes in braces. "
    "Every do-beat must be startable alone from its "
    "text. No praise-fluff, no streaks, no scores. Never write about "
    "weight, calories, body composition, or dieting -- anywhere, card "
    "fronts and backs included; any scene that does is dropped before it "
    "ever reaches a family, so writing one only wastes this call. "
    # The voice. Every scene may carry these; the assistant reads `speak`
    # aloud while the scene is on screen, so it is what a person HEARS
    # rather than a second copy of what they read.
    'Any scene may also carry: "speak" (up to 200 characters (500 on a teach scene) said out '
    "loud while that scene is showing -- write what a teacher would SAY, "
    "not a repeat of the text on screen), "
    '"speak_lang" (a language tag like "es" or "pt-BR", only when the '
    'spoken words are not in the session language), "tone" ("coach" for '
    'working, "calm" for winding down), "chime" ("success" or "fanfare", '
    'a short sound), and "grownup": true on any scene where a child '
    "needs an adult beside them. "
    # PATTERNS: enforcement in this module is entirely subtractive -- the
    # screens drop, they never require -- so the ceiling on how much a
    # lesson teaches is whatever this paragraph asks for.
    "Put \"grownup\": true on knives, heat, power "
    "tools and anything sharp or hot, so the scene asks for a grown-up. "
    "PATTERNS, by what the session is: music - teach names the notes or chords and is followed by a keyboard or fretboard "
    "show before metronome do-beats; strings tune up first. movement (anything moved or held) - teach says what the exercise "
    "is for and its pacing, never how to hold or move a joint; work is counters with spoken counts and switch-overs. cooking "
    "and crafts - teach the technique before the step it applies to; waits carry announce; grownup true on heat, blades, power "
    "tools. reading and phonics - teach the sound or rule with cards; work is cards and lines. problem-shaped (maths, puzzles) "
    "- teach the rule with one worked example; work is hint ladders, smallest nudge first. language - teach the rule with "
    "examples in both languages (speak_lang on the target-language ones); controlled practice through lines (lang set) and "
    "cards (speak + speak_lang); free production through a presence listen; at most one greeting beat in a session; OPEN "
    "reviews last lesson's words as cards. chemical (fertiliser, cleaner, weedkiller) - follow the label, never a rate or an amount."
)

# How many chargeable failures a single slot is allowed before generation
# stops spending calls on it, and how many slots one nightly pass may spend
# a call on at all. Both exist for the same reason: a sweep nobody is
# watching must have a ceiling on what it can quietly burn.
MAX_ATTEMPTS = 3   # the default; `lesson_max_attempts` in settings overrides it


def max_attempts(settings: dict = None) -> int:
    """How many chargeable failures a slot may burn before the sweep stops
    spending on it: the `lesson_max_attempts` setting (Config > Work >
    Lessons), 1..20, default MAX_ATTEMPTS. Transient failures and workflow
    pauses never count, so this only bounds real, repeatable failures."""
    from services import storage
    raw = (settings if settings is not None else (storage.get_settings() or {})).get('lesson_max_attempts')
    try:
        n = int(raw)
    except (TypeError, ValueError, OverflowError):
        return MAX_ATTEMPTS
    return max(1, min(20, n))
MAX_SLOTS_PER_PASS = 6

_CITED_PROMPT = (
    "Turn THIS material into tonight's {minutes}-minute session script. Use "
    "ONLY what the material says — do not add exercises or advice it does "
    "not contain, and anything you have the script SAY out loud must be "
    'the material\'s own words too.\n\nSession: {label} in phase {phase} '
    'of "{title}".\n{context}\n'
    "Steps the plan already names: {steps}\n\nMATERIAL from {url}:\n{page}"
)

_GENERATED_PROMPT = (
    "Write tonight's {minutes}-minute session script for "
    '"{title}" '
    "(phase {phase}, session {label}). Build it AROUND these steps — they "
    "are the session, your script paces and explains them: {steps}\n"
    "{context}\n"
    "Unit notes: {body}\nProgression rule: {progression}\n"
    "Structure the practice (warmup, the work, brief review). Do NOT "
    "prescribe how to hold or move any part of the body."
)


def profile_context(row: dict) -> str:
    from services import library
    made = row.get('made_for') or {}
    return (f"Who this is for: {library.made_for_line(made)}"
            + f", {made.get('sessions_per_week', 3)} sessions a week"
            + (f"; assumes {made['assumes']}." if made.get('assumes') else '.')
            + " Write it so they can run the session on their own; put grownup true on any scene that needs an adult.")


def _budget_lines(minutes: int) -> str:
    return (f"This session is {minutes} minutes. Write a script that runs between {int(minutes * BUDGET_LOW)} and "
            f"{int(minutes * BUDGET_HIGH)} minutes by this reckoning: a say or teach beat takes about a second per two and a "
            f"half words read plus the same for its spoken line, a teach adds six seconds per example, a do-beat takes its "
            f"seconds (60 when it has none), a check 8 seconds, a wait its minutes, cards 8 seconds a pair, lines 12 seconds a "
            f"pair, a counter its target times its pace, a metronome 45 seconds, a keyboard, fretboard or tuner 20, a hint ladder "
            f"30, a timer or listen its seconds. Up to {scene_cap(minutes)} scenes.")


def lesson_prompt(row: dict, lesson: dict, variant_label: str) -> str:
    phases = {p['id']: p for p in row.get('phases') or []}
    phase = phases.get(lesson.get('phase_id')) or {}
    ladder = row.get('lessons') or []
    idx = next((i for i, l in enumerate(ladder) if l['id'] == lesson['id']), 0)
    prev = ladder[idx - 1] if idx > 0 else None
    nxt = ladder[idx + 1] if idx + 1 < len(ladder) else None
    variant = next((v for v in lesson.get('variants') or [] if (v.get('label') or '') == (variant_label or '')), {}) if variant_label else {}
    steps = variant.get('steps') or lesson.get('steps') or []
    body = variant.get('body') or lesson.get('body') or ''
    minutes = int((row.get('made_for') or {}).get('minutes') or 25)
    lines = [f'Write the session script for "{row.get("title") or ""}", phase {phase.get("name") or ""}'
             + (f' ({phase.get("what")})' if phase.get('what') else '') + f', lesson "{lesson.get("title") or ""}"'
             + (f', session {variant_label}' if variant_label else '') + '.',
             profile_context(row), _budget_lines(minutes),
             'Steps the lesson names: ' + ' | '.join(steps), 'Lesson material: ' + body,
             'Progression rule: ' + (phase.get('progression') or '')]
    if prev:
        lines.append(f'Previous lesson: "{prev.get("title") or ""}" - {str(prev.get("body") or "")[:300]}')
    if nxt:
        lines.append(f'Next lesson: "{nxt.get("title") or ""}"')
    lines.append('Build the session around the steps and the material; teach before you drill. Do NOT prescribe how to hold '
                 'or move any part of the body.'
                 " Write {name} wherever a teacher would say the learner's name, and {project} for what they are working "
                 "towards. Nothing else goes in braces.")
    return '\n'.join(lines)


def shortfall_prompt(n_minutes: int, minutes: int) -> str:
    return (f"Your last script runs about {n_minutes} minutes of the {minutes} asked. Keep what works and add teaching, "
            f"practice and review until it fills the session.")


def _context_block(program: dict, now=None) -> str:
    """Who is practising, and when — the two facts this app holds for free
    and the prompts were spending nothing on.

    WHO decides the script in every domain, which is the lesson
    programs_curate learned one layer up when a plan written for a
    nine-year-old came back addressed to a generic adult beginner. Its
    `_who_line` is reused verbatim rather than re-derived here, so the
    plan and the lesson inside it can never describe the same person two
    different ways -- and it states an age ONLY when a birthdate is really
    on file, because guessing the one fact that decides the plan is worse
    than not knowing it.

    Whether they practise ALONE is the other half, and it is a different
    question from age: `practices_alone` is a per-child capability a
    parent can pin either way (stages.py), so it is asked rather than
    inferred. An adult has no stage and no capability list; an adult
    practises alone, which is the same default `capabilities` returning {}
    already implies.

    WHEN is one word and it only matters to a handful of programs -- a
    lawn in March and the same lawn in September are not the same evening
    -- but those programs cannot get it from anywhere else, and a month
    costs nothing to state.
    """
    import datetime
    from services import stages, storage, programs_curate
    member = None
    try:
        member = storage.get_member(program.get('member_id') or '')
    except Exception:
        member = None
    caps = stages.capabilities(member) if member else {}
    alone = caps.get('practices_alone', True)
    who = programs_curate._who_line(member, '')
    lines = [f"Who this is for: {who}."]
    if program.get('starting_point'):
        lines.append(f"Their starting point: {program['starting_point']}")
    lines.append("They can run this session on their own." if alone else
                 "They need a grown-up beside them for this session — write "
                 "the script so an adult can follow along too.")
    lines.append(f"It is {(now or datetime.datetime.now()).strftime('%B')}.")
    return "\n".join(lines)


def _phonics_line() -> str:
    """The letter sounds THIS install can actually play, named for the
    model — or nothing at all.

    `phoneme` validated, stored and rendered from the day it shipped, and
    no prompt ever mentioned it, so a model could only ever reach for
    `speak`. `speak: "l"` makes a browser say "ell", which is why every
    phonics card said the letter NAME instead of the sound: the field was
    a capability with no path to it.

    Built from the manifest rather than written into `_SYSTEM`, because
    which sounds exist is a property of what `tools/gen_phonemes.py`
    actually rendered on this machine, and a hardcoded list would promise
    sounds the sanitizer then drops. An install with none says nothing:
    offering a field whose every value will be refused spends the ask and
    teaches a shape that cannot be used.
    """
    keys = sorted(phoneme_keys())
    if not keys:
        return ''
    return (' A card pair may also carry "phoneme", a recorded letter '
            'SOUND played when the card is tapped -- use it instead of '
            '"speak" for a single letter or letter pair, because a voice '
            'reading "l" says its name and not its sound. Write the sound '
            'itself between slashes on the card face, the way a reading '
            'book prints it: front "k", back "/k/ as in kite". The only '
            'keys that exist are: ' + ', '.join(keys)
            + '. Keys starting name_ are the letter NAME (name_a is "ay"); '
              'the rest are sounds. Any other key is dropped.')


def system_prompt() -> str:
    """`_SYSTEM` plus whatever this install can add to it. One place, so
    a caller cannot forget the half that depends on the machine."""
    return _SYSTEM + _phonics_line()


def needs_lesson(program_id: str, slot: dict) -> bool:
    """Whether this slot would actually cost a model call.

    One predicate, two callers, so the rule cannot drift: `generate_for`
    asks it before spending anything, and `generate_due` asks it to decide
    whether a slot counts against the pass budget -- a pass that spent its
    whole allowance on slots which were only ever going to be skipped would
    be a cap on iteration, not on cost.

    False for a slot that already has a script (edited or not -- generated
    once, reused), and for one that has already burned MAX_ATTEMPTS
    chargeable failures; see `_record_attempt`.
    """
    from services import storage
    existing = storage.get_program_lesson(program_id, slot) or {}
    if existing.get('edited') or existing.get('scenes'):
        return False
    return int(existing.get('attempts') or 0) < max_attempts()


def _record_attempt(program_id: str, slot: dict, origin: str, source_url: str,
                    note: str, counts: bool = True) -> None:
    """A call was spent on this slot and no script came back.

    Left unrecorded, a slot whose script always sanitizes to nothing -- or
    a household whose `llm_gemini_api_key` is empty, where EVERY call fails
    forever -- re-spends a model call every night, silently, while the
    toggle says lessons are being written and nothing anywhere tells the
    difference between that and "the sweep has not reached this slot yet".

    The row this writes holds no scenes, so every surface still plays the
    fallback ladder exactly as before; what it adds is the reason, in
    words, where a person looks when they wonder why a lesson is plain (the
    slot's own editor on the programs page prints it), and an attempt count
    that stops the spending after MAX_ATTEMPTS. A TRANSIENT failure -- a
    429, a timeout, a 5xx, whatever the pool itself flags -- is recorded
    but never counted: a quota that ran out tonight is not a reason to stop
    trying a slot that may live for weeks. `DELETE
    /api/programs/{id}/lesson` drops the row, so the editor's own
    "Regenerate" is the reset.
    """
    from services import storage
    try:
        existing = storage.get_program_lesson(program_id, slot) or {}
        storage.upsert_program_lesson(program_id, slot, {
            'origin': origin, 'source_url': source_url, 'scenes': [],
            'attempts': int(existing.get('attempts') or 0) + (1 if counts else 0),
            'note': _clean_text(note, MAX_SHORT_TEXT),
            'model': existing.get('model') or ''})
    except deletion.Cancelled:
        raise
    except Exception as e:
        print(f"[lessons] could not record a failed attempt: {e}")


def _lesson_work(fn):
    @wraps(fn)
    def run(program, *args, **kwargs):
        with deletion.acting_for('program', program['id']):
            return fn(program, *args, **kwargs)
    return run


@_lesson_work
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

    Apart from deletion.Cancelled, failures -- a malformed program row, an exhausted
    model pool, a page that will not load -- comes back as a printed line
    and a None, so a sweep calling this in a loop never needs a
    try/except of its own.
    """
    from services import model_pools, storage, web, programs
    try:
        program = programs.load(program)
        if program.get('unresolved'):
            return None
        if window.get('lesson_id'):
            import datetime
            projection = programs.lesson_for(program, datetime.date.fromisoformat(
                window.get('date') or datetime.date.today().isoformat()),
                lesson_id=window['lesson_id'], variant_label=window.get('variant_label') or '')
            window = {**window, 'steps': projection['steps'], 'unit_title': projection['title'],
                      'unit_body': projection.get('body') or '', 'unit_url': projection.get('url') or ''}
        origin = ((program.get('source') or {}).get('origin')
                  or 'generated')
        slot = slot_of(window, unit_n=int((unit or {}).get('n') or 0))
        if not needs_lesson(program['id'], slot):
            # Already has its lesson, or has already burned its attempts.
            return None
        minutes = int((program.get('shape') or {}).get('minutes') or 25)
        fields = {'minutes': minutes,
                  'title': program.get('title') or '',
                  'phase': window.get('phase_name') or '',
                  'label': window.get('session_label') or 'practice',
                  'steps': ' | '.join(window.get('steps') or []),
                  'body': window.get('unit_body') or '',
                  'progression': window.get('progression') or '',
                  'context': _context_block(program)}
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
            system_prompt(), prompt, timeout_s=60, gemma_timeout_s=180,
            settings=settings)
        if not isinstance(res, dict) or res.get('error'):
            _record_attempt(
                program['id'], slot, origin, source_url,
                str((res or {}).get('error') if isinstance(res, dict)
                    else 'the model pool answered with nothing usable'),
                counts=not (isinstance(res, dict)
                            and (res.get('transient') or res.get('deferred'))))
            return None
        scenes = sanitize_script(res.get('scenes') or [], origin)
        if not scenes:
            _record_attempt(program['id'], slot, origin, source_url,
                            'Nothing in the script the model wrote survived '
                            'the screens.')
            return None
        return storage.upsert_program_lesson(program['id'], slot, {
            'origin': origin, 'source_url': source_url, 'scenes': scenes,
            'model': res.get('_model') or ''}) or None
    except deletion.Cancelled:
        raise
    except Exception as e:
        print(f"[lessons] generate failed for "
              f"{(program or {}).get('id')}: {e}")
        return None


# --- the nightly sweep, and the forced one --------------------------------
# generate_for is a single slot; generate_due is what actually runs, once a
# day, with nobody watching -- "a lesson generates itself" (Task 9) is only
# half a feature until something calls it, exactly once, not once per
# 30-second tick forever. sweep_report runs the identical scan on demand
# and NAMES what it did: a person who just changed generation code cannot
# wait for tonight to see what it does now.

def _windows_to_scan(now, start_offset: int, days: int):
    """(program row, window, unit) for every practice window the scan
    reaches -- `start_offset` days from `now` through `days` more.

    The walk generate_due and sweep_report both need: which programs are
    active, which windows practice_windows hands back for the date range,
    and which unit each window's program currently sits on. Factored into
    one place so a change to how any of that resolves can never drift
    between the nightly sweep and the forced one. What is deliberately NOT
    shared here is the day-marker/settings gate around this walk -- that
    stays in each caller, because sweep_report's whole reason to exist is
    that `force` may skip the marker where generate_due never does; see
    `_lessons_switched_on` for the half of the gate that IS shared.
    """
    import datetime
    from services import storage, programs
    start = now.date() + datetime.timedelta(days=start_offset)
    rows = {r['id']: programs.load(r) for r in storage.get_programs(state='active')}
    for w in programs._practice_windows(
            start, start + datetime.timedelta(days=days)):
        row = rows.get(w.get('program_id'))
        if not row or row.get('unresolved'):
            continue
        phase = programs.progress(row).get('phase') or {}
        unit = programs.unit_for(row, phase) or {}
        yield row, w, unit


def _lessons_switched_on(settings: dict) -> bool:
    """Both switches a real pass must clear, asked in one place --
    generate_due's own two `if not settings.get(...): return` reads, so a
    forced call from sweep_report can never silently outrun a switch
    generate_due still honors."""
    return bool(settings.get('programs_enabled', True)
               and settings.get('program_lessons_enabled', True))


def generate_due(now=None, limit: int = MAX_SLOTS_PER_PASS,
                 start_offset: int = 1) -> int:
    """Tomorrow's lessons, written tonight. Called blindly from the 300s
    loop (main.py's `poll_schedule`, the one that already owns slow work)
    and self-throttled to one real pass per day, so a restart never
    double-spends and idle cost is one app_state read.

    Bounded per pass, not merely per day. Every slot this reaches is up to
    four pool candidates at `gemma_timeout_s=180`, so an unbounded pass is
    an unbounded stall -- and the realistic bad case is not midnight but a
    morning: the marker is date-based, so an app that was down overnight
    and comes up at 07:00 runs the WHOLE sweep in the school-run window.
    `limit` counts slots that would actually spend a call (`needs_lesson`),
    never slots that were only ever going to be skipped, so the cap is a
    cap on cost. The remainder is absorbed by the two-day lookahead below:
    a slot passed over tonight is seen again tomorrow, before the evening
    it is needed.

    The day-marker check comes FIRST, ahead of both settings reads --
    self-throttling is the whole point of a function a 30s loop calls
    unconditionally forever, the same traffic-sweep shape
    maps.run_day_of_traffic_sweep already uses one block up in that loop.
    Neither settings check sets the marker: only a real pass earns it, so
    flipping a switch back on later gets tonight's sweep rather than
    waiting out a day a disabled sweep never actually ran.

    The scan itself reaches two days out, not one -- practice_windows(
    tomorrow, tomorrow+2d), exactly the design's Generation pipeline
    section -- so a slot due the evening after tomorrow is already
    visible tonight AND again tomorrow night, before the evening it is
    actually needed: a night this sweep fails or a program's page is
    unreachable still leaves a second chance rather than a silently blank
    session. The extra day is nearly free -- generate_for bails on a slot
    that already has a lesson before any page fetch or model call, so a
    slot re-seen on its second night costs one storage read and nothing
    else.

    `start_offset` exists for `sweep_report` below and nothing else: it
    moves where "tomorrow" starts without touching what the scan means.
    The default (1) reproduces the paragraph above exactly -- tomorrow
    through tomorrow+2d -- so every existing caller, and every scenario
    already pinned to that scan, is untouched. The 300s loop never passes
    it.

    Apart from deletion.Cancelled, never raises -- as with every
    function in this module follows. `generate_for` already promises that
    per slot, but the settings reads, `practice_windows` and
    `storage.get_programs` do not promise it of themselves, and three
    scenarios in tests/test_program_lessons.py call this function
    directly with no wrapper of their own -- unlike main.py's 30s loop,
    which guards its call the same way it guards the two sweep blocks
    beside it, but must not be the ONLY thing standing between a bad row
    and a raw traceback out of a function whose own docstring promises
    otherwise.
    """
    import datetime
    from services import storage
    now = now or datetime.datetime.now()
    marker = now.date().isoformat()
    if (storage.get_app_state('program_lessons_swept') or '') == marker:
        return 0
    try:
        settings = storage.get_settings() or {}
        if not _lessons_switched_on(settings):
            return 0
        storage.set_app_state('program_lessons_swept', marker)
        from services import library_scripts
        wrote = library_scripts.retry_due(now, limit)
        # unconverted runs keep the legacy branch
        spent = 0
        for row, w, unit in _windows_to_scan(now, start_offset, 2):
            if row.get('library_id'):
                continue
            slot = slot_of(w, unit_n=int((unit or {}).get('n') or 0))
            if not needs_lesson(row['id'], slot):
                continue
            if spent >= max(0, int(limit or 0)):
                break
            spent += 1
            if generate_for(row, w, unit, settings):
                wrote += 1
        return wrote
    except deletion.Cancelled:
        raise
    except Exception as e:
        print(f"[lessons] sweep failed: {e}")
        return 0
