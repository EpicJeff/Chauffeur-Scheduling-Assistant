"""Stages — the child that grows (load arc A4).

`role == 'child'` was the entire model. There was no birthdate, age or grade
field anywhere, and nothing in the codebase branched on a child's age, so a
six-year-old and a sixteen-year-old got the identical 64px-glyph card, the
identical "Hi James! 👋", the identical points economy and the identical tone.
The only exit was a manual role flip to `adult`, which deleted the kid lens in
one move.

Four stages, named for **what changes** rather than for how old you are, and
mapped to the shape a family already thinks in — preschool, elementary,
middle, high school:

    Sprout      < 6     pre-reader. Glyph- and photo-led, today only.
    Explorer    6–11    reads, checks off; points and streaks land honestly.
    Navigator   12–14   points start to read as babyish; wants to be trusted.
    Copilot     15+     a real schedule, own commitments, driving.

**The bands are configurable**, because school systems differ: US middle
school usually starts at 11-turning-12, so a fixed 12 would put a sixth
grader in the wrong stage for half the year. They are stored as three
CUTOFFS rather than four ranges — contiguous bands defined by cutoffs cannot
develop gaps or overlaps the way four independently edited ranges can.

Two rules govern movement between them:

  **Growing up is granted, never silently switched.** A stage change is
  announced and parent-confirmed, and the new capabilities are named out
  loud. Earned, rather than the app quietly getting different.

  **Nothing is deleted when a child moves up.** Points history, streaks and
  tier badges are retained — they are simply no longer the point. Growing up
  erasing the evidence that you were ever six is the opposite of what a
  family wants.
"""
import datetime

from services import storage

# Ordered youngest first. `key` is what surfaces read; `school` is only ever
# shown to a parent choosing the bands, so the vocabulary of independence
# stays primary and the school mapping stays a hint.
STAGES = [
    {'key': 'sprout',    'label': 'Sprout',    'school': 'preschool',     'glyph': '🌱'},
    {'key': 'explorer',  'label': 'Explorer',  'school': 'elementary',    'glyph': '🔍'},
    {'key': 'navigator', 'label': 'Navigator', 'school': 'middle school', 'glyph': '🧭'},
    {'key': 'copilot',   'label': 'Copilot',   'school': 'high school',   'glyph': '🚗'},
]
STAGE_KEYS = [s['key'] for s in STAGES]
DEFAULT_CUTOFFS = [6, 12, 15]

# What each stage turns on. Deliberately a small, explicit switch list, so no
# surface ever has to know a birthday — they ask for a capability by name.
CAPABILITIES = {
    'sprout': {
        'glyph_scale': 'xl', 'density': 'roomy', 'horizon_days': 0,
        'show_points': True, 'show_streaks': False, 'can_request': False,
        'assignable_tasks': False, 'can_drive': False, 'private_location': False,
    },
    'explorer': {
        'glyph_scale': 'lg', 'density': 'roomy', 'horizon_days': 6,
        'show_points': True, 'show_streaks': True, 'can_request': True,
        'assignable_tasks': False, 'can_drive': False, 'private_location': False,
    },
    'navigator': {
        'glyph_scale': 'sm', 'density': 'tight', 'horizon_days': 13,
        # Points do not vanish — the LEDGER is kept forever (nothing is
        # deleted when a child moves up); they simply stop leading the screen,
        # because at twelve they start to read as babyish.
        'show_points': False, 'show_streaks': False, 'can_request': True,
        'assignable_tasks': True, 'can_drive': False, 'private_location': True,
    },
    'copilot': {
        'glyph_scale': 'none', 'density': 'tight', 'horizon_days': 13,
        'show_points': False, 'show_streaks': False, 'can_request': True,
        'assignable_tasks': True, 'can_drive': True, 'private_location': True,
    },
}

# Said out loud when a child moves up, because growing up is GRANTED. Each
# line names the thing that is new in the words a family would use.
GRANTS = {
    'explorer': ["their own streaks", "a week of the schedule instead of just today",
                 "asking a parent for something"],
    'navigator': ["two weeks of the schedule", "being given real household jobs",
                  "keeping their whereabouts to the family rather than the kiosk"],
    'copilot': ["driving, once you set them up as a driver",
                "their own errands and commitments"],
}


def cutoffs() -> list:
    """The three ages where the bands change. Sanitised hard: a family can
    type anything into a settings box, and a non-increasing list would make
    a band unreachable rather than just odd."""
    raw = (storage.get_settings() or {}).get('stage_cutoffs')
    if not isinstance(raw, (list, tuple)) or len(raw) != 3:
        return list(DEFAULT_CUTOFFS)
    out = []
    for i, v in enumerate(raw):
        try:
            out.append(int(v))
        except (TypeError, ValueError):
            return list(DEFAULT_CUTOFFS)
    if not (0 < out[0] < out[1] < out[2] < 25):
        return list(DEFAULT_CUTOFFS)
    return out


def age_of(member: dict, on: datetime.date = None):
    """Whole years, or None when no birthdate is set — and None is a real
    answer that callers must handle, not a zero."""
    bd = (member or {}).get('birthdate')
    if not bd:
        return None
    try:
        b = datetime.date.fromisoformat(str(bd)[:10])
    except ValueError:
        return None
    on = on or datetime.date.today()
    return on.year - b.year - ((on.month, on.day) < (b.month, b.day))


def stage_for_age(age) -> str:
    if age is None:
        return 'explorer'      # the safe middle: reads, but nothing is assumed
    c = cutoffs()
    if age < c[0]:
        return 'sprout'
    if age < c[1]:
        return 'explorer'
    if age < c[2]:
        return 'navigator'
    return 'copilot'


def suggested_stage(member: dict) -> str:
    return stage_for_age(age_of(member))


def stage_of(member: dict) -> str:
    """The stage a child is ACTUALLY in.

    A pinned stage always wins. Birthdate only ever SUGGESTS — kids differ,
    and a single number should not be destiny, which is also how the
    mid-cohort birthday problem is meant to be solved (pin the child whose
    birthday falls in the wrong half of the school year).
    """
    if not member or member.get('role') != 'child':
        return None
    pinned = member.get('stage_override')
    if pinned in STAGE_KEYS:
        return pinned
    return suggested_stage(member)


def capabilities(member: dict) -> dict:
    """The switch list for this child, with per-capability overrides applied.

    Per-capability overrides are why the stage is a BUNDLE and not a verdict:
    a mature eleven-year-old can hold request rights without being aged up
    wholesale.
    """
    st = stage_of(member)
    if not st:
        return {}
    caps = dict(CAPABILITIES.get(st) or CAPABILITIES['explorer'])
    for k, v in (member.get('capability_overrides') or {}).items():
        if k in caps:
            caps[k] = v
    caps['stage'] = st
    caps['stage_label'] = next((s['label'] for s in STAGES if s['key'] == st), st)
    return caps


def can(member: dict, capability: str) -> bool:
    """Ask for a capability by name. Adults are not staged and simply can."""
    if not member or member.get('role') != 'child':
        return True
    return bool(capabilities(member).get(capability))


def pending_promotions(today: datetime.date = None) -> list:
    """Children whose age has moved past their current stage.

    Returned rather than applied: the transition is a MOMENT — announced and
    parent-confirmed, with the new capabilities named — not a config value
    that silently changes one morning.
    """
    today = today or datetime.date.today()
    out = []
    for m in storage.get_all_members():
        if m.get('role') != 'child' or m.get('stage_override'):
            continue
        age = age_of(m, today)
        if age is None:
            continue
        want = stage_for_age(age)
        have = m.get('stage_acknowledged') or 'sprout' if age is not None else None
        if want != have and STAGE_KEYS.index(want) > STAGE_KEYS.index(have or 'sprout'):
            out.append({'member_id': m['id'], 'name': m.get('name'),
                        'from': have or 'sprout', 'to': want, 'age': age,
                        'grants': GRANTS.get(want, [])})
    return out


def acknowledge(member_id: str, stage: str = None) -> dict:
    """A parent confirms the move. Nothing is deleted — the points ledger,
    streaks and tier badges stay exactly where they are; they simply stop
    leading the screen."""
    m = storage.get_member(member_id)
    if not m or m.get('role') != 'child':
        return {'status': 'error', 'message': 'Not a child member.'}
    target = stage if stage in STAGE_KEYS else suggested_stage(m)
    storage.update_member(member_id, {'stage_acknowledged': target})
    label = next((s['label'] for s in STAGES if s['key'] == target), target)
    return {'status': 'success', 'stage': target,
            'message': f"{m.get('name')} is a {label} now.",
            'grants': GRANTS.get(target, [])}
