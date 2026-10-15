"""The durable project record, its audience and lifecycle."""

import datetime
from copy import deepcopy

from services import body_goal, storage


AUDIENCES = ('private', 'parents', 'household')
STATES = ('active', 'paused', 'done', 'dropped')
EDITABLE = ('title', 'goal', 'done_when', 'owner_member_id', 'audience', 'target_date')


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


def view(project, viewer):
    """Return only this viewer's project and visible piece references."""
    from services import subjects

    if not can_see(project, viewer):
        return {}
    result = {key: deepcopy(project.get(key)) for key in
              ('id', 'title', 'goal', 'done_when', 'owner_member_id', 'audience', 'state', 'target_date')}
    result['steps'] = deepcopy(project.get('steps') or [])
    result['pieces'] = []
    for piece in project.get('pieces') or []:
        kind, sid = piece.get('kind'), piece.get('id')
        row = subjects.load(kind, sid)
        if subjects.visible(kind, row, viewer):
            result['pieces'].append({'kind': kind, 'id': sid})
    result.update(next_step=None,
                  steps_done=sum(step.get('state') in ('done', 'skipped') for step in result['steps']),
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
