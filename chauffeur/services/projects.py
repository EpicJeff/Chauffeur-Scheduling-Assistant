"""The durable project record, its audience and lifecycle."""

import datetime
import time
import uuid
from copy import deepcopy

from services import body_goal, storage


AUDIENCES = ('private', 'parents', 'household')
STATES = ('active', 'paused', 'done', 'dropped')
EDITABLE = ('title', 'goal', 'done_when', 'owner_member_id', 'audience', 'target_date')
STEP_STATES = ('todo', 'doing', 'done', 'skipped', 'blocked')
STEP_EDITABLE = ('title', 'owner', 'needs', 'due_date', 'order', 'goal')


def _child(member):
    return member.get('role') == 'child' or bool(member.get('is_child'))


def _active(member):
    return bool(member and member.get('id') and not member.get('system')
                and member.get('id') != 'argyle'
                and (member.get('status') or 'active') == 'active')


def _parent(member):
    return member.get('role') == 'parent' and not _child(member)


def can_see(project, viewer):
    """A child's private project still includes every active parent."""
    if not project or not _active(viewer):
        return False
    if viewer['id'] == project.get('owner_member_id'):
        return True
    audience = project.get('audience')
    if audience == 'household':
        return True
    if not _parent(viewer):
        return False
    owner = storage.get_member(project.get('owner_member_id')) or {}
    return audience == 'parents' or (audience == 'private' and _child(owner))


def can_act(project, viewer):
    if not can_see(project, viewer):
        return False
    return (viewer['id'] == project.get('owner_member_id')
            or (not _child(viewer) and viewer.get('role') in ('parent', 'adult')))


def _error(message):
    return {'status': 'error', 'message': message}


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
    if row.get('audience') not in AUDIENCES:
        return 'Choose private, parents or household'
    target_date = row.get('target_date')
    if target_date is not None:
        try:
            if (not isinstance(target_date, str)
                    or datetime.date.fromisoformat(target_date).isoformat() != target_date):
                return 'Target date must be YYYY-MM-DD'
        except ValueError:
            return 'Target date must be YYYY-MM-DD'
    if row.get('body_goal') and (_child(owner) or row['audience'] != 'private'):
        return 'A body goal must belong to an adult and stay private'
    return None


def _classify(row):
    # Once classified, editing away the triggering words never clears the pin.
    row['body_goal'] = bool(row.get('body_goal')) or any(
        body_goal.is_body_goal(row.get(key)) for key in ('title', 'goal', 'done_when'))


def create(fields, actor):
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
        if any(not isinstance(row.get(key), str) for key in ('title', 'goal', 'done_when')):
            return _error('Title, goal and done-when must be text')
        _classify(row)
        message = _validate(row)
        if message:
            return _error(message)
        if row['owner_member_id'] != actor['id'] and not _parent(actor):
            return _error('Only a parent can assign a project to someone else')
        row.update(created_by=actor['id'], state='active', steps=[], pieces=[])
        project_id = storage.add_project(row)
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
        message = _validate(proposed)
        if message:
            return _error(message)
        if (proposed['owner_member_id'] != project['owner_member_id']
                and proposed['owner_member_id'] != actor['id'] and not _parent(actor)):
            return _error('Only a parent can assign a project to someone else')
        patch['body_goal'] = proposed['body_goal']
        storage.update_project(project_id, patch)
        return {'status': 'success', 'project': storage.get_project(project_id)}


def stop_work(project_id):
    """Task 6 will cancel this project's running Argyle work here."""


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
        return {'status': 'success', 'project': storage.get_project(project_id)}


def _can_edit_step(project, step, actor):
    return can_act(project, actor) and (not _child(actor) or step.get('owner') == actor['id'])


def _needs_satisfied(step, steps):
    states = {item['id']: item.get('state') for item in steps}
    return all(states.get(sid) in ('done', 'skipped') for sid in step.get('needs') or [])


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
        return {'status': 'success', 'step': deepcopy(row)}


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
        return {'status': 'success', 'step': deepcopy(step)}


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
        return {'status': 'success', 'step': step}


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
        step.update(state=state,
                    done_by=actor['id'] if state in ('done', 'skipped') else None,
                    done_at=time.time() if state in ('done', 'skipped') else None)
        # Readiness is derived from needs, so reopening immediately blocks todo
        # dependents again without changing work already doing or done.
        storage.update_project(project_id, {'steps': steps})
        return {'status': 'success', 'step': deepcopy(step), 'advanced': advance(project_id)}


def advance(project_id):
    """Find ready Argyle steps; Task 6 will start their work here."""
    with storage.db_lock:
        project = storage.get_project(project_id)
        steps = (project or {}).get('steps') or []
        return [step['id'] for step in sorted(steps, key=lambda item: item['order'])
                if step.get('owner') == 'argyle' and step.get('state') == 'todo'
                and _needs_satisfied(step, steps)]


def view(project, viewer):
    """Return only this viewer's project and visible piece references."""
    from services import subjects

    if not can_see(project, viewer):
        return {}
    result = {key: deepcopy(project.get(key)) for key in
              ('id', 'title', 'goal', 'done_when', 'owner_member_id', 'audience', 'state', 'target_date')}
    result['steps'] = deepcopy(project.get('steps') or [])
    for step in result['steps']:
        owner = storage.get_member(step.get('owner')) or {}
        step['owner_label'] = ('Argyle' if step.get('owner') == 'argyle' else
                               owner.get('name') if _active(owner) else 'Unassigned')
    result['pieces'] = []
    for piece in project.get('pieces') or []:
        kind, sid = piece.get('kind'), piece.get('id')
        row = subjects.load(kind, sid)
        if subjects.visible(kind, row, viewer):
            result['pieces'].append({'kind': kind, 'id': sid})
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

_subjects.register('project', _subjects.Adapter(
    rows=storage.get_projects,
    title=lambda row: row.get('title') or '',
    visible=can_see,
    closed=lambda row: row.get('state') in ('done', 'dropped'),
    link=lambda sid: f'projects?id={sid}',
    context=_context,
    facets=[],
    spoken_safe=lambda row: row.get('audience') == 'household',
))
