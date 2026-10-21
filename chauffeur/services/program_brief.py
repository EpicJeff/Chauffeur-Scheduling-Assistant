"""A plain-language brief becomes the curator's inputs (programs spec §1).

One model call on the free chain; every free-text field screened; the starting
point stays private to the run and never enters the public profile."""
import datetime

from services import model_pools, programs_curate, storage

SYSTEM = ("Read a family's description of a practice program and answer ONLY with JSON: "
          "{\"title\": short aim like 'Learn piano' or '', \"for\": a person's first name or '', \"minutes\": int or null, "
          "\"sessions_per_week\": int or null, \"assumes\": generic starting level like 'complete beginner' or '', "
          "\"starting_point\": what THIS person can already do, in their words, or '', \"preferred_days\": [0-6 weekday ints, 0 is Monday] or [], "
          "\"target_date\": 'YYYY-MM-DD' or '', \"based_on\": a named book, site or method or '', "
          "\"exclude_books\": true only if they said no books, \"notes\": anything else that should shape the plan or ''}. "
          "Leave title empty if no aim is stated. Never copy the starting point into assumes: assumes is public, "
          "the starting point is private to the person.")

DEFAULT_MINUTES = 20
DEFAULT_PER_WEEK = 3
# How much of each free-text field is kept. The public context caps notes again.
CAPS = {'title': 80, 'assumes': programs_curate.STARTING_POINT_CHARS,
        'starting_point': programs_curate.STARTING_POINT_CHARS, 'based_on': 120, 'notes': 400}
FIELD_NAMES = {'assumes': 'the starting level', 'based_on': 'what it is based on', 'notes': 'the notes'}
PUBLIC_FIELDS = ('assumes', 'notes', 'based_on')


def _text(raw, field):
    return str(raw.get(field) or '').strip()[:CAPS[field]]


def _int(value, default):
    try:
        return int(value) if value not in (None, '') else default
    except (TypeError, ValueError):
        return default


def _date(value):
    try:
        return datetime.date.fromisoformat(str(value or '').strip()[:10]).isoformat()
    except ValueError:
        return None


def screen_fields(fields):
    """The aim's screen on the title and the starting point's on every other
    free-text field; a refusal names the field (spec §1). None when all pass."""
    for field in ('title', 'assumes', 'starting_point', 'based_on', 'notes'):
        value = str((fields or {}).get(field) or '').strip()
        if not value:
            continue
        screen = (programs_curate.screen_aim(value) if field == 'title'
                  else programs_curate.screen_starting_point(value))
        if screen.get('ok'):
            continue
        message = screen['message']
        if field in FIELD_NAMES:
            message = (f"Same rule for {FIELD_NAMES[field]} as for the aim: no target weights "
                       f"and no calorie numbers.")
        return {'status': 'error', 'message': message,
                **({'alternatives': screen['alternatives']} if screen.get('alternatives') else {})}
    return None


def parse(text, actor, members, *, surface='library'):
    """{'status': 'success', 'brief': {...}} or a refusal (spec §1, P6).

    `surface` is 'chat' or 'library': a brief that names nobody is the
    speaker's in chat and nobody's on the Library page."""
    text = str(text or '').strip()
    if not text:
        return {'status': 'error', 'message': 'Say what the program is for.'}
    settings = storage.get_settings() or {}
    raw = model_pools.call_pool_json('interactive', settings.get('llm_gemini_api_key', ''), SYSTEM, text,
                                     timeout_s=45, settings=settings, paid_ok=False)
    if not isinstance(raw, dict) or raw.get('error'):
        return {'status': 'error', 'message': "Couldn't read that just now. Try again, or fill it in by hand."}
    fields = {f: _text(raw, f) for f in CAPS}
    if not fields['title']:
        return {'status': 'error', 'message': "Say what the aim is (for example 'learn piano' or 'train for a 5K')."}
    refusal = screen_fields(fields)
    if refusal:
        return refusal
    # The starting point is private to the run; a public field that repeats it
    # (assumes, notes, based_on all reach the public context) is dropped, never
    # refused, so the public stays generic and the brief still goes through.
    starting = fields['starting_point']
    if starting:
        for field in PUBLIC_FIELDS:
            if starting.lower() in fields[field].lower():
                fields[field] = ''
    assumes = fields['assumes']
    name = str(raw.get('for') or '').strip().lower()
    member = next((m for m in members or [] if name and str(m.get('name') or '').strip().lower().startswith(name)), None)
    if member is None and surface == 'chat':
        if name:
            return {'status': 'error', 'message': f"I couldn't find {raw.get('for')} in the household."}
        member = actor
    from services import library
    try:
        profile = library.public_profile({
            'age_band': library.band_for(member) if member else 'any',
            'minutes': _int(raw.get('minutes'), DEFAULT_MINUTES),
            'sessions_per_week': _int(raw.get('sessions_per_week'), DEFAULT_PER_WEEK),
            'assumes': assumes})
    except ValueError as e:
        return {'status': 'error', 'message': str(e)}
    days = []
    for d in raw.get('preferred_days') if isinstance(raw.get('preferred_days'), list) else []:
        d = _int(d, None)
        if d is not None and 0 <= d <= 6 and d not in days:
            days.append(d)
    return {'status': 'success', 'brief': {
        'title': fields['title'], 'for_member_id': (member or {}).get('id'), 'profile': profile,
        'starting_point': starting, 'preferred_days': days,
        'target_date': _date(raw.get('target_date')),
        'based_on': fields['based_on'], 'exclude_books': raw.get('exclude_books') is True,
        'notes': fields['notes']}}
