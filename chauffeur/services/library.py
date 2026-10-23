"""The household's public curricula, separate from each person's run."""
import copy
import uuid

from services import access, storage

EDIT_REFUSAL = 'Only the person who made this program, or a parent, can change it.'
LIVE_RUN_STATES = ('proposed', 'active', 'paused')


def age_bands():
    """The bands a public profile names, worded once for every surface."""
    from services import stages
    cut = stages.cutoffs()
    return [{'key': 'any', 'label': 'all ages'},
            {'key': 'sprout', 'label': f'ages 0–{cut[0] - 1}'},
            {'key': 'explorer', 'label': f'ages {cut[0]}–{cut[1] - 1}'},
            {'key': 'navigator', 'label': f'ages {cut[1]}–{cut[2] - 1}'},
            {'key': 'copilot', 'label': f'ages {cut[2]} and up'}]


def made_for_line(profile):
    """"ages 7–10 with 20-minute sessions": Argyle's choice card and the library cards."""
    profile = profile or {}
    labels = {b['key']: b['label'] for b in age_bands()}
    return f"{labels.get(profile.get('age_band'), 'all ages')} with {profile.get('minutes', 25)}-minute sessions"


def band_for(member):
    """The age band a new profile starts on: the birthdate's stage, else any.
    Never a pinned UI stage (spec §1)."""
    from services import stages
    age = stages.age_of(member or {})
    return stages.stage_for_age(age) if age is not None else 'any'


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
                    or not isinstance(lesson.get('variants', []), list)
                    or not isinstance(lesson.get('summary', ''), str)
                    or lesson.get('origin', 'none') not in ('cited', 'generated', 'none')):
                return False
            for variant in lesson.get('variants', []):
                if not isinstance(variant, dict) or not isinstance(variant.get('steps', []), list):
                    return False
        return all(any(l['phase_id'] == pid for l in lessons) for pid in phase_ids)
    except (KeyError, TypeError, ValueError, OverflowError):
        return False


def default_summary(steps, sessions):
    """The same parent-facing fallback at creation, hand entry and migration."""
    first = str((steps or [''])[0] or '').strip().rstrip('.')
    count = max(1, int(sessions or 1))
    return (first + '. ' if first else '') + f"{count} session{'s' if count != 1 else ''}."


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
            sessions = max(1, int(unit.get('sessions') or 1))
            steps = copy.deepcopy(unit.get('steps', raw.get('steps') or []))
            summary = default_summary(steps, sessions)
            lessons.append({
                'id': uuid.uuid4().hex, 'phase_id': phase['id'],
                'title': unit.get('title') or raw.get('name') or title,
                'sessions': sessions,
                'steps': steps,
                'summary': unit.get('summary') or summary,
                'origin': unit.get('origin') or (curated.get('source') or {}).get('origin') or 'none',
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


def create_refusal(actor):
    """Who may publish a library program: an active adult or parent. None, or the refusal."""
    if not actor or actor.get('role') not in ('adult', 'parent') or actor.get('status', 'active') != 'active':
        return {'status': 'error', 'code': 403, 'message': 'An adult or a parent can make a library program.'}
    return None


def prepare(fields, actor):
    """Curate public content without a write lock; callers publish atomically.

    A brief's `notes` and `based_on` (programs spec §1) are screened like the
    title and reach the curator's public context; they are not stored."""
    from services import programs_curate, program_brief
    refusal = create_refusal(actor)
    if refusal:
        return refusal
    title = str(fields.get('title') or '').strip()
    if not title:
        screen = programs_curate.screen_aim(title)
        return {'status': 'error', **{k: screen[k] for k in ('message', 'alternatives') if k in screen}}
    refusal = program_brief.screen_fields({k: fields.get(k) for k in ('title', 'assumes', 'based_on', 'notes')})
    if refusal:
        return refusal
    try:
        profile = public_profile(fields)
    except ValueError as exc:
        return {'status': 'error', 'message': str(exc)}
    brief = {k: str(fields.get(k) or '').strip() for k in ('notes', 'based_on')}
    curated = programs_curate.curate(title, profile, **({'exclude_books': True} if fields.get('exclude_books') else {}),
                                     **({'brief': brief} if any(brief.values()) else {}))
    row = from_curated(title, profile, curated, actor['id'])
    return {'status': 'success', 'program': row,
            'message': f'Everyone in the household will see this program as: {title}'}


def create(fields, actor):
    prepared = prepare(fields, actor)
    if prepared.get('status') != 'success':
        return prepared
    lid = storage.add_library_program(prepared['program'])
    from services import library_scripts
    library_scripts.write(lid, actor)
    _invalidate()
    return {'status': 'success', 'program': storage.get_library_program(lid),
            'message': prepared['message']}


def runners(library_id, viewer):
    """Project visibility and record visibility both apply to a named runner."""
    named, hidden, hidden_on = [], 0, {}
    with access.batch():
        for run in storage.get_programs(include_finished=True):
            if run.get('library_id') != library_id or access.gone('program', run):
                continue
            project = storage.get_project(run.get('project_id'))
            # A household runner's public identity is visible on this shared
            # surface even to a helper or sibling who cannot open the run.
            projection = access.record_view('program', run, viewer) or access.record_view('program', run, access.HOUSE)
            # Which lesson a live run sits on: what Remove has to warn about.
            current = ((run.get('progress') or {}).get('current')
                       if run.get('state') in LIVE_RUN_STATES else None)
            if project and access.project_visible(project, viewer) and projection:
                member = storage.get_member(run.get('member_id')) or {}
                named.append({'name': member.get('name') or '', 'run_id': run['id'], 'project_id': project['id'],
                              'project_title': project.get('title') or '', 'current': current})
            else:
                hidden += 1
                if current:
                    hidden_on[current] = hidden_on.get(current, 0) + 1
    return {'named': named, 'hidden': hidden, 'hidden_on': hidden_on}


def in_use_message(library_id, viewer):
    """Delete's refusal while any non-gone run references the program, else ''."""
    if not any(r.get('library_id') == library_id and not access.gone('program', r)
               for r in storage.get_programs(include_finished=True)):
        return ''
    visible = runners(library_id, viewer)['named']
    names = ', '.join(dict.fromkeys(n['name'] for n in visible))
    return f"In use by {names}'s project" if names else 'In use by another project'


def _script_view(row):
    from services import library_scripts
    scripts = {}
    by_slot = {(s['lesson_id'], s['variant_label']): s for s in storage.get_library_scripts(row['id'])}
    job = library_scripts.job_state(row['id'])
    for lesson, label in library_scripts.slots_of(row):
        s = by_slot.get((lesson['id'], label)) or {}
        if job and job.get('lesson_id') == lesson['id'] and (job.get('variant_label') or '') == label:
            state = 'writing'
        elif s.get('scenes'):
            state = 'ready'
        elif s.get('attempts') or s.get('note'):
            state = 'failed'
        else:
            state = 'none'
        # `short`: the stored script ran under the shortfall rule, as the
        # writer recorded it ("runs about N minutes of M", library_scripts),
        # never recomputed here. The course page says "shorter than asked".
        short = bool(s.get('scenes')) and str(s.get('note') or '').startswith('runs about ')
        scripts.setdefault(lesson['id'], {})[label] = {'state': state, 'minutes': int(s.get('minutes') or 0), 'note': s.get('note') or '',
                                                        'origin': s.get('origin') or '', 'edited': bool(s.get('edited')), 'stale': bool(s.get('stale')),
                                                        'short': short, 'budget': int(s.get('budget') or 0),
                                                        'outdated': bool(s.get('scenes')) and not s.get('edited') and bool(s.get('budget'))
                                                        and int(s['budget']) != int((row.get('made_for') or {}).get('minutes') or 25)}
    return scripts, job


def source_line(row):
    source = row.get('source') or {}
    if source.get('origin') == 'cited':
        line = f"Based on {source.get('plan_name') or 'a published plan'} · cited"
        changed = sum(l.get('origin') == 'generated' for l in row.get('lessons') or [])
        if changed:
            line += f" · {changed} lesson{'s' if changed != 1 else ''} changed by the app"
        return line
    return 'Made by the app' if source.get('origin') == 'generated' else 'Practice time only'


def _view(row, viewer):
    """A library row as one viewer reads it: runners filtered, and what they may do."""
    scripts, job = _script_view(row)
    return {**row, 'scripts': scripts, 'writing': job, 'runners': runners(row['id'], viewer), 'can_edit': can_edit(row, viewer),
            'made_for_line': made_for_line(row.get('made_for')), 'source_line': source_line(row),
            'in_use': in_use_message(row['id'], viewer)}


def get(library_id, viewer):
    row = storage.get_library_program(library_id)
    return _view(row, viewer) if row else None


def list_programs(viewer, include_archived=True):
    return [_view(r, viewer) for r in storage.get_library_programs()
            if include_archived or not r.get('archived')]


def _invalidate():
    from services import home_board
    home_board._ACCESS_DIGEST.clear()
    home_board.invalidate_cache()


def _commit(library_id, candidate_row, actor, *, expect_revision=None):
    """Validate and publish one curriculum, reconciling its runs atomically."""
    from services import programs
    with storage.db_lock, storage.db.transaction():
        before = storage.get_library_program(library_id)
        if not before:
            return {'status': 'error', 'code': 404, 'message': 'No such library program.'}
        if not can_edit(before, actor):
            return {'status': 'error', 'code': 403, 'message': EDIT_REFUSAL}
        if expect_revision is not None and int(before.get('revision') or 0) != int(expect_revision):
            return {'status': 'error', 'code': 409, 'message': 'The program changed; read it again.'}
        if before.get('archived') and candidate_row.get('archived') is not False:
            return {'status': 'error', 'message': 'This program is archived.'}
        row = copy.deepcopy(candidate_row)
        if not valid_curriculum(row):
            return {'status': 'error', 'message': 'Every phase needs a lesson, with a valid phase and session count.'}
        # The lesson length is the one profile field scripts are written against
        # (library_scripts budgets on it). When it moves, every generated script
        # records the length it was written for, so Write lessons picks it up
        # and the course says so; a hand edit is flagged, never rewritten.
        # Nothing is deleted or scheduled here: the old script keeps playing
        # until a person taps Write lessons.
        old_minutes = int((before.get('made_for') or {}).get('minutes') or 25)
        if old_minutes != int((row.get('made_for') or {}).get('minutes') or 25):
            for script in storage.get_library_scripts(library_id):
                slot = {'lesson_id': script['lesson_id'], 'variant_label': script['variant_label']}
                if script.get('edited'):
                    storage.mark_library_script_stale(library_id, slot, True)
                elif script.get('scenes') and not script.get('budget'):
                    storage.set_library_script_fields(library_id, slot, {'budget': old_minutes})
        row['revision'] = int(before.get('revision') or 0) + 1
        storage.update_library_program(library_id, row)
        for run in storage.get_programs(include_finished=True):
            if run.get('library_id') == library_id and not access.gone('program', run):
                progress = programs.reconcile_progress(run, row, before)
                if progress != run.get('progress'):
                    storage.update_program(run['id'], {'progress': progress})
        result = storage.get_library_program(library_id)
    _invalidate()
    return {'status': 'success', 'program': result}


def _write(library_id, actor, change):
    """Build hand edits under the lock so concurrent edits cannot lose a write."""
    with storage.db_lock, storage.db.transaction():
        row = storage.get_library_program(library_id)
        if not row:
            return {'status': 'error', 'code': 404, 'message': 'No such library program.'}
        if not can_edit(row, actor):
            return {'status': 'error', 'code': 403, 'message': EDIT_REFUSAL}
        row = copy.deepcopy(row)
        try:
            change(row)
        except (ValueError, TypeError, OverflowError) as exc:
            return {'status': 'error', 'message': str(exc)}
        return _commit(library_id, row, actor)


def _change_profile(row, fields):
    """Mutate one candidate; both hand and model callers publish it later."""
    from services import programs_curate
    if 'title' in fields:
        title = str(fields['title']).strip()
        screen = programs_curate.screen_aim(title)
        if not screen.get('ok'):
            raise ValueError(screen['message'])
        row['title'] = title
    if 'made_for' in fields:
        profile = public_profile(fields['made_for'])
        screen = programs_curate.screen_starting_point(profile['assumes'])
        if not screen.get('ok'):
            raise ValueError(screen['message'])
        row['made_for'] = profile


def _change_add_lesson(row, fields, after=None):
    if not any(p['id'] == fields.get('phase_id') for p in row['phases']):
        raise ValueError('No such phase.')
    lesson = {'id': uuid.uuid4().hex, 'steps': [], 'variants': [], 'sessions': 1,
              'summary': '', 'origin': (row.get('source') or {}).get('origin') or 'none',
              **{k: copy.deepcopy(v) for k, v in fields.items() if k in
                 ('phase_id', 'title', 'sessions', 'steps', 'variants', 'body', 'url', 'summary', 'origin', 'source_index')}}
    if not lesson['summary']:
        lesson['summary'] = default_summary(lesson['steps'], lesson['sessions'])
    if after is None:
        row['lessons'].append(lesson)
    else:
        index = next((i for i, l in enumerate(row['lessons'])
                      if l['id'] == after and l['phase_id'] == lesson.get('phase_id')), None)
        if index is None:
            raise ValueError('Choose a lesson in the same phase to insert after.')
        row['lessons'].insert(index + 1, lesson)
    return lesson


def _change_update_lesson(row, lesson_id, fields):
    lesson = next((l for l in row['lessons'] if l['id'] == lesson_id), None)
    if lesson is None:
        raise ValueError('No such lesson.')
    lesson.update({k: copy.deepcopy(v) for k, v in fields.items() if k in
                   ('title', 'sessions', 'steps', 'variants', 'body', 'url', 'summary', 'origin', 'source_index')})
    return lesson


def _change_update_phase(row, phase_id, fields):
    phase = next((p for p in row['phases'] if p['id'] == phase_id), None)
    if phase is None:
        raise ValueError('No such phase.')
    phase.update({k: copy.deepcopy(v) for k, v in fields.items() if k in ('name', 'milestone', 'what', 'progression')})


def _change_remove_lesson(row, lesson_id):
    if not any(l['id'] == lesson_id for l in row['lessons']):
        raise ValueError('No such lesson.')
    row['lessons'] = [l for l in row['lessons'] if l['id'] != lesson_id]


def _change_order(row, ids):
    by_id = {l['id']: l for l in row['lessons']}
    if (not isinstance(ids, list) or not all(isinstance(i, str) for i in ids)
            or len(ids) != len(by_id) or set(ids) != set(by_id)):
        raise ValueError('Choose every lesson once.')
    row['lessons'] = [by_id[lid] for lid in ids]


def update(library_id, fields, actor):
    return _write(library_id, actor, lambda row: _change_profile(row, fields))


def archive(library_id, actor):
    with storage.db_lock, storage.db.transaction():
        row = storage.get_library_program(library_id)
        if row and can_edit(row, actor) and row.get('archived'):
            return {'status': 'success', 'program': row}
        return _write(library_id, actor, lambda row: row.update(archived=True))


def add_lesson(library_id, fields, actor, after=None):
    return _write(library_id, actor, lambda row: _change_add_lesson(row, fields, after))


def update_lesson(library_id, lesson_id, fields, actor):
    return _write(library_id, actor, lambda row: _change_update_lesson(row, lesson_id, fields))


def update_phase(library_id, phase_id, fields, actor):
    return _write(library_id, actor, lambda row: _change_update_phase(row, phase_id, fields))


def remove_lesson(library_id, lesson_id, actor):
    with storage.db_lock, storage.db.transaction():
        result = _write(library_id, actor, lambda row: _change_remove_lesson(row, lesson_id))
        if result.get('status') == 'success':
            storage.delete_library_lesson_scripts(library_id, lesson_id)
        return result


def order_lessons(library_id, ids, actor):
    return _write(library_id, actor, lambda row: _change_order(row, ids))


def delete(library_id, actor):
    with storage.db_lock, storage.db.transaction():
        row = storage.get_library_program(library_id)
        if not row:
            return {'status': 'error', 'code': 404, 'message': 'No such library program.'}
        if not can_edit(row, actor):
            return {'status': 'error', 'code': 403, 'message': EDIT_REFUSAL}
        refusal = in_use_message(library_id, actor)
        if refusal:
            return {'status': 'error', 'message': refusal}
        storage.delete_library_program(library_id)
    _invalidate()
    return {'status': 'success'}
