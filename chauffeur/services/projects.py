"""The durable project record, its audience and lifecycle."""

import datetime
import time
import uuid
from copy import deepcopy

from services import body_goal, storage


AUDIENCES = ('household', 'parents', 'shared', 'private')
STATES = ('active', 'paused', 'done', 'dropped')
EDITABLE = ('title', 'goal', 'done_when', 'owner_member_id', 'audience', 'shared_with', 'target_date')
AUDIENCE_KEYS = ('audience', 'shared_with', 'owner_member_id')
STEP_STATES = ('todo', 'doing', 'done', 'skipped', 'blocked')
STEP_EDITABLE = ('title', 'owner', 'needs', 'due_date', 'order', 'goal')
PIECE_HOME_KINDS = ('thread', 'mission', 'program')   # live in a project through project_id only


def _link_kinds():
    from services import subjects
    return tuple(k for k in subjects.ADAPTERS if k not in PIECE_HOME_KINDS)


def _child(member):
    return member.get('role') == 'child' or bool(member.get('is_child'))


def _active(member):
    return bool(member and member.get('id') and not member.get('system')
                and member.get('id') != 'argyle'
                and (member.get('status') or 'active') == 'active')


def _parent(member):
    return member.get('role') == 'parent' and not _child(member)


def can_see(project, viewer):
    """The owner always; anyone else by the shared audience model (scope.audience_allows)."""
    from services import access
    if access.gone('project', project) or not project or not _active(viewer):
        return False
    if viewer['id'] == project.get('owner_member_id'):
        return True
    from services import scope
    return scope.audience_allows(project, 'project', viewer)


def can_edit_audience(project, viewer):
    return bool(can_see(project, viewer) and (viewer['id'] == project.get('owner_member_id') or _parent(viewer)))


def can_act(project, viewer):
    if not can_see(project, viewer):
        return False
    return (viewer['id'] == project.get('owner_member_id')
            or (not _child(viewer) and viewer.get('role') in ('parent', 'adult')))


def _error(message):
    return {'status': 'error', 'message': message}


def _listable(mid):
    m = storage.get_member(mid) if isinstance(mid, str) else None
    return bool(m and not m.get('system') and mid != 'argyle' and (m.get('status') or 'active') != 'archived')


def normalize_audience(row, list_given):
    """Shape audience + shared_with in place (spec §2); return an error message or None."""
    audience = row.get('audience')
    if audience not in AUDIENCES:
        return 'Choose household, parents, shared or private'
    owner_id = row.get('owner_member_id')
    owner = storage.get_member(owner_id) or {}
    if list_given and not isinstance(row.get('shared_with'), list):
        return 'Choose people for the list'
    ids = []
    for mid in (row.get('shared_with') or []) if list_given else []:
        if _listable(mid) and mid not in ids:
            ids.append(mid)
    if audience in ('household', 'parents'):
        ids = []
    elif audience == 'private':
        if not list_given:
            ids = [owner_id] + ([m['id'] for m in storage.get_all_members() if _parent(m) and _active(m)]
                                if _child(owner) else [])
        if owner_id not in ids:
            ids.insert(0, owner_id)
    elif audience == 'shared' and not ids:
        audience = 'parents'
    row['audience'], row['shared_with'] = audience, list(dict.fromkeys(ids))
    return None


def _validate(row):
    """Validate the complete proposed record before any write."""
    if not isinstance(row.get('title'), str) or not row['title'].strip():
        return 'A title is required'
    if any(not isinstance(row.get(key), str) for key in ('goal', 'done_when')):
        return 'Goal and done-when must be text'
    owner_id = row.get('owner_member_id')
    if not isinstance(owner_id, str):
        return 'Choose a project owner'
    owner = storage.get_member(owner_id)
    if not _active(owner) or owner.get('role') not in ('parent', 'adult', 'child'):
        return 'Choose an active project owner'
    target_date = row.get('target_date')
    if target_date is not None:
        try:
            if (not isinstance(target_date, str)
                    or datetime.date.fromisoformat(target_date).isoformat() != target_date):
                return 'Target date must be YYYY-MM-DD'
        except ValueError:
            return 'Target date must be YYYY-MM-DD'
    if row.get('body_goal') and (_child(owner) or row['audience'] != 'private'
                                 or row.get('shared_with') != [row['owner_member_id']]):
        return 'A body goal must belong to an adult and stay private'
    return None


def _classify(row):
    # Once classified, editing away the triggering words never clears the pin.
    row['body_goal'] = bool(row.get('body_goal')) or any(
        body_goal.is_body_goal(row.get(key)) for key in ('title', 'goal', 'done_when'))


def prepare_create(fields, actor):
    """Validate and normalize a proposed project without writing it."""
    if (not _active(actor) or actor.get('role') not in ('parent', 'adult', 'child')):
        return _error('Sign in as a project owner or parent')
    if 'body_goal' in fields:
        return _error('Body goals are classified by Chauffeur')
    with storage.db_lock:
        row = {'title': '', 'goal': '', 'done_when': '',
               'owner_member_id': actor['id'], 'target_date': None,
               **{key: fields[key] for key in EDITABLE if key in fields}}
        owner = storage.get_member(row['owner_member_id']) if isinstance(row['owner_member_id'], str) else None
        row.setdefault('audience', 'parents' if _child(owner or {}) else 'private')
        message = normalize_audience(row, 'shared_with' in fields)
        if message:
            return _error(message)
        row['audience_rev'] = 2
        if any(not isinstance(row.get(key), str) for key in ('title', 'goal', 'done_when')):
            return _error('Title, goal and done-when must be text')
        _classify(row)
        message = _validate(row)
        if message:
            return _error(message)
        if row['owner_member_id'] != actor['id'] and not _parent(actor):
            return _error('Only a parent can assign a project to someone else')
        row.update(created_by=actor['id'], state='active', steps=[], pieces=[])
        return {'status': 'success', 'project': row}


def create(fields, actor):
    with storage.db_lock:
        result = prepare_create(fields, actor)
        if result['status'] != 'success':
            return result
        project_id = storage.add_project(result['project'])
        return {'status': 'success', 'project': storage.get_project(project_id)}


def update(project_id, fields, actor):
    with storage.db_lock:
        project = storage.get_project(project_id)
        if not can_act(project, actor):
            return _error('You cannot edit this project')
        if 'body_goal' in fields:
            return _error('Body goals are classified by Chauffeur')
        patch = {key: fields[key] for key in EDITABLE if key in fields}
        proposed = {**project, **patch}
        if any(not isinstance(proposed.get(key), str) for key in ('title', 'goal', 'done_when')):
            return _error('Title, goal and done-when must be text')
        _classify(proposed)
        list_given = 'shared_with' in patch or (proposed.get('audience') == project.get('audience')
                                                 and project.get('audience_rev') == 2)
        message = normalize_audience(proposed, list_given)
        if message:
            return _error(message)
        if proposed['owner_member_id'] != project['owner_member_id'] and proposed['audience'] in ('private', 'shared') \
                and proposed['owner_member_id'] not in proposed['shared_with']:
            proposed['shared_with'].append(proposed['owner_member_id'])
        before = dict(project)
        normalize_audience(before, project.get('audience_rev') == 2)
        touches = (any(proposed.get(k) != before.get(k) for k in ('owner_member_id', 'audience'))
                   or set(proposed['shared_with']) != set(before['shared_with']))
        if touches and not can_edit_audience(project, actor):
            return _error('Only the owner or a parent can change who sees this project')
        message = _validate(proposed)
        if message:
            return _error(message)
        if (proposed['owner_member_id'] != project['owner_member_id']
                and proposed['owner_member_id'] != actor['id'] and not _parent(actor)):
            return _error('Only a parent can assign a project to someone else')
        patch['body_goal'] = proposed['body_goal']
        patch.update(audience=proposed['audience'], shared_with=proposed['shared_with'], audience_rev=2)
        storage.update_project(project_id, patch)
        return {'status': 'success', 'project': storage.get_project(project_id)}


def _work_missions(project):
    from services import missions
    linked = {s.get('mission_id') for s in project.get('steps', [])}
    return [m for m in storage.get_missions()
            if m.get('project_id') == project['id'] or m['id'] in linked
            or missions.subject_of(m)[:2] == ('project', project['id'])]


def stop_work(project_id):
    """Park paused work; end the sessions of a completed or dropped project."""
    from services import missions, planned, situations
    with storage.db_lock:
        project = storage.get_project(project_id)
        if not project:
            return
        actor = storage.get_member(project.get('owner_member_id')) or {}
        if actor.get('role') not in ('parent', 'adult'):
            actor = situations.parent_of_record() or {}
        for mission in _work_missions(project):
            if mission.get('status') not in missions.LIVE:
                continue
            if project['state'] == 'paused':
                if mission.get('paused_by_project'):
                    continue
                prior = {'status': mission['status'], 'retry_at': mission.get('retry_at')}
                plan = mission.get('plan')
                for stage in (plan or {}).get('stages', []):
                    if (mission['status'] in missions.RUNNABLE
                            and stage['kind'] == 'work' and stage['state'] == 'running'):
                        stage.update(state='pending', steps_used=0)
                        stage.pop('budget_ask_pending', None)
                # Changing the generation also invalidates results arriving
                # after a quick pause/resume has started the same stage again.
                parked = mission['status'] in missions.RUNNABLE + ('browsing', 'waiting_retry')
                missions._close(mission['id'], 'waiting_step' if parked else mission['status'],
                                paused_by_project=True, paused_from=prior,
                                project_pause_rev=int(mission.get('project_pause_rev') or 0) + 1,
                                **({'plan': plan} if plan else {}))
                if mission['status'] == 'browsing':
                    storage.set_app_state(f"mission_steer:{mission['id']}", {'text': 'Paused', 'ts': time.time()})
                continue
            if (mission.get('plan') or {}).get('state') not in (None, 'done', 'stopped'):
                planned.stop_plan(mission['id'], actor)
            else:
                storage.set_app_state(f"mission_steer:{mission['id']}", {'text': 'Stopped', 'ts': time.time()})
                for ask in storage.get_mission_steps(mission['id']):
                    if ask.get('kind') == 'ask':
                        missions.settle_ask_cards(mission['id'], ask['id'], 'Stopped')
                missions._close(mission['id'], 'dropped')


def set_state(project_id, state, actor):
    with storage.db_lock:
        project = storage.get_project(project_id)
        if not can_act(project, actor):
            return _error('You cannot change this project')
        if state not in STATES:
            return _error('Choose active, paused, done or dropped')
        storage.update_project(project_id, {'state': state})
        if state in ('paused', 'done', 'dropped'):
            stop_work(project_id)
        elif state == 'active':
            from services import missions
            for mission in _work_missions(storage.get_project(project_id)):
                if mission.get('paused_by_project') and mission.get('status') in missions.LIVE:
                    prior = mission.get('paused_from') or {'status': 'running'}
                    missions._close(mission['id'], prior['status'], retry_at=prior.get('retry_at'),
                                    paused_by_project=False, paused_from=None)
            resume_waiting(project_id)
            advance(project_id)
        return {'status': 'success', 'project': storage.get_project(project_id)}


def _can_edit_step(project, step, actor):
    return can_act(project, actor) and (not _child(actor) or step.get('owner') == actor['id'])


def _hold_interval(hold):
    """Parse the dated, minute-precision wire format without normalizing bad input."""
    day = datetime.date.fromisoformat(hold['date'])
    if day.isoformat() != hold['date']:
        raise ValueError('Date must be YYYY-MM-DD')
    times = []
    for key in ('start', 'end'):
        value = hold[key]
        parsed = datetime.time.fromisoformat(value)
        if parsed.strftime('%H:%M') != value:
            raise ValueError('Time must be HH:MM')
        times.append(datetime.datetime.combine(day, parsed))
    if times[1] <= times[0]:
        raise ValueError('End must be after start')
    return tuple(times)


def _confirmed_holds(start, end):
    from services import access
    for project in storage.get_projects():
        if access.gone('project', project):
            continue
        for step in project.get('steps') or []:
            hold = step.get('hold')
            if step.get('owner') in (None, 'argyle') or not hold:
                continue
            if start.isoformat() <= hold['date'] <= end.isoformat():
                yield project, step, hold


def _busy_intervals(member_id, start, end, exclude=None):
    """The one overlap source for suggestions and confirmation under the lock."""
    from services import programs

    member = storage.get_member(member_id) or {}
    schedule = storage.get_cached_schedule() or {}
    assignments = schedule.get('assignments') or {}
    busy = []
    for event in schedule.get('events') or []:
        # Derived holds must come from live projects below: the cached version
        # can be stale, and would also make replacing one's own hold impossible.
        if event.get('event_type') in ('project_hold', 'practice'):
            continue
        involved = bool(member.get('driver_id') and
                        assignments.get(event.get('id')) == member['driver_id'])
        for key in ('member_ids', 'attendee_ids', 'attendee_member_ids',
                    'members', 'attendees', 'trip_attendees', 'calendar_ids'):
            for person in event.get(key) or []:
                pid = (person.get('member_id') or person.get('id')) if isinstance(person, dict) else person
                if pid == member_id or (key == 'calendar_ids' and
                                        member.get('passenger_id') and pid == member['passenger_id']):
                    involved = True
        if not involved:
            continue
        try:
            begins, finishes = [datetime.datetime.fromisoformat(event[key].replace('Z', '+00:00'))
                                for key in ('start', 'end')]
            # Schedule timestamps carry offsets; holds and waking hours are local.
            begins, finishes = [dt.astimezone().replace(tzinfo=None) if dt.tzinfo else dt
                                for dt in (begins, finishes)]
        except (KeyError, TypeError, ValueError):
            continue
        busy.append((begins, finishes))
    for window in programs.practice_windows(start, end, member_id=member_id):
        busy.append(_hold_interval({'date': window['date'], 'start': window['time_start'],
                                    'end': window['time_end']}))
    for project, step, hold in _confirmed_holds(start, end):
        if step.get('owner') == member_id and (project['id'], step['id']) != exclude:
            busy.append(_hold_interval(hold))
    return busy


def find_window(member_id, minutes, by_date, now=None):
    """First free local waking-hours window, on a half-hour grid."""
    if type(minutes) is not int or minutes <= 0:
        raise ValueError('Minutes must be a positive integer')
    end = datetime.date.fromisoformat(by_date) if isinstance(by_date, str) else by_date
    if isinstance(by_date, str) and end.isoformat() != by_date:
        raise ValueError('By date must be YYYY-MM-DD')
    now = now or datetime.datetime.now()
    if now.tzinfo:
        now = now.astimezone().replace(tzinfo=None)
    day = now.date()
    duration = datetime.timedelta(minutes=minutes)
    busy = _busy_intervals(member_id, day, end)
    while day <= end:
        cursor = datetime.datetime.combine(day, datetime.time(8))
        limit = datetime.datetime.combine(day, datetime.time(21))
        while cursor + duration <= limit:
            finishes = cursor + duration
            if cursor >= now and not any(cursor < b and finishes > a for a, b in busy):
                return {'date': day.isoformat(), 'start': cursor.strftime('%H:%M'),
                        'end': finishes.strftime('%H:%M')}
            cursor += datetime.timedelta(minutes=30)
        day += datetime.timedelta(days=1)
    return None


def _dirty_driver_holds(*steps):
    """Invalidate derived driving schedules when protected driver time moves."""
    dirty = any(step.get('hold') and (storage.get_member(step.get('owner')) or {}).get('driver_id')
                for step in steps)
    if dirty:
        storage.mark_all_daily_schedules_dirty()
    return {'schedule_dirty': True} if dirty else {}


def _change_hold(project_id, step_id, hold, actor):
    with storage.db_lock:
        project = storage.get_project(project_id)
        if not can_act(project, actor):
            return _error('You cannot edit this project')
        steps = deepcopy(project.get('steps') or [])
        step = next((s for s in steps if s['id'] == step_id), None)
        if step is None:
            return _error('No such step')
        if not _can_edit_step(project, step, actor):
            return _error('A child can only hold their own steps')
        if not step.get('owner') or step['owner'] == 'argyle':
            return _error('Choose a person\'s step')
        if hold is not None and not _active(storage.get_member(step['owner'])):
            return _error('Choose an active step owner')
        if hold is not None:
            try:
                begins, finishes = _hold_interval(hold)
            except (KeyError, TypeError, ValueError):
                return _error('Choose a YYYY-MM-DD date and HH:MM times, with end after start')
            busy = _busy_intervals(step['owner'], begins.date(), begins.date(),
                                   exclude=(project_id, step_id))
            if any(begins < b and finishes > a for a, b in busy):
                return _error('That time is no longer free')
            hold = {key: hold[key] for key in ('date', 'start', 'end')}
            hold['confirmed_by'] = actor['id']
        before = deepcopy(step)
        step['hold'] = hold
        storage.update_project(project_id, {'steps': steps})
        return {'status': 'success', 'step': step, **_dirty_driver_holds(before, step)}


def confirm_hold(project_id, step_id, hold, actor):
    if not isinstance(hold, dict):
        return _error('Choose a dated hold')
    return _change_hold(project_id, step_id, hold, actor)


def clear_hold(project_id, step_id, actor):
    return _change_hold(project_id, step_id, None, actor)


def calendar_holds(start, end, viewer):
    """Project words only for the audience; shared readers get neutral time."""
    return [{'date': hold['date'], 'start': hold['start'], 'end': hold['end'],
             'member_id': step['owner'], 'project_id': project['id'], 'step_id': step['id'],
             'title': step['title'] if project.get('audience') == 'household' or can_see(project, viewer)
                      else 'Busy'}
            for project, step, hold in _confirmed_holds(start, end)]


def driver_hold_rules(start, end):
    from models.schemas import Rule

    rules = []
    for project, step, hold in _confirmed_holds(start, end):
        member = storage.get_member(step['owner']) or {}
        if member.get('driver_id'):
            rules.append(Rule(driver_id=member['driver_id'], constraint_type='unavailable',
                              days_of_week=[datetime.date.fromisoformat(hold['date']).weekday()],
                              time_start=hold['start'], time_end=hold['end'], match_overlap=True,
                              start_date=hold['date'], end_date=hold['date']))
    return rules


def _needs_satisfied(step, steps):
    states = {item['id']: item.get('state') for item in steps}
    return all(states.get(sid) in ('done', 'skipped') for sid in step.get('needs') or [])


def needs_satisfied(project, step):
    """Done and skipped prerequisites both release a project's step."""
    return _needs_satisfied(step, (project or {}).get('steps') or [])


def step_for_stage(project_id, mission_id, stage_id):
    """Find the project step linked to this particular mission stage."""
    project = storage.get_project(project_id) or {}
    return next((step for step in project.get('steps') or []
                 if step.get('mission_id') == mission_id and step.get('stage_id') == stage_id), None)


def resume_waiting(project_id):
    """Wake parked work only when its next stage's prerequisites are satisfied."""
    from services import missions

    with storage.db_lock:
        project = storage.get_project(project_id)
        if not project or project.get('state') != 'active':
            return []
        resumed = []
        for mission in storage.get_missions(status='waiting_step'):
            if mission.get('paused_by_project'):
                continue
            if missions.subject_of(mission)[:2] != ('project', project_id):
                continue
            plan = mission.get('plan') or {}
            if plan.get('state') != 'approved':
                continue
            stage = next((s for s in plan.get('stages', [])
                          if s.get('state') not in ('done', 'skipped')), None)
            if not stage or stage.get('state') != 'pending':
                continue
            step = step_for_stage(project_id, mission['id'], stage['id'])
            if step and needs_satisfied(project, step):
                missions._close(mission['id'], 'running')
                resumed.append(mission['id'])
        return resumed


def _validate_step(project, step, steps):
    if not isinstance(step.get('title'), str) or not step['title'].strip():
        return 'A step title is required'
    if body_goal.is_body_goal(step['title']):
        owner = storage.get_member(project.get('owner_member_id')) or {}
        if (not project.get('body_goal') or project.get('audience') != 'private'
                or owner.get('role') not in ('parent', 'adult') or _child(owner)):
            return 'A body-goal step needs an adult\'s private body-goal project'
    if step.get('owner') is not None and not isinstance(step['owner'], str):
        return 'Choose a member or Argyle as the step owner'
    if type(step.get('order')) is not int:
        return 'Step order must be an integer'
    if step.get('owner') == 'argyle' and (
            not isinstance(step.get('goal'), str) or not step['goal'].strip()):
        return 'An Argyle step needs a goal'
    due_date = step.get('due_date')
    if due_date is not None:
        try:
            if (not isinstance(due_date, str)
                    or datetime.date.fromisoformat(due_date).isoformat() != due_date):
                return 'Due date must be YYYY-MM-DD'
        except ValueError:
            return 'Due date must be YYYY-MM-DD'
    graph = {item['id']: item.get('needs') for item in steps}
    for needs in graph.values():
        if not isinstance(needs, list) or any(
                not isinstance(sid, str) or sid not in graph for sid in needs):
            return 'Needs must name existing steps of this project'
    visiting, visited = set(), set()

    def cycle(sid):
        if sid in visiting:
            return True
        if sid in visited:
            return False
        visiting.add(sid)
        if any(cycle(need) for need in graph[sid]):
            return True
        visiting.remove(sid)
        visited.add(sid)
        return False

    if any(cycle(sid) for sid in graph):
        return 'Step dependencies cannot form a cycle'
    return None


def add_step(project_id, step, actor):
    with storage.db_lock:
        project = storage.get_project(project_id)
        if not can_act(project, actor):
            return _error('You cannot edit this project')
        steps = deepcopy(project.get('steps') or [])
        row = {'id': uuid.uuid4().hex, 'order': max(
                   (item['order'] for item in steps), default=-1) + 1,
               'title': '', 'owner': actor['id'], 'needs': [], 'due_date': None,
               **{key: deepcopy(step[key]) for key in STEP_EDITABLE if key in step},
               'state': 'todo', 'done_by': None, 'done_at': None}
        if row['owner'] == 'argyle':
            row.update(mission_id=None, stage_id=None, found=None, question=None)
        else:
            row['hold'] = None
        if not _can_edit_step(project, row, actor):
            return _error('A child can only add their own steps')
        steps.append(row)
        message = _validate_step(project, row, steps)
        if message:
            return _error(message)
        storage.update_project(project_id, {'steps': steps})
        advance(project_id)
        return {'status': 'success', 'step': next(
            s for s in storage.get_project(project_id)['steps'] if s['id'] == row['id'])}


def edit_step(project_id, step_id, fields, actor):
    with storage.db_lock:
        project = storage.get_project(project_id)
        if not can_act(project, actor):
            return _error('You cannot edit this project')
        steps = deepcopy(project.get('steps') or [])
        step = next((item for item in steps if item['id'] == step_id), None)
        if step is None:
            return _error('No such step')
        if not _can_edit_step(project, step, actor):
            return _error('A child can only edit their own steps')
        before = deepcopy(step)
        step.update({key: deepcopy(fields[key]) for key in STEP_EDITABLE if key in fields})
        if not _can_edit_step(project, step, actor):
            return _error('A child can only assign steps to themselves')
        if step.get('owner') == 'argyle':
            for key in ('mission_id', 'stage_id', 'found', 'question'):
                step.setdefault(key, None)
        else:
            step.setdefault('hold', None)
        message = _validate_step(project, step, steps)
        if message:
            return _error(message)
        storage.update_project(project_id, {'steps': steps})
        dirty = _dirty_driver_holds(before, step) if before.get('owner') != step.get('owner') else {}
        resume_waiting(project_id)
        advance(project_id)
        return {'status': 'success', 'step': next(
            s for s in storage.get_project(project_id)['steps'] if s['id'] == step_id), **dirty}


def remove_step(project_id, step_id, actor):
    with storage.db_lock:
        project = storage.get_project(project_id)
        if not can_act(project, actor):
            return _error('You cannot edit this project')
        steps = deepcopy(project.get('steps') or [])
        step = next((item for item in steps if item['id'] == step_id), None)
        if step is None:
            return _error('No such step')
        if not _can_edit_step(project, step, actor):
            return _error('A child can only remove their own steps')
        if any(step_id in (item.get('needs') or []) for item in steps):
            return _error('Another step needs this step; edit its needs first')
        storage.update_project(project_id, {'steps': [item for item in steps if item['id'] != step_id]})
        return {'status': 'success', 'step': step, **_dirty_driver_holds(step)}


def set_step_state(project_id, step_id, state, actor):
    with storage.db_lock:
        project = storage.get_project(project_id)
        if not can_act(project, actor):
            return _error('You cannot change this project')
        steps = deepcopy(project.get('steps') or [])
        step = next((item for item in steps if item['id'] == step_id), None)
        if step is None:
            return _error('No such step')
        if not _can_edit_step(project, step, actor):
            return _error('A child can only tick their own steps')
        if state not in STEP_STATES:
            return _error('Choose todo, doing, done, skipped or blocked')
        if step.get('state') == state:
            return {'status': 'success', 'step': step, 'advanced': []}
        if not _parent(actor) and not _needs_satisfied(step, steps):
            return _error('Finish or skip this step\'s needs first')
        if (step.get('owner') == 'argyle' and step.get('state') not in ('todo', 'doing')
                and state in ('todo', 'doing')):
            if step.get('stage_id'):
                return _error('Plan that part again with Argyle to do it again.')
            from services import missions
            mission = storage.get_mission(step['mission_id']) if step.get('mission_id') else None
            if mission and mission.get('status') in missions.TERMINAL:
                step.setdefault('attempts', []).append({
                    'mission_id': step['mission_id'], 'state': step['state'],
                    'found': deepcopy(step.get('found')), 'at': time.time()})
                step.update(mission_id=None, found=None, question=None)
            if not step.get('mission_id'):
                state = 'todo'  # advance launches it, including a request for doing.
        _stamp_step(step, state, actor['id'])
        # Readiness is derived from needs, so reopening immediately blocks todo
        # dependents again without changing work already doing or done.
        storage.update_project(project_id, {'steps': steps})
        resume_waiting(project_id)
        # The tap response has always reported readiness, including when the
        # mission service is disabled. advance itself reports actual starts.
        ready = [item['id'] for item in sorted(steps, key=lambda item: item['order'])
                 if item.get('owner') == 'argyle' and item.get('state') == 'todo'
                 and _needs_satisfied(item, steps)]
        advance(project_id)
        return {'status': 'success', 'step': next(
            s for s in storage.get_project(project_id)['steps'] if s['id'] == step_id), 'advanced': ready}


def advance(project_id):
    """Start ready Argyle work once; refused launches remain eligible to retry."""
    from services import missions, situations
    with storage.db_lock:
        project = storage.get_project(project_id)
        if not project or project.get('state') != 'active':
            return []
        resumed = resume_waiting(project_id)
        steps = (project or {}).get('steps') or []
        started = []
        for step in sorted(steps, key=lambda item: item['order']):
            if (step.get('owner') != 'argyle' or step.get('state') != 'todo'
                    or not _needs_satisfied(step, steps)):
                continue
            if step.get('mission_id'):
                if step['mission_id'] in resumed:
                    started.append(step['id'])
                continue  # Stage-backed work is started by prepare_next/run_stage.
            owner = storage.get_member(project.get('owner_member_id'))
            creator = owner if _active(owner) else situations.parent_of_record()
            if not creator:
                continue
            result = missions.launch(step['goal'], created_by=creator['id'], project_id=project_id,
                                     subject=('project', project_id))
            if result.get('status') != 'launched':
                continue
            mid = result['mission_id']
            step['mission_id'] = mid
            _stamp_step(step, 'doing', 'argyle')
            storage.update_project(project_id, {'steps': steps})
            started.append(step['id'])
        return started


def _stamp_step(step, state, actor):
    """Shared state stamp for person actions and trusted engine transitions."""
    step.update(state=state, done_by=actor if state in ('done', 'skipped') else None,
                done_at=time.time() if state in ('done', 'skipped') else None)


def _work_step(mission_id, stage_id, state=None, **fields):
    from services import missions
    with storage.db_lock:
        mission = storage.get_mission(mission_id) or {}
        kind, pid, _ = missions.subject_of(mission)
        if kind != 'project':
            return
        project = storage.get_project(pid) or {}
        step = next((s for s in project.get('steps', []) if s.get('owner') == 'argyle'
                     and s.get('mission_id') == mission_id and s.get('stage_id') == stage_id), None)
        if not step or step.get('state') in ('done', 'skipped'):
            return
        if state:
            _stamp_step(step, state, 'argyle')
        step.update(fields)
        storage.update_project(pid, {'steps': project['steps']})
        if state in ('done', 'skipped'):
            resume_waiting(pid)
            advance(pid)


def on_stage_started(mission_id, stage_id):
    _work_step(mission_id, stage_id, 'doing', question=None)


def on_stage_done(mission_id, stage_id, found):
    _work_step(mission_id, stage_id, 'done', found=found, question=None)


def on_stage_blocked(mission_id, stage_id, reason):
    _work_step(mission_id, stage_id, 'blocked', question=reason)


def on_stage_cancelled(mission_id, stage_id, outcome):
    _work_step(mission_id, stage_id, 'skipped' if outcome == 'skip' else 'blocked',
               question=None if outcome == 'skip' else 'Stopped')


def on_question(mission_id, question):
    mission = storage.get_mission(mission_id) or {}
    stage = next((s for s in (mission.get('plan') or {}).get('stages', [])
                  if s.get('state') == 'running'), None)
    _work_step(mission_id, stage['id'] if stage else None, question=question)


def on_mission_closed(mission_id, status, reason=''):
    """Only standalone steps finish with a mission; stage steps finish earlier."""
    mission = storage.get_mission(mission_id) or {}
    if status == 'done':
        _work_step(mission_id, None, 'done', found={'summary': mission.get('summary') or ''}, question=None)
    elif status in ('blocked', 'dropped'):
        from services import missions
        kind, pid, _ = missions.subject_of(mission)
        if kind == 'project':
            for step in (storage.get_project(pid) or {}).get('steps', []):
                if (step.get('mission_id') == mission_id
                        and step.get('state') not in ('done', 'skipped')):
                    _work_step(mission_id, step.get('stage_id'), 'blocked',
                               question=reason or 'Stopped')


def _change_piece(project_id, kind, sid, actor, removing=False):
    from services import access, subjects

    with storage.db_lock:
        project = storage.get_project(project_id)
        if not can_act(project, actor):
            return _error('You cannot edit this project')
        if not isinstance(kind, str) or (kind not in subjects.ADAPTERS and kind not in PIECE_HOME_KINDS):
            return _error('Choose a registered record kind')
        if kind in PIECE_HOME_KINDS and not removing:
            return _error('Threads, missions and programs start inside a project; they are not linked')
        if not isinstance(sid, str) or not sid:
            return _error('Choose a record id')
        if kind in PIECE_HOME_KINDS:
            record = access.KINDS[kind].load(sid)
            visible = access.record_visible(kind, record, actor)
        else:
            record = subjects.load(kind, sid)
            visible = subjects.visible(kind, record, actor)
        if record is None or not visible:
            return _error('No such visible record')
        pieces = deepcopy(project.get('pieces') or [])
        existing = next((p for p in pieces if (p['kind'], p['id']) == (kind, sid)), None)
        if removing:
            if existing is not None:
                pieces = [p for p in pieces if (p['kind'], p['id']) != (kind, sid)]
                storage.update_project(project_id, {'pieces': pieces})
        elif existing is None:
            pieces.append({'kind': kind, 'id': sid, 'added_by': actor['id'], 'added_at': time.time()})
            storage.update_project(project_id, {'pieces': pieces})
        return {'status': 'success', 'piece': {'kind': kind, 'id': sid}}


def add_piece(project_id, kind, sid, actor):
    return _change_piece(project_id, kind, sid, actor)


def remove_piece(project_id, kind, sid, actor):
    return _change_piece(project_id, kind, sid, actor, removing=True)


_ADOPT_TABLES = {'thread': (storage.get_thread, storage.update_thread),
                 'mission': (storage.get_mission, storage.update_mission),
                 'program': (storage.get_program, storage.update_program)}


def project_for(kind, record_id):
    """The project a thread, mission or program belongs to, or None."""
    get, _ = _ADOPT_TABLES[kind]
    row = get(record_id) or {}
    return storage.get_project(row.get('project_id')) if row.get('project_id') else None


def _belongs_to(kind, row):
    """The project a record already belongs to by an earlier binding, if any."""
    from services import missions
    if kind == 'mission':
        if row.get('origin_kind') == 'thread' and row.get('origin_ref'):
            thread = storage.get_thread(row['origin_ref']) or {}
            if thread.get('project_id') and storage.get_project(thread['project_id']):
                return thread['project_id']
        skind, sid, _ = missions.subject_of(row)
        if skind == 'project' and storage.get_project(sid):
            return sid
    for project in storage.get_projects():
        if any(p.get('kind') == kind and p.get('id') == row.get('id') for p in project.get('pieces') or []):
            return project['id']
    return None


def _state_for(kind, row):
    st = row.get('state') if kind != 'mission' else row.get('status')
    if kind == 'thread':
        return {'done': 'done', 'dropped': 'dropped'}.get(st, 'active')
    if kind == 'program':
        return {'done': 'done', 'dropped': 'dropped', 'paused': 'paused'}.get(st, 'active')
    from services import missions
    if st in missions.LIVE or st == 'waiting_user':
        return 'active'
    return 'done' if st == 'done' else 'dropped'


def _wrapper_fields(kind, row, actor):
    """Title, goal, owner and audience for a project made from a record (§1)."""
    from services import situations
    if kind == 'thread':
        title, goal, owner = row.get('title') or '', row.get('goal') or row.get('title') or '', row.get('owner_member_id')
    elif kind == 'program':
        title, goal, owner = row.get('title') or '', row.get('title') or '', row.get('member_id')
    else:
        title, goal, owner = (row.get('goal') or '')[:80], row.get('goal') or '', row.get('created_by')
    member = storage.get_member(owner) if owner else None
    if not _active(member or {}):
        member = situations.parent_of_record()
    # adopt derives the audience from the record before creating the wrapper.
    return {'title': title or 'Untitled', 'goal': goal, 'done_when': '', 'owner_member_id': (member or {}).get('id'),
            'audience': 'private'}


def adopt(kind, record_id, actor, project_id=None):
    """Give a thread, mission or program its one project (front door §1).

    An explicit project wins; else the project the record already belongs to
    by binding; else a project made from the record. Idempotent: a record
    that has a project keeps it, even a dropped one (reopening is an act)."""
    get, update = _ADOPT_TABLES[kind]
    with storage.db_lock:
        from services import access, deletion
        deletion.check()
        row = get(record_id)
        if not row:
            return None
        home_id = row.get('project_id')
        home = storage.get_project(home_id) if home_id else None
        target = storage.get_project(project_id) if project_id else None
        if (access.gone(kind, row) or
                (home_id and access.gone('project', home, rid=home_id)) or
                (project_id and (not target or access.gone('project', target)))):
            if deletion.has_source():
                raise deletion.Cancelled(f'{kind} {record_id} or its project was deleted')
            return None
        # Creation now binds the home in the initial insert. Adoption still
        # records its native piece card, including for an already bound row.
        pid = (home_id if home else
               project_id if target else _belongs_to(kind, row))
        if pid and access.gone('project', storage.get_project(pid), rid=pid):
            if deletion.has_source():
                raise deletion.Cancelled(f'project {pid} was deleted')
            return None
        if not pid:
            fields = _wrapper_fields(kind, row, actor)
            from services import project_audience
            owner_id, audience, listed, retitle = project_audience.derive_for_record(kind, row, fields['owner_member_id'])
            fields.update(owner_member_id=owner_id, audience=audience, shared_with=listed)
            if retitle:
                fields.update(title='Untitled project', goal='')
            if any(body_goal.is_body_goal(fields.get(key)) for key in ('title', 'goal')):
                fields.update(audience='private', shared_with=[owner_id])
            owner = storage.get_member(fields['owner_member_id']) or {}
            creator = actor if _active(actor or {}) else (owner if _active(owner) else None)
            if not creator:
                from services import situations
                creator = situations.parent_of_record()
            if not creator:
                return None
            prepared = prepare_create(fields, creator)
            if prepared['status'] != 'success':
                # A body-goal title a child typed, or an owner the actor may not
                # assign: fall back to the creator as owner, private.
                fallback = {**fields, 'owner_member_id': creator['id'], 'audience': 'private'}
                fallback.pop('shared_with', None)
                prepared = prepare_create(fallback, creator)
                if prepared['status'] != 'success':
                    return None
            project = prepared['project']
            project['state'] = _state_for(kind, row)
            project['wrapped_from'] = {'kind': kind, 'id': record_id}
            pid = storage.add_project(project)
        if row.get('project_id') != pid:
            update(record_id, {'project_id': pid})
        project = storage.get_project(pid)
        pieces = project.get('pieces') or []
        if not any(p.get('kind') == kind and p.get('id') == record_id for p in pieces):
            storage.update_project(pid, {'pieces': pieces + [{'kind': kind, 'id': record_id}]})
        return pid


ADOPTED_KEY = 'projects_adopted_rev'


def adopt_existing():
    """One-time wrap of every thread, mission and program (front door §1).

    Threads first so their missions join the thread's project; closed rows
    become done or dropped projects so old links still open. Recorded in
    app state; a later record is adopted at creation."""
    with storage.db_lock:
        if int(storage.get_app_state(ADOPTED_KEY) or 0) >= 1:
            return {'threads': 0, 'missions': 0, 'programs': 0, 'skipped': True}
        counts = {'threads': 0, 'missions': 0, 'programs': 0, 'skipped': False}
        for row in storage.get_threads(include_closed=True):
            if adopt('thread', row['id'], None):
                counts['threads'] += 1
        for row in storage.get_missions():
            if adopt('mission', row['id'], None):
                counts['missions'] += 1
        for row in storage.get_programs(include_finished=True):
            if adopt('program', row['id'], None):
                counts['programs'] += 1
        storage.set_app_state(ADOPTED_KEY, 1)
        return counts


AUDIENCE_LABEL = {'private': 'Private', 'parents': 'Parents', 'shared': 'Parents and chosen people',
                  'household': 'Household'}


def audience_label(project):
    names = [n for n in _listed(project) if n['id'] != project.get('owner_member_id')]
    if project.get('audience') == 'private' and names:
        return 'Only ' + ', '.join([(storage.get_member(project['owner_member_id']) or {}).get('name') or 'the owner']
                                   + [n['name'] for n in names])
    return AUDIENCE_LABEL.get(project.get('audience'), '')


def _listed(project):
    out = []
    for mid in project.get('shared_with') or []:
        m = storage.get_member(mid)
        if _active(m or {}):
            out.append({'id': mid, 'name': m.get('name') or ''})
    return out


def needs_plan(project):
    """An active project with no steps and no live planning: a parent's Needs you row."""
    from services import missions
    if project.get('state') != 'active' or project.get('steps'):
        return False
    return not any(m.get('status') in missions.LIVE for m in _work_missions(project))


def planless(project):
    """Only an empty project can still need its first plan."""
    return needs_plan(project) and not project.get('pieces')


def card(project, viewer, planning='started', reason=''):
    """The project chat card (front door §1); None for a viewer who may not see it."""
    if not can_see(project, viewer):
        return None
    owner = storage.get_member(project.get('owner_member_id')) or {}
    return {'kind': 'project', 'project_id': project['id'], 'title': project.get('title') or '',
            'goal': project.get('goal') or '', 'owner': project.get('owner_member_id'),
            'owner_label': owner.get('name') if _active(owner) else 'Unassigned',
            'audience': project.get('audience'), 'audience_label': audience_label(project),
            'shared_with': _listed(project), 'can_edit_audience': can_edit_audience(project, viewer),
            'state': project.get('state'), 'planning': planning, 'reason': reason,
            'can_edit': can_act(project, viewer), 'body_goal': bool(project.get('body_goal'))}


SHEET_KINDS = ('thread', 'mission', 'program')
LANES = ('needs_you', 'moving', 'waiting', 'paused', 'closed')


def _record_visible(kind, row, viewer):
    from services import situations, subjects
    if kind == 'program':
        return subjects.visible('program', row, viewer)
    return situations.can_see(kind, row, viewer)


def piece_cards(project, viewer, project_view=None):
    """One card per piece the viewer may see, drawn by its kind (front door §2)."""
    from services import situations, programs
    out = []
    project_view = view(project, viewer) if project_view is None else project_view
    for piece in project_view.get('pieces', []):
        kind, sid = piece['kind'], piece['id']
        card = {**piece, 'sheet': kind in SHEET_KINDS}
        if kind in ('thread', 'mission'):
            card['situation'] = situations.view(kind, sid, viewer)
            if card['situation'] is None:
                continue
        elif kind == 'program':
            row = storage.get_program(sid) or {}
            phase = (programs.progress(row) or {}).get('phase') or {}
            card['program'] = {'state': row.get('state'), 'member_id': row.get('member_id'),
                               'phase': phase.get('name') or ''}
        out.append(card)
    return out


def lane(project, viewer, cards=None, planless_=None):
    """Which overview lane a project sits in for this viewer (front door §2)."""
    state = project.get('state')
    if state in ('done', 'dropped'):
        return 'closed'
    if state == 'paused':
        return 'paused'
    viewer = viewer or {}
    planless_ = planless(project) if planless_ is None else planless_
    owner = storage.get_member(project.get('owner_member_id')) or {}
    if planless_ and _child(owner) and _parent(viewer) and viewer.get('id') != project.get('owner_member_id'):
        return 'needs_you'
    cards = piece_cards(project, viewer) if cards is None else cards
    steps = project.get('steps') or []
    if not _child(viewer) and any(s.get('owner') == 'argyle' and (s.get('question') or s.get('state') == 'blocked')
                                  for s in steps):
        return 'needs_you'
    groups = [(c.get('situation') or {}).get('group') for c in cards]
    if 'now' in groups:
        return 'needs_you'
    if _parent(viewer) and any((c.get('program') or {}).get('state') == 'proposed' for c in cards):
        return 'needs_you'
    mine = [s for s in steps if s.get('state') == 'todo' and s.get('owner') == viewer.get('id')
            and _needs_satisfied(s, steps)]
    if mine or 'moving' in groups or 'in_hand' in groups or any(s.get('state') == 'doing' for s in steps):
        return 'moving'
    return 'waiting'


def overview_row(project, viewer):
    """A project's overview card: its view, its lane and the one line it says next."""
    row = view(project, viewer)
    is_planless = planless(project)
    cards = ([] if project.get('state') in ('done', 'dropped', 'paused')
             else piece_cards(project, viewer, project_view=row))
    nxt = (row.get('next_step') or {}).get('title') or ''
    if not nxt and is_planless:
        nxt = 'Needs a plan'
    if not nxt:
        nxt = next(((c['situation'].get('next_step') or {}).get('label') or ''
                    for c in cards if (c.get('situation') or {}).get('next_step')), '')
    row.update(lane=lane(project, viewer, cards=cards, planless_=is_planless), card_next=nxt,
               has_program=any(p['kind'] == 'program' for p in row.get('pieces', [])), needs_plan=is_planless)
    return row


def elsewhere(viewer):
    """Missions this person started whose project they may not see: a keeper's
    rows, drawn with the keeper projection (front door §2)."""
    from services import situations
    if not viewer or not viewer.get('id'):
        return []
    out = []
    for m in storage.get_missions():
        if m.get('created_by') != viewer['id'] or not m.get('project_id'):
            continue
        project = storage.get_project(m['project_id'])
        if project is None or can_see(project, viewer):
            continue
        v = situations.view('mission', m['id'], viewer)
        if v:
            out.append(v)
    return out


def locate(kind, record_id, viewer):
    """Where an old link lands (front door §3): the record's project when the
    viewer may see both, else the record alone when they may see that."""
    if kind not in _ADOPT_TABLES:
        return {'project_id': None, 'record_visible': False}
    row = _ADOPT_TABLES[kind][0](record_id)
    if not row:
        return {'project_id': None, 'record_visible': False}
    visible = _record_visible(kind, row, viewer)
    project = storage.get_project(row.get('project_id')) if row.get('project_id') else None
    return {'project_id': project['id'] if project and visible and can_see(project, viewer) else None,
            'record_visible': bool(visible)}


def view(project, viewer):
    """Return only this viewer's project and visible piece references."""
    from services import subjects, access

    if not access.project_visible(project, viewer):
        return {}
    result = {key: deepcopy(project.get(key)) for key in
              ('id', 'title', 'goal', 'done_when', 'owner_member_id', 'audience', 'state', 'target_date', 'body_goal')}
    result.update(audience_label=audience_label(project), shared_with=_listed(project),
                  can_edit_audience=can_edit_audience(project, viewer))
    result['steps'] = deepcopy(project.get('steps') or [])
    result['can_act'] = can_act(project, viewer)
    for step in result['steps']:
        step['can_edit'] = _can_edit_step(project, step, viewer)
        step['can_cancel'] = can_act(project, viewer) and not _child(viewer)
        owner = storage.get_member(step.get('owner')) or {}
        step['owner_label'] = ('Argyle' if step.get('owner') == 'argyle' else
                               owner.get('name') if _active(owner) else 'Unassigned')
    result['pieces'] = []
    for piece in project.get('pieces') or []:
        kind, sid = piece.get('kind'), piece.get('id')
        if kind == 'mission':
            # Missions have no subject adapter (they are never what something is
            # ABOUT), so their piece reads the mission row and its own audience.
            from services import situations
            row = storage.get_mission(sid)
            if row is not None and situations.can_see('mission', row, viewer):
                result['pieces'].append({'kind': kind, 'id': sid, 'title': (row.get('goal') or '')[:80],
                                         'link': f'projects?piece=mission:{sid}'})
            continue
        row = subjects.load(kind, sid)
        if row is not None and subjects.visible(kind, row, viewer):
            result['pieces'].append({'kind': kind, 'id': sid,
                                     'title': subjects.title_of(kind, row),
                                     'link': subjects.link(kind, sid)})
    result.update(next_step=next((step for step in sorted(result['steps'], key=lambda item: item['order'])
                                  if step.get('state') == 'todo'
                                  and _needs_satisfied(step, result['steps'])), None),
                  steps_done=sum(step.get('state') == 'done' for step in result['steps']),
                  steps_total=len(result['steps']))
    return result


def _context(row, viewer, spoken, facet):
    from services import subjects

    return subjects._clip([f"PROJECT: {row['title']}",
                           f"Goal: {row.get('goal') or 'not on file'}",
                           f"Done when: {row.get('done_when') or 'not on file'}",
                           f"State: {row.get('state')}", 'Next step: none yet'])


# Import the registry only after defining the service: subjects loads this
# module after its own built-ins, and either module may be imported first.
from services import subjects as _subjects

def _adapter_visible(row, viewer):
    """HOUSE (wall, speaker, Mind) has a meaning here: household projects only."""
    from services import access
    return access.project_visible(row, viewer)


_subjects.register('project', _subjects.Adapter(
    rows=storage.get_projects,
    title=lambda row: row.get('title') or '',
    visible=_adapter_visible,
    closed=lambda row: row.get('state') in ('done', 'dropped'),
    link=lambda sid: f'projects?id={sid}',
    context=_context,
    facets=[],
    spoken_safe=lambda row: row.get('audience') == 'household',
))
