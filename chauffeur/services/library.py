"""The household's public curricula, separate from each person's run."""
import copy
import uuid

from services import access, storage

EDIT_REFUSAL = 'Only the person who made this program, or a parent, can change it.'


def can_edit(row, viewer):
    return bool(row and viewer and viewer.get('id') and
                viewer.get('status', 'active') == 'active' and
                (viewer.get('role') == 'parent' or
                 (viewer.get('role') == 'adult' and row.get('created_by') == viewer['id'])))


def valid_curriculum(row):
    """Reject a damaged document as a whole; never serve half a curriculum."""
    if not isinstance(row, dict):
        return False
    if (not isinstance(row.get('title'), str) or not row['title'].strip()
            or not isinstance(row.get('source', {}), dict)
            or not isinstance(row.get('made_for', {}), dict)):
        return False
    phases, lessons = row.get('phases'), row.get('lessons')
    if not isinstance(phases, list) or not isinstance(lessons, list):
        return False
    try:
        phase_ids = [p['id'] for p in phases]
        lesson_ids = [l['id'] for l in lessons]
        if (not all(isinstance(i, str) and i for i in phase_ids + lesson_ids)
                or len(set(phase_ids)) != len(phases) or len(set(lesson_ids)) != len(lessons)):
            return False
        for ph in phases:
            if int(ph.get('weeks') or 1) < 1 or not isinstance(ph.get('steps', []), list):
                return False
        for lesson in lessons:
            if (lesson['phase_id'] not in phase_ids or int(lesson.get('sessions') or 1) < 1
                    or not isinstance(lesson.get('steps', []), list)
                    or not isinstance(lesson.get('variants', []), list)):
                return False
            for variant in lesson.get('variants', []):
                if not isinstance(variant, dict) or not isinstance(variant.get('steps', []), list):
                    return False
        return all(any(l['phase_id'] == pid for l in lessons) for pid in phase_ids)
    except (KeyError, TypeError, ValueError):
        return False


def from_curated(title, profile, curated, created_by):
    """Mint identities once: one lesson per rung, rotation inside that lesson."""
    phases, lessons = [], []
    for raw in curated.get('phases') or []:
        phase = {k: copy.deepcopy(v) for k, v in raw.items()
                 if k not in ('id', 'units', 'unit_shift', 'milestone_hit_at')}
        phase['id'] = uuid.uuid4().hex
        phase.setdefault('weeks', 1)
        phases.append(phase)
        units = raw.get('units') or [{'title': raw.get('name') or title, 'sessions': 1}]
        for unit in units:
            lessons.append({
                'id': uuid.uuid4().hex, 'phase_id': phase['id'],
                'title': unit.get('title') or raw.get('name') or title,
                'sessions': max(1, int(unit.get('sessions') or 1)),
                'steps': copy.deepcopy(unit.get('steps', raw.get('steps') or [])),
                **{k: unit[k] for k in ('body', 'url') if unit.get(k)},
                'variants': copy.deepcopy([v for v in raw.get('rotation') or []
                                           if isinstance(v, dict) and v.get('steps')])})
    return {'title': title, 'made_for': profile, 'created_by': created_by,
            'phases': phases, 'lessons': lessons, 'source': curated.get('source') or {}}


def public_profile(fields):
    from services import programs, stages
    shape = programs.clamp_shape(fields)
    band = fields.get('age_band') or 'any'
    if band not in ['any'] + stages.STAGE_KEYS:
        raise ValueError('Choose an age band.')
    return {'age_band': band, 'minutes': shape['minutes'],
            'sessions_per_week': shape['sessions_per_week'],
            'assumes': str(fields.get('assumes') or '').strip()}


def create(fields, actor):
    from services import programs_curate
    if not actor or actor.get('role') not in ('adult', 'parent') or actor.get('status', 'active') != 'active':
        return {'status': 'error', 'code': 403, 'message': 'An adult or a parent can make a library program.'}
    title = str(fields.get('title') or '').strip()
    for screen in (programs_curate.screen_aim(title),
                   programs_curate.screen_starting_point(str(fields.get('assumes') or ''))):
        if not screen.get('ok'):
            return {'status': 'error', **{k: screen[k] for k in ('message', 'alternatives') if k in screen}}
    try:
        profile = public_profile(fields)
    except ValueError as exc:
        return {'status': 'error', 'message': str(exc)}
    curated = programs_curate.curate(title, profile, **({'exclude_books': True} if fields.get('exclude_books') else {}))
    row = from_curated(title, profile, curated, actor['id'])
    lid = storage.add_library_program(row)
    _invalidate()
    return {'status': 'success', 'program': storage.get_library_program(lid),
            'message': f'Everyone in the household will see this program as: {title}'}


def runners(library_id, viewer):
    """Project visibility and record visibility both apply to a named runner."""
    named, hidden = [], 0
    with access.batch():
        for run in storage.get_programs(include_finished=True):
            if run.get('library_id') != library_id or access.gone('program', run):
                continue
            project = storage.get_project(run.get('project_id'))
            # A household runner's public identity is visible on this shared
            # surface even to a helper or sibling who cannot open the run.
            projection = access.record_view('program', run, viewer) or access.record_view('program', run, access.HOUSE)
            if project and access.project_visible(project, viewer) and projection:
                member = storage.get_member(run.get('member_id')) or {}
                named.append({'name': member.get('name') or '', 'project_id': project['id'],
                              'project_title': project.get('title') or ''})
            else:
                hidden += 1
    return {'named': named, 'hidden': hidden}


def get(library_id, viewer):
    row = storage.get_library_program(library_id)
    return {**row, 'runners': runners(library_id, viewer)} if row else None


def list_programs(viewer, include_archived=True):
    return [{**r, 'runners': runners(r['id'], viewer)} for r in storage.get_library_programs()
            if include_archived or not r.get('archived')]


def _invalidate():
    from services import home_board
    home_board._ACCESS_DIGEST.clear()
    home_board.invalidate_cache()


def _write(library_id, actor, change):
    from services import programs
    with storage.db_lock, storage.db.transaction():
        before = storage.get_library_program(library_id)
        if not before:
            return {'status': 'error', 'code': 404, 'message': 'No such library program.'}
        if not can_edit(before, actor):
            return {'status': 'error', 'code': 403, 'message': EDIT_REFUSAL}
        row = copy.deepcopy(before)
        try:
            change(row)
            if not valid_curriculum(row):
                raise ValueError('Every phase needs a lesson, with a valid phase and session count.')
        except ValueError as exc:
            return {'status': 'error', 'message': str(exc)}
        storage.update_library_program(library_id, row)
        for run in storage.get_programs(include_finished=True):
            if run.get('library_id') == library_id and not access.gone('program', run):
                progress = programs.reconcile_progress(run, row, before)
                if progress != run.get('progress'):
                    storage.update_program(run['id'], {'progress': progress})
    _invalidate()
    return {'status': 'success', 'program': storage.get_library_program(library_id)}


def update(library_id, fields, actor):
    from services import programs_curate
    def change(row):
        if 'title' in fields:
            screen = programs_curate.screen_aim(str(fields['title']).strip())
            if not screen.get('ok'):
                raise ValueError(screen['message'])
            row['title'] = str(fields['title']).strip()
        if 'made_for' in fields:
            profile = public_profile(fields['made_for'])
            screen = programs_curate.screen_starting_point(profile['assumes'])
            if not screen.get('ok'):
                raise ValueError(screen['message'])
            row['made_for'] = profile
    return _write(library_id, actor, change)


def archive(library_id, actor):
    return _write(library_id, actor, lambda row: row.update(archived=True))


def add_lesson(library_id, fields, actor):
    def change(row):
        row['lessons'].append({'id': uuid.uuid4().hex, 'steps': [], 'variants': [], 'sessions': 1,
                               **{k: v for k, v in fields.items() if k in
                                  ('phase_id', 'title', 'sessions', 'steps', 'variants', 'body', 'url')}})
    return _write(library_id, actor, change)


def update_lesson(library_id, lesson_id, fields, actor):
    def change(row):
        lesson = next((l for l in row['lessons'] if l['id'] == lesson_id), None)
        if lesson is None:
            raise ValueError('No such lesson.')
        lesson.update({k: v for k, v in fields.items() if k in
                       ('title', 'sessions', 'steps', 'variants', 'body', 'url')})
    return _write(library_id, actor, change)


def remove_lesson(library_id, lesson_id, actor):
    def change(row):
        if not any(l['id'] == lesson_id for l in row['lessons']):
            raise ValueError('No such lesson.')
        row['lessons'] = [l for l in row['lessons'] if l['id'] != lesson_id]
    return _write(library_id, actor, change)


def order_lessons(library_id, ids, actor):
    def change(row):
        by_id = {l['id']: l for l in row['lessons']}
        if len(ids) != len(by_id) or set(ids) != set(by_id):
            raise ValueError('Choose every lesson once.')
        row['lessons'] = [by_id[lid] for lid in ids]
    return _write(library_id, actor, change)


def delete(library_id, actor):
    with storage.db_lock, storage.db.transaction():
        row = storage.get_library_program(library_id)
        if not row:
            return {'status': 'error', 'code': 404, 'message': 'No such library program.'}
        if not can_edit(row, actor):
            return {'status': 'error', 'code': 403, 'message': EDIT_REFUSAL}
        if any(r.get('library_id') == library_id for r in storage.get_programs(include_finished=True)):
            visible = runners(library_id, actor)['named']
            names = ', '.join(dict.fromkeys(n['name'] for n in visible))
            return {'status': 'error', 'message': f"In use by {names}'s project" if names else 'In use by another project'}
        storage.delete_library_program(library_id)
    _invalidate()
    return {'status': 'success'}
