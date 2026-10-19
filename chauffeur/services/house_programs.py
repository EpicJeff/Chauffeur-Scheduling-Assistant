"""A family's active programs become objects, never a copy of private records."""
import datetime
import re
from services import storage, programs, stages, access


def appearance(row):
    row = programs.load(row) if row.get('id') or row.get('library_id') else row
    # Deliberately use the named aim, not private starting-point notes or
    # inferred health/body characteristics. Unknown aims keep the program book.
    title = str(row.get('title') or '').lower()
    for kind, pattern in (
        ('guitar', r'\b(guitar|ukulele|bass guitar)\b'),
        ('piano', r'\b(piano|keyboard)\b'),
        ('meditation', r'\b(meditat\w*|mindfulness|zen)\b'),
        ('exercise', r'\b(workout|exercise|fitness|strength|weightlifting|treadmill|cycling)\b'),
    ):
        if re.search(pattern, title):
            return kind
    return 'book'


def objects(*, viewer=access.HOUSE):
    members = {m['id']: m for m in storage.get_all_members()}
    out = []
    for row in storage.get_programs(state='active'):
        if not access.shared_screen_visible('program', row, viewer):
            continue
        row = programs.load(row)
        unresolved = row.get('unresolved')
        member = members.get(row.get('member_id'))
        if not member:
            continue
        kind = 'book' if unresolved else appearance(row)
        out.append({'id': row['id'], 'kind': kind, 'title': '' if unresolved else row.get('title') or 'Practice',
                    'member_name': '' if unresolved else member.get('name') or '',
                    'color': member.get('color_code') or '#58978b',
                    'variant': 'electric' if kind == 'guitar' and 'electric' in row.get('title', '').lower() else 'acoustic'})
    return out


def session(program_id, now=None, *, viewer=access.HOUSE):
    """Today's session, or the current lesson for an unscheduled practice tap.

    Same family-safe material as practice_windows. Opening never writes a
    practice log, advances a unit, or exposes the stored program row.
    """
    now = now or datetime.datetime.now()
    row = programs.load(storage.get_program(program_id))
    if not row or row.get('state') != 'active' or not access.shared_screen_visible('program', row, viewer):
        return None
    member = storage.get_member(row.get('member_id'))
    if not member or member.get('archived'):
        return None
    # This shared-screen row already passed the HOUSE-or-person gate above.
    windows = [w for w in programs._practice_windows(now.date(), now.date(), member_id=member['id'])
               if w['program_id'] == program_id]
    if windows:
        upcoming = [w for w in windows if (w.get('time_end') or '') >= now.strftime('%H:%M') and not w.get('logged')]
        return (upcoming or windows)[0]
    phase = programs.progress(row).get('phase') or {}
    unit = programs.unit_for(row, phase) or {}
    projection = programs.lesson_for(row, now.date())
    return {'program_id': row['id'], 'member_id': member['id'],
            'member_name': '' if row.get('unresolved') else member.get('name') or '',
            'owner_practices_alone': bool(stages.capabilities(member).get('practices_alone', True)),
            **{k: projection[k] for k in ('lesson_id', 'variant_label') if k in projection},
            'title': 'Busy' if row.get('unresolved') else row.get('title') or 'Practice', 'date': now.date().isoformat(),
            'time_start': now.strftime('%H:%M'), 'time_end': '',
            'phase_name': phase.get('name') or '', 'unit_n': int(unit.get('n') or 0),
            'unit_title': projection.get('title', unit.get('title') or ''),
            'unit_url': projection.get('url', unit.get('url') or ''),
            'unit_body': projection.get('body', unit.get('body') or ''),
            'session_label': projection.get('variant_label') or '',
            'steps': projection.get('steps', list(phase.get('steps') or [])),
            'progression': phase.get('progression') or '', 'milestone': phase.get('milestone') or '',
            'logged': False}
