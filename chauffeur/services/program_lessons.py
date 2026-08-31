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
