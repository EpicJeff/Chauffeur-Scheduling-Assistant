"""Admission contract and approval records for planned mission stages."""

import hashlib
import json
import time
from copy import deepcopy
from contextlib import nullcontext

from services import storage, subjects, missions, deletion

_clock = time.monotonic
# A tick may run while a foreground approval is executing. Only orphaned
# persisted claims need restart reconciliation.
_active_stages = set()


CAPS = {'questions': 5, 'rounds': 2, 'stages': 7, 'rows': 15,
        'model_rows': 3, 'stage_seconds': 120, 'work_steps': 12}
NAME_ARGS = {'occasion_name', 'thread_title', 'list_name', 'trip_name'}


def _contract(targets=None, creates=None, model_calls=0, idem=False):
    return {'targets': targets or {}, 'idem': idem,
            'creates': creates, 'model_calls': model_calls}


CONTRACT = {
    'add_project_step': _contract({'project_id': 'project'}),
    'add_to_project': _contract({'project_id': 'project'}),
    'set_project_state': _contract({'project_id': 'project'}),
    'set_step_state': _contract({'project_id': 'project'}),
    'add_occasion': _contract(creates='occasion', idem=True),
    'add_occasion_guests': _contract({'occasion_id': 'occasion'}),
    'set_occasion_attendance': _contract({'occasion_id': 'occasion'}),
    'answer_occasion_question': _contract({'occasion_id': 'occasion'}),
    'stamp_occasion_template': _contract({'occasion_id': 'occasion'}),
    # The dishes come from a model reading the words: a repeat is not the same call.
    'add_occasion_dishes': _contract({'occasion_id': 'occasion'}, 'dish', 1),
    'set_occasion_menu': _contract({'occasion_id': 'occasion', 'dish_ids': 'dish'}),
    'source_for_occasion': _contract({'occasion_id': 'occasion'}, 'list', 1),
    'add_occasion_gift_list': _contract({'occasion_id': 'occasion'}, 'list', idem=True),
    'create_trip': _contract(creates='trip', idem=True),
    'add_trip_poi': _contract({'trip_id': 'trip'}, 'poi', idem=True),
    'add_trip_accommodation': _contract({'trip_id': 'trip'}, 'accommodation', idem=True),
    'manage_trip_flights': _contract({'trip_id': 'trip'}, model_calls=1),
    'schedule_trip_itinerary': _contract({'trip_id': 'trip'}),
    'propose_program': _contract(creates='program', model_calls=4),
    'create_list': _contract(creates='list', idem=True),
    'add_shopping_items': _contract({'list_id': 'list'}),
    'add_errand': _contract(creates='errand', idem=True),
    'create_event': _contract(creates='event'),
    'create_thread': _contract(creates='thread', idem=True),
    'add_thread_note': _contract({'thread_id': 'thread'}),
    'draft_thread_message': _contract({'thread_id': 'thread'}, model_calls=1),
    'add_household_task': _contract(creates='task', idem=True),
    'draft_message': _contract(),
}


def _valid_target(value, kind):
    if isinstance(value, dict):
        return (isinstance(value.get('$ref'), str) and bool(value['$ref'])
                and value.get('kind') == kind)
    if not isinstance(value, str) or not value:
        return False
    if kind in subjects.KINDS:
        return subjects.load(kind, value) is not None
    return kind == 'dish' and storage.get_dish(value) is not None


def check_row(row):
    tool = row.get('tool')
    contract = CONTRACT.get(tool)
    if contract is None:
        return f'{tool} is not stage-ready yet.'
    args = row.get('args', {})
    if not isinstance(args, dict):
        return f'{tool}: arguments must contain record ids.'
    if NAME_ARGS.intersection(args):
        return f'{tool}: use the id, not a name.'
    if (tool == 'manage_trip_flights' and isinstance(args.get('flight'), dict)
            and {'event_id', 'trip_id'}.intersection(args['flight'])):
        return 'Use only the outer trip id for flights.'
    for arg, kind in contract['targets'].items():
        value = args.get(arg)
        if isinstance(value, dict):
            valid = _valid_target(value, kind)
        elif arg == 'dish_ids':
            valid = isinstance(value, list) and all(_valid_target(v, kind) for v in value)
        else:
            valid = _valid_target(value, kind)
        if not valid:
            return f'{tool}: {arg} must be an existing {kind} id or a matching $ref.'
    return None


def check_rows(rows):
    if len(rows) > CAPS['rows']:
        return f"A build stage may contain at most {CAPS['rows']} rows."
    if sum(CONTRACT.get(row.get('tool'), {}).get('model_calls', 0) > 0
           for row in rows) > CAPS['model_rows']:
        return f"A build stage may contain at most {CAPS['model_rows']} model-calling rows."
    return next((error for row in rows if (error := check_row(row))), None)


def _check_row_order(rows):
    """Require unique ids and dependencies on earlier rows of this stage."""
    def refs(value):
        if isinstance(value, dict):
            if '$ref' in value:
                yield value['$ref']
            for child in value.values():
                yield from refs(child)
        elif isinstance(value, list):
            for child in value:
                yield from refs(child)

    seen = set()
    for row in rows:
        row_id = row.get('id')
        if not isinstance(row_id, str) or not row_id or row_id in seen:
            return 'Rows need unique non-empty string ids.'
        needs = row.get('needs') or []
        if not isinstance(needs, list) or any(not isinstance(dep, str) or dep not in seen for dep in needs):
            return 'Prerequisites must name earlier rows in the same stage.'
        if any(not isinstance(ref, str) or ref not in seen for ref in refs(row.get('args', {}))):
            return 'Every $ref must name an earlier row in the same stage.'
        seen.add(row_id)
    return None


def snapshot(stage, subject, plan_rev):
    payload = {'kind': stage['kind'], 'subject': subject, 'plan_rev': plan_rev}
    if stage['kind'] == 'build':
        payload['rows'] = [{'id': row['id'], 'tool': row['tool'],
                            'args': row.get('args') or {},
                            'excluded': row.get('state') == 'excluded'}
                           for row in stage.get('rows', [])]
    else:
        payload.update(goal=stage.get('goal'), step_budget=stage.get('step_budget'))
    canonical = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def new_plan():
    return {'state': 'interviewing', 'rev': 0, 'questions': [], 'stages': [],
            'approved_by': None, 'approved_at': None}


def may_approve(mission, actor):
    from services import situations
    return ((actor or {}).get('role') in ('parent', 'adult')
            and all(situations._subject_visible(kind, record, actor)
                    for kind, record in subjects.subject_records('mission', mission)))


def is_keeper(mission, viewer) -> bool:
    """Ownership keeps the mission row, never what is hidden around it."""
    from services import access
    return access.record_view('mission', mission, viewer) == access.KEEPER


def redacted(plan) -> dict:
    """Progress only: never copy any of the planner's words or work."""
    plan = plan or {}
    stages = plan.get('stages') or []
    out = {'state': plan.get('state'), 'stage_count': len(stages),
           'current_index': next((i for i, stage in enumerate(stages, 1)
                                  if stage.get('state') not in ('done', 'skipped')), None)}
    if (plan.get('state') == 'proposed'
            or (plan.get('state') == 'interviewing' and _remaining(plan))
            or any(s.get('state') in ('proposed', 'uncertain', 'waiting_choice') or can_resume_stage(s)
                   or s.get('budget_ask_pending') for s in stages)):
        out['waiting_on'] = 'a parent'
    return out


def keeper_view(mission, viewer):
    """The same keeper projection for active, history and transcript reads."""
    if not is_keeper(mission, viewer):
        return mission
    row = {k: mission[k] for k in (
        'id', 'status', 'tier', 'created_by', 'created_at', 'updated_at',
        'retry_at', 'acknowledged_at', 'finished_at', 'origin_kind', 'origin_ref',
        'goal', 'step_count', 'rev') if k in mission}
    row['plan'] = redacted(mission['plan']) if mission.get('plan') else None
    if 'steps' in mission:
        row['steps'] = [{k: s[k] for k in ('id', 'idx', 'ts', 'kind', 'name') if k in s}
                        for s in mission['steps']]
    return row


def stage_pending(mission):
    return any(s.get('state') in ('proposed', 'running', 'waiting_choice')
               for s in (mission.get('plan') or {}).get('stages', []))


def _refused(message='That phase is not current.'):
    return {'status': 'refused', 'message': message}


def _ask(mid, name, question, **details):
    from services import missions
    storage.add_mission_step(mid, {'kind': 'ask', 'name': name,
                                  'result_json': {'question': question, **details}})
    missions._close(mid, 'waiting_user')
    missions._dm_person(storage.get_mission(mid), question)


def _settle(mid, name, outcome):
    from services import missions
    ask = missions._pending_ask(mid, name)
    if ask:
        missions.settle_ask_cards(mid, ask['id'], outcome)


def _remaining(plan):
    return [q for q in plan['questions'] if q.get('answer') is None and not q.get('you_decide')]


def answer_plan(mission_id, answers, actor):
    from services import missions
    if (actor or {}).get('role') not in ('parent', 'adult'):
        return _refused('Only a parent or adult can answer these.')
    with storage.db_lock:
        mission = storage.get_mission(mission_id)
        plan = (mission or {}).get('plan')
        if (not plan or plan['state'] != 'interviewing' or mission.get('paused_by_project')
                or mission.get('status') in ('done', 'blocked', 'dropped')):
            return _refused()
        if not isinstance(answers, dict):
            return _refused('Answers must name the questions.')
        for q in plan['questions']:
            if q['key'] in answers:
                value = answers[q['key']]
                q.update(answer=None if value == 'you_decide' else value,
                         you_decide=value == 'you_decide', answered_by=actor.get('id'))
        remaining = len(_remaining(plan))
        missions._close(mission_id, 'waiting_user' if remaining else 'running', plan=plan)
        if not remaining:
            _settle(mission_id, 'interview', 'Answered')
    return {'status': 'success', 'message': 'Answers recorded.', 'remaining': remaining}


def _plan_for_change(mid, actor, rev=None):
    mission = storage.get_mission(mid)
    if not mission or not may_approve(mission, actor):
        return None, None, _refused('That plan is not yours to handle.')
    plan = mission.get('plan')
    if not plan or (rev is not None and plan['rev'] != rev):
        return None, None, _refused('The plan moved; look again.')
    if mission.get('status') in ('done', 'blocked', 'dropped'):
        return None, None, _refused('That mission has ended.')
    return mission, plan, None


RESHAPE = ('title', 'goal', 'done_when', 'target_date', 'body_goal', 'audience_rev')


def _project_for_plan(mission, proposed, actor):
    """Use the same project rules for the preview and the approval write."""
    from services import projects
    kind, pid, _ = missions.subject_of(mission)
    if kind == 'project':
        project = storage.get_project(pid)
        if not projects.can_act(project, actor):
            return None, 'You cannot edit this project'
        return project, None
    # Every mission lives in a project (front door §1). A person's project is
    # planned into as it stands; a wrapper takes the plan's content while
    # keeping its people, so approval never makes a second project.
    home = storage.get_project(mission.get('project_id')) if mission.get('project_id') else None
    if home and not projects.can_act(home, actor):
        return None, 'You cannot edit this project'
    if home and (not home.get('wrapped_from') or proposed is None):
        return home, None
    if proposed is None:
        return None, None  # Older plans can still run without a project proposal.
    if not isinstance(proposed, dict):
        return None, 'The project must be an object'
    fields = {k: proposed[k] for k in projects.EDITABLE if k in proposed}
    if 'owner' in proposed:
        fields['owner_member_id'] = proposed['owner']
    if 'body_goal' in proposed:
        fields['body_goal'] = proposed['body_goal']
    if home:
        # The planner never chooses people. Validate the final merged content
        # with the wrapper's existing owner and explicit list, not child defaults.
        fields.update({k: home.get(k) for k in ('owner_member_id', 'audience', 'shared_with')})
    # No ownership is being assigned on a reshape; its owner validates the
    # shape after the approver's can_act check above (a listed adult may approve).
    result = projects.prepare_create(fields, storage.get_member(home['owner_member_id']) if home else actor)
    if home and result.get('project'):
        shaped = {**result['project'], **{k: home.get(k) for k in ('owner_member_id', 'audience', 'shared_with')},
                  'id': home['id'], 'reshape': True}
        if home.get('body_goal'):
            # The pin is permanent (core spec §1): the same adult owner, private.
            if (shaped.get('audience') != 'private' or shaped.get('owner_member_id') != home.get('owner_member_id')
                    or shaped.get('shared_with') != [home.get('owner_member_id')]):
                return None, 'A body goal stays private to its adult owner'
            shaped['body_goal'] = True
        return shaped, None
    return result.get('project'), result.get('message')


def _project_steps(plan, mid):
    """Translate both kinds of local plan id into one project checklist."""
    rows = []
    for source in plan.get('steps', []):
        rows.append({**deepcopy(source), 'hold': None})
    for stage in plan['stages']:
        rows.append({'id': stage['id'], 'title': stage['title'], 'owner': 'argyle',
                     'goal': stage.get('goal') or stage['title'], 'needs': stage.get('needs') or [],
                     'mission_id': mid, 'stage_id': stage['id'], 'found': None, 'question': None,
                     'state': 'skipped' if stage['state'] == 'skipped' else 'todo'})
    ids = {row['id']: f"{mid}-{plan['rev']}-{row['id']}" for row in rows}
    return [{**row, 'id': ids[row['id']], 'needs': [ids[n] for n in row.get('needs', [])],
             'order': i, 'due_date': row.get('due_date'), 'state': row.get('state', 'todo'),
             'done_by': None, 'done_at': None} for i, row in enumerate(rows)]


def _complete_approval(mission, plan):
    """Replay the persisted write intent under db_lock, including after a crash."""
    from services import projects
    intent = plan.get('approval')
    mid = mission['id']
    if intent:
        pid = intent['project_id']
        project = storage.get_project(pid)
        if project is None:
            storage.add_project({**intent['project'], 'id': pid})
            project = storage.get_project(pid)
        steps = list(project.get('steps') or [])
        ids = {s['id'] for s in steps}
        order = max((s['order'] for s in steps), default=-1) + 1
        for step in _project_steps(plan, mid):
            if step['id'] not in ids:
                steps.append({**step, 'order': order})
                ids.add(step['id'])
                order += 1
        pieces = list(project.get('pieces') or [])
        earlier = intent.get('earlier_subject')
        if earlier and earlier['kind'] in projects.PIECE_HOME_KINDS:
            from services import access
            record = access.KINDS[earlier['kind']].load(earlier['id'])
            if not record or record.get('project_id') != pid:
                earlier = None
        if earlier and not any((p['kind'], p['id']) == (earlier['kind'], earlier['id']) for p in pieces):
            pieces.insert(0, {**earlier, 'added_by': plan['approved_by'], 'added_at': plan['approved_at']})
        patch = {'steps': steps, 'pieces': pieces,
                 'origin_mission_id': project.get('origin_mission_id') or mid}
        if intent.get('reshape'):
            # The wrapper becomes the plan's project, before the binding below
            # makes the record's subject this project.
            # Whitelist content even for an intent persisted by an older build:
            # approval and replay must never replace the wrapper's people.
            patch.update({k: v for k, v in intent['reshape'].items() if k in RESHAPE})
            patch['wrapped_from'] = None
        if any(project.get(k) != v for k, v in patch.items()):
            storage.update_project(pid, patch)
        binding = intent.get('binding')
        if binding:
            load, update = ((storage.get_thread, storage.update_thread) if binding['kind'] == 'thread'
                            else (storage.get_mission, storage.update_mission))
            row = load(binding['id'])
            if any(row.get(k) != v for k, v in binding['fields'].items()):
                update(binding['id'], binding['fields'])
                from services import project_audience
                project_audience.narrow_on_bind(binding['kind'], load(binding['id']))
    plan['state'] = 'approved'
    missions._close(mid, 'running', plan=plan)
    _settle(mid, 'plan', 'Looks good')


@missions._mission_work
def approve_plan(mission_id, rev, actor):
    from services import missions
    with storage.db_lock:
        mission, plan, error = _plan_for_change(mission_id, actor, rev)
        if error:
            return error
        if plan['state'] != 'proposed' or mission.get('paused_by_project'):
            return _refused()
        project, message = _project_for_plan(mission, plan.get('project'), actor)
        if message:
            return _refused(message)
        if project:
            from services import projects
            steps = _project_steps(plan, mission_id)
            for step in steps:
                message = projects._validate_step(project, step, steps)
                if message:
                    return _refused(message)
            pid = project.get('id') or f'prj-{mission_id}'
            intent = {'project_id': pid, 'project': project if not project.get('id') else None}
            if project.get('reshape'):
                intent['reshape'] = {k: project.get(k) for k in RESHAPE}
            kind, sid, _ = missions.subject_of(mission)
            if kind != 'project':
                row, binding_kind = mission, 'mission'
                if mission.get('origin_kind') == 'thread':
                    row, binding_kind = storage.get_thread(mission.get('origin_ref')), 'thread'
                if kind and sid:
                    intent['earlier_subject'] = {'kind': kind, 'id': sid}
                intent['binding'] = {'kind': binding_kind, 'id': row['id'], 'fields': {
                    'subject_kind': 'project', 'subject_id': pid,
                    'subject_rev': int(row.get('subject_rev') or 0) + 1,
                    'subject_history': subjects.history_after_binding(row, 'project', pid)}}
            plan['approval'] = intent
        plan.update(state='approving', approved_by=actor.get('id'), approved_at=time.time())
        storage.update_mission(mission_id, {'plan': plan})
        _complete_approval(mission, plan)
    return {'status': 'success', 'message': 'Plan approved.'}


def drop_stage(mission_id, rev, stage_id, actor):
    with storage.db_lock:
        mission, plan, error = _plan_for_change(mission_id, actor, rev)
        if error:
            return error
        stage = next((s for s in plan['stages'] if s['id'] == stage_id), None)
        if plan['state'] != 'proposed' or not stage or stage['state'] != 'pending':
            return _refused()
        stage['state'] = 'skipped'
        plan['rev'] += 1
        storage.update_mission(mission_id, {'plan': plan})
    return {'status': 'success', 'message': 'Stage left out.'}


def cancel_for_delete(mission_id):
    """Admission already authorized the deletion; stopping needs no plan approval."""
    with storage.db_lock:
        mission = storage.get_mission(mission_id) or {}
        plan = mission.get('plan')
        _cancel_program_choices(mission)
        if not plan:
            if mission:
                storage.update_mission(mission_id, {'program_choices': mission.get('program_choices', [])})
            return
        plan['state'] = 'stopped'
        for stage in plan.get('stages', []):
            _dismiss_rows(stage)
            if stage.get('state') == 'running':
                stage.update(state='skipped', outcome='stop')
        storage.update_mission(mission_id, {'plan': plan, 'program_choices': mission.get('program_choices', [])})
        storage.set_app_state(f'mission_steer:{mission_id}', {'text': 'Stopped', 'ts': time.time()})
        for name in ('plan', 'stage', 'stage_check'):
            _settle(mission_id, name, 'Stopped')


def stop_plan(mission_id, actor):
    with storage.db_lock:
        mission, plan, error = _plan_for_change(mission_id, actor)
        if error:
            return error
        for stage in plan['stages']:
            if stage['state'] == 'running' and stage['kind'] == 'work':
                cancel_stage(mission_id, stage['id'], actor, 'stop')
        # Cancellation wrote a fresh plan. A build runner may still own its
        # current row, but must see stopped before claiming the next one.
        plan = storage.get_mission(mission_id)['plan']
        plan['state'] = 'stopped'
        current = storage.get_mission(mission_id)
        current['plan'] = plan
        _cancel_program_choices(current)
        for stage in plan['stages']:
            _dismiss_rows(stage)
        storage.update_mission(mission_id, {'plan': plan, 'program_choices': current.get('program_choices', [])})
        _settle(mission_id, 'plan', 'Stopped')
        _settle(mission_id, 'stage', 'Stopped')
        _settle(mission_id, 'stage_check', 'Stopped')
        from services import missions
        missions._close(mission_id, 'dropped')
    return {'status': 'success', 'message': 'Stopped.'}


def cancel_stage(mission_id, stage_id, actor, outcome):
    """Cancel work without letting its in-flight results revive it."""
    from services import projects
    with storage.db_lock:
        mission, plan, error = _plan_for_change(mission_id, actor)
        if error:
            return error
        stage = next((s for s in plan['stages'] if s['id'] == stage_id), None)
        if (outcome not in ('skip', 'stop') or plan['state'] != 'approved'
                or not stage or stage['kind'] != 'work' or stage['state'] != 'running'):
            return _refused()
        stage['state'] = 'skipped'
        stage['outcome'] = outcome
        _dismiss_followups(plan, stage_id)
        storage.update_mission(mission_id, {'plan': plan})
        storage.set_app_state(f'mission_steer:{mission_id}', {'text': 'Stopped', 'ts': time.time()})
        for ask in storage.get_mission_steps(mission_id):
            if ask.get('kind') == 'ask':
                missions.settle_ask_cards(mission_id, ask['id'], 'Stopped')
        missions._close(mission_id, 'running')
        projects.on_stage_cancelled(mission_id, stage_id, outcome)
    return {'status': 'success', 'message': 'Stage skipped.' if outcome == 'skip' else 'Stopped.'}


def work_is_current(mission_id, stage_id=None, pause_rev=None):
    """Recheck captured work after a model, browse or research call returns."""
    mission = storage.get_mission(mission_id) or {}
    plan = mission.get('plan') or {}
    if (not mission or mission.get('status') in missions.TERMINAL
            or mission.get('paused_by_project') or plan.get('state') == 'stopped'
            or (pause_rev is not None and int(mission.get('project_pause_rev') or 0) != pause_rev)):
        return False
    if stage_id is None:
        return True
    return plan.get('state') == 'approved' and any(
        s['id'] == stage_id and s['state'] == 'running' for s in plan.get('stages', []))


def _dismiss_rows(stage, status='dismissed'):
    for row in stage.get('rows', []):
        if row.get('state') == 'running':
            continue  # A stopped build finishes the row it already claimed.
        pid = row.get('proposal_id')
        prop = storage.get_action_proposal(pid) if pid else None
        if prop and prop.get('status') in ('proposed', 'waiting_choice'):
            storage.update_action_proposal(pid, {'status': status})
        if row.get('state') == 'waiting_choice':
            row['state'] = 'excluded'


def _cancel_program_choices(mission):
    if not mission:
        return
    for ask in storage.get_mission_steps(mission['id']):
        if ask.get('kind') == 'ask' and ask.get('name') == 'program_choice':
            _, row = program_choice_for(mission, (ask.get('result_json') or {}).get('choice_id'))
            if row and row.get('state') == 'waiting_choice':
                missions.settle_ask_cards(mission['id'], ask['id'], 'Stopped')
    for stage in (mission.get('plan') or {}).get('stages', []):
        continuation = stage.pop('continue_after_choice', False)
        if stage.get('state') == 'waiting_choice' or continuation:
            stage.update(state='skipped', outcome='stop')
        _dismiss_rows(stage)
    _dismiss_rows({'rows': mission.get('program_choices') or []})


def _dismiss_followups(plan, stage_id):
    for follow in plan['stages']:
        if follow.get('parent') == stage_id:
            _dismiss_rows(follow)
            follow['state'] = 'skipped'
            for row in follow.get('rows', []):
                row['state'] = 'excluded'


def steer_stage(mission_id, stage_id):
    """Withdraw an unapproved stage so the next offer needs fresh approval."""
    from services import missions
    with storage.db_lock:
        mission = storage.get_mission(mission_id) or {}
        plan = mission.get('plan') or {}
        stage = next((s for s in plan.get('stages', []) if s['id'] == stage_id), None)
        if mission.get('status') not in missions.ATTENTION or not stage or stage['state'] != 'proposed':
            return False
        _dismiss_rows(stage, status='withdrawn')
        stage.update(state='pending', rows=[], snapshot=None)
        _settle(mission_id, 'stage', 'Changed')
        missions._close(mission_id, 'running', plan=plan)
    return True


def _stage_for_change(mid, stage_id, snap, actor):
    mission, plan, error = _plan_for_change(mid, actor)
    if error:
        return None, None, None, error
    if mission.get('paused_by_project'):
        return None, None, None, _refused('Resume the project first.')
    stage = next((s for s in plan['stages'] if s['id'] == stage_id), None)
    if not stage or stage.get('snapshot') != snap:
        return None, None, None, {'status': 'success', 'moved': True, 'message': 'The stage moved; look again.'}
    return mission, plan, stage, None


def can_resume_stage(stage):
    if any(r.get('state') == 'waiting_choice' for r in stage.get('rows', [])):
        return False
    if stage.get('state') == 'uncertain':
        return True  # Even an all-uncertain stage needs a way to carry on.
    if stage.get('state') != 'partial':
        return False
    return (stage.get('kind') == 'work'
            or stage.get('paused_by_project')
            or any(r['state'] == 'proposed' or
                   (r['state'] == 'failed' and (r.get('result') or {}).get('budget') is True)
                   for r in stage.get('rows', [])))


@missions._mission_work
def resume_stage(mission_id, stage_id, snap, actor):
    from services import missions
    with storage.db_lock:
        mission, plan, stage, error = _stage_for_change(mission_id, stage_id, snap, actor)
        if error:
            return error
        if plan['state'] != 'approved' or not can_resume_stage(stage) or stage_pending(mission):
            return _refused()
        if ((stage['state'] == 'uncertain' and not any(r['state'] == 'proposed' for r in stage.get('rows', [])))
                or (stage.get('paused_by_project') and all(
                    r['state'] in ('done', 'excluded', 'skipped', 'uncertain') for r in stage.get('rows', [])))):
            stage['state'] = 'done'
            stage.pop('paused_by_project', None)
            missions._close(mission_id, 'running', plan=plan)
            from services import projects
            projects.on_stage_done(mission_id, stage_id, {'summary': '; '.join(
                r['summary'] for r in stage.get('rows', []) if r['state'] == 'done')})
            _settle(mission_id, 'stage_check', 'Carry on')
            return {'status': 'success', 'message': 'Stage done; carrying on.'}
        if stage['kind'] == 'work':
            stage['steps_used'] = 0
            stage.pop('budget_ask_pending', None)
        for row in stage.get('rows', []):
            if row['state'] == 'failed' and (row.get('result') or {}).get('budget') is True:
                row['state'] = 'proposed'
                row.pop('result', None)
                if row.get('proposal_id'):
                    storage.update_action_proposal(row['proposal_id'], {'status': 'proposed', 'result': None})
        stage['state'] = 'proposed'
        stage.pop('paused_by_project', None)
        stage['subject'] = list(missions.subject_of(mission))
        # Even unchanged inputs need fresh approval after a partial attempt.
        plan['rev'] += 1
        stage['snapshot'] = snapshot(stage, stage['subject'], plan['rev'])
        storage.update_mission(mission_id, {'plan': plan})
        _settle(mission_id, 'stage', 'Carry on')
        _settle(mission_id, 'stage_check', 'Carry on')
        _ask(mission_id, 'stage', stage['title'], stage_id=stage_id)
    return {'status': 'success', 'message': 'Stage ready to carry on.'}


def exclude_row(mission_id, stage_id, snap, row_id, actor):
    with storage.db_lock:
        mission, plan, stage, error = _stage_for_change(mission_id, stage_id, snap, actor)
        if error:
            return error
        row = next((r for r in stage.get('rows', []) if r['id'] == row_id), None)
        if stage['state'] != 'proposed' or not row or row['state'] != 'proposed':
            return _refused()
        row['state'] = 'excluded'
        _dismiss_rows({'rows': [row]})
        stage['snapshot'] = snapshot(stage, stage['subject'], plan['rev'])
        storage.update_mission(mission_id, {'plan': plan})
        _ask(mission_id, 'stage', stage['title'], stage_id=stage_id)
    return {'status': 'success', 'message': 'Row left out.'}


def skip_stage(mission_id, stage_id, snap, actor):
    from services import missions
    with storage.db_lock:
        mission, plan, stage, error = _stage_for_change(mission_id, stage_id, snap, actor)
        if error:
            return error
        if stage['state'] == 'running':
            return cancel_stage(mission_id, stage_id, actor, 'skip')
        if stage['state'] != 'proposed' and not can_resume_stage(stage):
            return _refused()
        stage['state'] = 'skipped'
        _dismiss_rows(stage)
        _dismiss_followups(plan, stage_id)
        missions._close(mission_id, 'running', plan=plan)
        _settle(mission_id, 'stage', 'Not this one')
        _settle(mission_id, 'stage_check', 'Not this one')
        from services import projects
        projects.on_stage_cancelled(mission_id, stage_id, 'skip')
    return {'status': 'success', 'message': 'Stage skipped.'}


def planner_action(mid, action):
    """Admit a planner action against the current persisted phase."""
    from services import missions, occasions
    with storage.db_lock:
        mission = storage.get_mission(mid)
        plan = mission.get('plan')
        name = action['action']
        if mission['status'] not in missions.RUNNABLE:
            return _refused()
        if name == 'interview':
            if plan:
                return _refused()
            template = action.get('template')
            kind, sid, _ = missions.subject_of(mission)
            if kind == 'occasion':
                template_questions = (occasions.interview(sid).get('questions') or [])
            elif template:
                if template not in occasions.TEMPLATES:
                    return _refused('Unknown interview template.')
                template_questions = occasions.TEMPLATES[template]['questions']
            else:
                template_questions = []
            questions = []
            for source, items in [('template', template_questions), ('planner', action.get('questions') or [])]:
                for q in items:
                    if not isinstance(q, dict) or not q.get('key') or not q.get('ask'):
                        return _refused('Each question needs a key and wording.')
                    if any(old['key'] == q['key'] for old in questions):
                        continue
                    ask = occasions._ASK.get(q['key'], (q['ask'], None))[0] if source == 'template' else q['ask']
                    questions.append({'key': q['key'], 'ask': ask, 'kind': q.get('kind', 'text'),
                                      'choices': q.get('choices') or [], 'why': q.get('why') or '',
                                      'source': source, 'template_key': q['key'] if source == 'template' else None,
                                      'answer': None, 'you_decide': False, 'answered_by': None})
            if len(questions) > CAPS['questions'] * CAPS['rounds']:
                return _refused('Too many interview questions.')
            plan = new_plan()
            plan['questions'] = questions
            storage.update_mission(mid, {'plan': plan})
            _ask(mid, 'interview', 'A few questions before I make the plan.')
        elif name == 'answers':
            if not plan or plan['state'] != 'interviewing':
                return _refused()
            steps = storage.get_mission_steps(mid)
            latest_ask = next((s['idx'] for s in reversed(steps) if s['kind'] == 'ask'), -1)
            answer = next((s for s in reversed(steps) if s['name'] == 'user_answer' and s['idx'] > latest_ask), None)
            actor_id = ((answer or {}).get('result_json') or {}).get('answered_by') or mission.get('created_by')
            result = answer_plan(mid, action.get('values') or {}, {'id': actor_id, 'role': 'adult'})
            if result.get('remaining'):
                _ask(mid, 'interview', 'A few questions remain before I make the plan.')
            return result
        elif name == 'plan':
            if not plan or plan['state'] not in ('interviewing', 'proposed') or _remaining(plan):
                return _refused()
            stages = action.get('stages')
            if not isinstance(stages, list) or not stages or len(stages) > CAPS['stages']:
                return _refused('The plan needs one to seven stages.')
            seen, reserve = set(), 2
            for stage in stages:
                if (not isinstance(stage, dict) or not isinstance(stage.get('id'), str)
                        or not stage['id'].strip() or stage['id'] in seen
                        or stage.get('kind') not in ('build', 'work') or not stage.get('title')):
                    return _refused('Each stage needs a unique id, kind and title.')
                seen.add(stage['id'])
                if stage['kind'] == 'work':
                    budget = stage.get('step_budget')
                    if type(budget) is not int or not 1 <= budget <= CAPS['work_steps'] or not stage.get('goal'):
                        return _refused('A work stage needs a goal and a bounded step budget.')
                    reserve += budget + 1
                else:
                    reserve += 1
            cap = int(storage.get_settings().get('mission_step_cap', missions.CAPS_DEFAULT['steps']))
            if cap - int(mission.get('step_count') or 0) < reserve:
                return _refused('The remaining step budget cannot cover this plan.')
            person_steps = action.get('steps', [])
            if not isinstance(person_steps, list):
                return _refused('Steps must be a list.')
            for step in person_steps:
                if (not isinstance(step, dict) or not isinstance(step.get('id'), str)
                        or not step['id'].strip() or step['id'] in seen or step.get('owner') == 'argyle'):
                    return _refused('Each person step needs a unique id and a person as owner.')
                seen.add(step['id'])
            graph = {s['id']: s.get('needs', []) for s in stages + person_steps}
            if any(not isinstance(needs, list) or any(not isinstance(n, str) or n not in graph for n in needs)
                   for needs in graph.values()):
                return _refused('Needs must name steps or stages in this plan.')
            visiting, visited = set(), set()

            def cycle(sid):
                if sid in visiting:
                    return True
                if sid in visited:
                    return False
                visiting.add(sid)
                if any(cycle(n) for n in graph[sid]):
                    return True
                visiting.remove(sid)
                visited.add(sid)
                return False

            if any(cycle(sid) for sid in graph):
                return _refused('Plan dependencies cannot form a cycle.')
            stage_order = {stage['id']: index for index, stage in enumerate(stages)}

            def needs_later(sid, index):
                return any(stage_order.get(dep, -1) > index or needs_later(dep, index)
                           for dep in graph[sid])

            if any(needs_later(stage['id'], index) for index, stage in enumerate(stages)):
                return _refused('A stage cannot need a later stage, even through a person step. Reorder the plan.')
            actor = missions._finder(mission) or {}
            project, message = _project_for_plan(mission, action.get('project'), actor)
            if message:
                return _refused(message)
            if person_steps and not project:
                return _refused('Person steps need a proposed or existing project.')
            candidate = {**plan, 'rev': plan['rev'] + 1,
                         'stages': [{k: deepcopy(s.get(k)) for k in (
                             'id', 'kind', 'title', 'why', 'makes', 'owner_member_id', 'goal', 'step_budget')}
                             | {'needs': list(graph[s['id']]), 'state': 'pending'} for s in stages],
                         'steps': [{k: deepcopy(s.get(k)) for k in ('id', 'title', 'owner', 'due_date')}
                                   | {'needs': list(graph[s['id']])} for s in person_steps]}
            from services import projects
            translated = _project_steps(candidate, mid)
            for step in translated:
                message = projects._validate_step(project or {}, step, translated)
                if message:
                    return _refused(message)
            candidate['project'] = None
            if project:
                # A wrapper to reshape keeps the whole proposed shape, as a new project does.
                existing = project.get('id') and not project.get('reshape')
                keys = (('id', 'title', 'goal', 'done_when') if existing else
                        ('title', 'goal', 'done_when', 'audience', 'shared_with', 'target_date'))
                candidate['project'] = {k: project.get(k) for k in keys}
                if not existing:
                    candidate['project']['owner'] = project['owner_member_id']
                candidate['project']['audience_label'] = projects.audience_label(project)
            plan = candidate
            plan['state'] = 'proposed'
            storage.update_mission(mid, {'plan': plan})
            _ask(mid, 'plan', 'Does this plan look good?')
        elif name == 'stage':
            return propose_stage(mid, action.get('stage_id'), action.get('rows'))
        else:
            return _refused()
    return {'status': 'success', 'message': 'Recorded.'}


def propose_stage(mission_id, stage_id, rows):
    from services import missions, chat_actions
    with storage.db_lock:
        mission = storage.get_mission(mission_id)
        plan = (mission or {}).get('plan')
        if not plan or mission['status'] not in missions.RUNNABLE or plan['state'] != 'approved' or stage_pending(mission):
            return _refused()
        stage = next((s for s in plan['stages'] if s['state'] == 'pending'), None)
        if not stage or stage['id'] != stage_id or stage['kind'] != 'build':
            return _refused('Only the next pending build stage can propose rows.')
        if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
            return _refused('A stage needs rows.')
        error = check_rows(rows) or _check_row_order(rows)
        if error:
            return _refused(error)
        stage['rows'] = [{k: r.get(k) for k in ('id', 'tool', 'args', 'summary')}
                         | {'state': 'proposed', 'needs': r.get('needs') or [],
                            'resumable': CONTRACT[r['tool']]['idem']} for r in rows]
        stage['subject'] = list(missions.subject_of(mission))
        stage['snapshot'] = snapshot(stage, stage['subject'], plan['rev'])
        for row in stage['rows']:
            if CONTRACT[row['tool']]['idem']:
                row['idem'] = hashlib.sha256(json.dumps([mission_id, stage_id, row['id'], stage['snapshot']]).encode()).hexdigest()
            if row['tool'] != 'draft_message':
                prop = chat_actions.create_action_proposal(
                    row['tool'], row['summary'], row['args'], created_by_member_id=mission.get('created_by'),
                    extra_allowed=missions.proposable_tools(),
                    extra={'origin_kind': 'mission', 'origin_id': mission_id, 'stage_id': stage_id, 'row_id': row['id']})
                if prop['status'] != 'success':
                    _dismiss_rows(stage)
                    return _refused(prop['message'])
                row['proposal_id'] = prop['proposal_id']
        stage['state'] = 'proposed'
        storage.update_mission(mission_id, {'plan': plan})
        _ask(mission_id, 'stage', stage['title'], stage_id=stage_id)
    return {'status': 'success', 'message': 'Stage proposed.'}


def running_work(mission):
    return next((s for s in (mission.get('plan') or {}).get('stages', [])
                 if s['kind'] == 'work' and s['state'] == 'running'), None)


def _propose_work(mid, mission, plan, stage, question=None):
    from services import missions
    stage.update(state='proposed', subject=list(missions.subject_of(mission)))
    stage['snapshot'] = snapshot(stage, stage['subject'], plan['rev'])
    storage.update_mission(mid, {'plan': plan})
    _ask(mid, 'stage', question or stage['title'], stage_id=stage['id'])


def _offer_followup(mid, mission, stage):
    from services import missions
    cap = int(storage.get_settings().get('mission_step_cap', missions.CAPS_DEFAULT['steps']))
    if cap - int(mission.get('step_count') or 0) < 1 + 2:
        _ask(mid, 'budget', 'Please raise the step cap, or stop here. Queued writes: '
             + '; '.join(r['summary'] for r in stage['rows']))
        return {'status': 'success', 'message': 'Waiting for more step budget.'}
    return propose_stage(mid, stage['id'], stage['rows'])


def prepare_next(mid):
    """Offer known stages before spending a planner call."""
    with storage.db_lock:
        mission = storage.get_mission(mid)
        plan = mission.get('plan') or {}
        continuation = next((s for s in plan.get('stages', []) if s.get('continue_after_choice')
                             and (mid, s['id']) not in _active_stages), None)
        if continuation:
            _recover_choice_continuation(mission, continuation)
            return True
        if mission['status'] not in missions.RUNNABLE or plan.get('state') != 'approved':
            return False
        if mission.get('interaction') == 'voice':
            for stage in plan.get('stages', []):
                for row in stage.get('rows', []):
                    result = row.get('result') or {}
                    if row.get('state') == 'done' and result.get('notice') and not result.get('notice_sent'):
                        # Use the mission notice path: its typed refs survive the
                        # queue and are checked again at actual delivery.
                        from services import access
                        run = storage.get_program(result.get('run_id'))
                        with storage.db.transaction():
                            if run and not access.gone('program', run):
                                missions._dm_person(mission, result['notice'])
                            result['notice_sent'] = True
                            storage.update_mission(mid, {'plan': plan})
        if any(key[0] == mid for key in _active_stages):
            return True  # A resumed mission still has a build row in flight.
        stage = next((s for s in plan['stages'] if s['state'] not in ('done', 'skipped')), None)
        if not stage:
            return False
        if stage['state'] == 'waiting_choice':
            _offer_program_choice(mid, stage)
            return True
        if stage.get('paused_by_project') and stage['state'] == 'partial':
            _ask(mid, 'stage', 'Partly done; carry on?', stage_id=stage['id'])
            return True
        if stage.get('paused_by_project') and stage['state'] == 'uncertain':
            _ask(mid, 'stage_check', 'Please check what happened before carrying on.', rows=[
                {'stage_id': stage['id'], 'row_id': r['id'], 'summary': r.get('summary')}
                for r in stage.get('rows', []) if r['state'] == 'uncertain'])
            return True
        if stage['state'] == 'pending':
            from services import projects
            kind, pid, _ = missions.subject_of(mission)
            if kind == 'project':
                step = projects.step_for_stage(pid, mid, stage['id'])
                if step and not projects.needs_satisfied(storage.get_project(pid), step):
                    missions._close(mid, 'waiting_step')
                    return True
        if stage['state'] == 'pending' and stage['kind'] == 'work':
            stage.update(state='running', steps_used=0, subject=list(missions.subject_of(mission)))
            stage['snapshot'] = snapshot(stage, stage['subject'], plan['rev'])
            storage.update_mission(mid, {'plan': plan})
            projects.on_stage_started(mid, stage['id'])
            return True
        if stage['state'] == 'pending' and stage.get('parent') and stage.get('rows'):
            result = _offer_followup(mid, mission, stage)
            if result['status'] != 'success':
                storage.add_mission_step(mid, {'kind': 'note', 'name': 'refused',
                                              'result_json': {'note': result['message']}})
            return result['status'] == 'success'
        return False


def queue_row(mid, action, viewer=None):
    """Keep work-stage writes behind one later build approval."""
    with storage.db_lock:
        mission = storage.get_mission(mid)
        if viewer is not None:
            from services import access
            if not access.record_actable('mission', mission, viewer, 'run_stage'):
                return _refused('No such mission')
        work = running_work(mission)
        if not work:
            return _refused()
        plan = mission['plan']
        follow = next((s for s in plan['stages'] if s.get('parent') == work['id']), None)
        rows = follow['rows'] if follow else []
        row_id = action.get('row_id')
        if not isinstance(row_id, str) or not row_id:
            used = {r['id'] for r in rows}
            index = len(rows) + 1
            while f'r{index}' in used:
                index += 1
            row_id = f'r{index}'
        row = {'id': row_id,
               'tool': action.get('tool'), 'args': action.get('args') or {},
               'summary': action.get('summary') or action.get('why') or action.get('tool'),
               'needs': action.get('needs') or []}
        error = check_rows([*rows, row]) or _check_row_order([*rows, row])
        if error:
            return _refused(error)
        if follow is None:
            follow = {'id': f"{work['id']}-build", 'kind': 'build', 'parent': work['id'],
                      'title': f"Do what {work['title']} found", 'why': '', 'makes': [],
                      'state': 'pending', 'rows': []}
            if any(s['id'] == follow['id'] for s in plan['stages']):
                return _refused('The follow-up stage id is already in use.')
            plan['stages'].insert(plan['stages'].index(work) + 1, follow)
        follow['rows'].append(row)
        follow['makes'].append(row['summary'])
        storage.update_mission(mid, {'plan': plan})
    return {'status': 'success', 'message': 'Queued for the follow-up build.'}


def finish_work(mid, action):
    with storage.db_lock:
        mission = storage.get_mission(mid)
        stage = running_work(mission)
        if (not stage or stage['id'] != action.get('stage_id')
                or not work_is_current(mid, stage['id'])):
            return _refused('Only the running work stage can finish.')
        stage.update(state='done', summary=action.get('summary') or '', found=action.get('found') or {})
        storage.update_mission(mid, {'plan': mission['plan']})
        from services import projects
        projects.on_stage_done(mid, stage['id'], stage['found'])
        follow = next((s for s in mission['plan']['stages'] if s.get('parent') == stage['id']), None)
        if follow and follow.get('rows'):
            return _offer_followup(mid, storage.get_mission(mid), follow)
    return {'status': 'success', 'message': 'Work stage done.'}


def pause_bound_work(mid, title):
    with storage.db_lock:
        mission = storage.get_mission(mid)
        stage = running_work(mission)
        if stage:
            _propose_work(mid, mission, mission['plan'], stage, f'Now about {title} — go on?')


def check_work_budget(mid, exhausted=False):
    """Pause spent work; let an existing browse or question finish before asking."""
    with storage.db_lock:
        mission = storage.get_mission(mid)
        stage = next((s for s in (mission.get('plan') or {}).get('stages', [])
                      if s['kind'] == 'work' and (s['state'] == 'running'
                          or (s['state'] == 'partial' and s.get('budget_ask_pending')))), None)
        if (not stage or (not exhausted and stage.get('steps_used', 0) < stage['step_budget'])
                or mission['status'] in ('done', 'blocked', 'dropped') or mission.get('paused_by_project')):
            return False
        stage['budget_ask_pending'] = mission['status'] not in missions.RUNNABLE
        # Keep in-flight work running until its browse/question has landed.
        # The next runnable step parks it before another planner call.
        if not stage['budget_ask_pending']:
            stage['state'] = 'partial'
        storage.update_mission(mid, {'plan': mission['plan']})
        if stage['budget_ask_pending']:
            return False
        _ask(mid, 'stage', 'Partly done; carry on?', stage_id=stage['id'])
        return True


def _resolve_refs(value, completed):
    def resolve(item):
        if isinstance(item, dict):
            if '$ref' in item:
                row = completed.get(item['$ref']) or {}
                found = [c['id'] for c in (row.get('result') or {}).get('created', [])
                         if c.get('kind') == item.get('kind')] if row.get('state') == 'done' else []
                if not found:
                    raise ValueError(f"No created {item.get('kind')} from {item['$ref']}.")
                return found if item.get('all') is True else found[0]
            return {k: resolve(v) for k, v in item.items()}
        if isinstance(item, list):
            return [resolve(v) for v in item]
        return item

    return resolve(value)


def _row_dependencies(row):
    """A reference also waits for its producer when `needs` was omitted."""
    dependencies = set(row.get('needs') or [])

    def walk(value):
        if isinstance(value, dict):
            if '$ref' in value:
                dependencies.add(value['$ref'])
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(row.get('args') or {})
    return dependencies


def _bind_created(mid, created):
    """Bind a created subject; return (kind, id) to narrow under the row writer's lock."""
    from services import missions
    mission = storage.get_mission(mid)
    kind, pid, _ = missions.subject_of(mission)
    if kind == 'project':
        with storage.db_lock:
            project = storage.get_project(pid)
            if not project:
                return
            pieces = list(project.get('pieces') or [])
            seen = {(p['kind'], p['id']) for p in pieces}
            for record in created:
                key = (record.get('kind'), record.get('id'))
                if (key[0] in subjects.KINDS and key[1] and key not in seen
                        and key != ('project', pid)):
                    pieces.append({'kind': key[0], 'id': key[1], 'added_by': 'argyle', 'added_at': time.time()})
                    seen.add(key)
            if pieces != project.get('pieces'):
                storage.update_project(pid, {'pieces': pieces})
        return
    if kind:
        return
    record = next((c for c in created if c.get('kind') in ('occasion', 'trip', 'list', 'program', 'thread')
                   and subjects.load(c['kind'], c.get('id')) is not None), None)
    if not record:
        return
    row, update = mission, storage.update_mission
    if mission.get('origin_kind') == 'thread':
        row = storage.get_thread(mission.get('origin_ref'))
        update = storage.update_thread
    if row and not row.get('subject_kind'):
        update(row['id'], {'subject_kind': record['kind'], 'subject_id': record['id'],
                          'subject_rev': int(row.get('subject_rev') or 0) + 1,
                          'subject_history': subjects.history_after_binding(row, record['kind'], record['id'])})
        bound_kind = 'thread' if mission.get('origin_kind') == 'thread' else 'mission'
        return bound_kind, row['id']


def _offer_program_choice(mid, stage):
    row = next(r for r in stage['rows'] if r['state'] == 'waiting_choice')
    result = row['result']
    pending = missions._pending_ask(mid, 'program_choice')
    if pending and (pending.get('result_json') or {}).get('choice_id') == result['choice_id']:
        if storage.get_mission(mid).get('status') != 'waiting_user':
            missions._close(mid, 'waiting_user')
        return
    _ask(mid, 'program_choice', result['message'], choice_id=result['choice_id'],
         stage_id=stage.get('id'), row_id=row['id'])


def record_program_choice(proposal, result):
    """A standalone proposal uses the same mission ask and answer transaction."""
    mid = proposal['origin_id']
    mission = storage.get_mission(mid)
    rows = mission.setdefault('program_choices', [])
    if not any(r['state'] == 'waiting_choice' for r in rows):
        previous = next((s for s in reversed(storage.get_mission_steps(mid)) if s.get('kind') == 'ask'), None)
        mission['program_choice_resume'] = {'status': mission['status'],
            'ask': {k: previous[k] for k in ('name', 'result_json')} if previous else None}
    if not any(r['proposal_id'] == proposal['id'] for r in rows):
        rows.append({'id': proposal['id'], 'proposal_id': proposal['id'],
                     'state': 'waiting_choice', 'result': result})
    storage.update_mission(mid, {'program_choices': rows, 'program_choice_resume': mission.get('program_choice_resume')})
    _offer_program_choice(mid, {'rows': rows})


def program_choice_for(mission, choice_id):
    for stage in (mission.get('plan') or {}).get('stages', []):
        for row in stage.get('rows', []):
            if (row.get('result') or {}).get('choice_id') == choice_id:
                return stage, row
    for row in mission.get('program_choices') or []:
        if (row.get('result') or {}).get('choice_id') == choice_id:
            return None, row
    return None, None


def _recover_choice_continuation(mission, stage):
    """Restore an actionable ask after an answered choice, without repeating a write."""
    if mission.get('paused_by_project') or (mission.get('plan') or {}).get('state') != 'approved':
        return
    with storage.db_lock, storage.db.transaction():
        mid = mission['id']
        stage.pop('continue_after_choice', None)
        if any(r['state'] == 'waiting_choice' for r in stage['rows']):
            stage['state'] = 'waiting_choice'
            storage.update_mission(mid, {'plan': mission['plan']})
            _offer_program_choice(mid, stage)
            return
        uncertain = [{'stage_id': stage['id'], 'row_id': r['id'], 'summary': r.get('summary')}
                     for r in stage['rows'] if r['state'] == 'uncertain']
        if uncertain:
            stage['state'] = 'uncertain'
            storage.update_mission(mid, {'plan': mission['plan']})
            _ask(mid, 'stage_check', 'Please check what happened before carrying on.', rows=uncertain)
        else:
            stage.update(state='proposed', subject=list(missions.subject_of(mission)))
            stage['snapshot'] = snapshot(stage, stage['subject'], mission['plan']['rev'])
            storage.update_mission(mid, {'plan': mission['plan']})
            _ask(mid, 'stage', stage['title'], stage_id=stage['id'])


def _continue_program_choice(mid, stage_id):
    with storage.db_lock:
        mission = storage.get_mission(mid)
        stage = next(s for s in mission['plan']['stages'] if s['id'] == stage_id)
        if any(r['state'] == 'uncertain' for r in stage['rows']):
            _recover_choice_continuation(mission, stage)
            return {'status': 'success', 'message': 'Please check what happened before carrying on.'}
        approver = storage.get_member(mission['plan'].get('approved_by'))
        snap = stage['snapshot']
    continued = run_stage(mid, stage_id, snap, approver)
    if continued.get('status') != 'success' or continued.get('moved'):
        with storage.db_lock:
            mission = storage.get_mission(mid)
            stage = next(s for s in mission['plan']['stages'] if s['id'] == stage_id)
            if stage.get('continue_after_choice'):
                _recover_choice_continuation(mission, stage)
    return continued


def may_answer_program_choice(mission, choice_id, actor):
    from services import access
    if not actor or not actor.get('id') or not access._active(actor):
        return False
    if not mission or access.gone('mission', mission):
        return False
    _, row = program_choice_for(mission, choice_id)
    choice = ((row or {}).get('result') or {}).get('choice') or {}
    if actor.get('role') == 'child':
        # This grants only the child's own program choice, never the mission
        # transcript or the parent's other stage approvals.
        return bool(row and mission.get('created_by') == actor['id']
                    and choice.get('created_by') == actor['id'] and choice.get('member_id') == actor['id']
                    and access.project_visible(access.home_project(mission), actor)
                    and all(subjects.visible(k, r, actor) for k, r in subjects.subject_records('mission', mission)))
    return bool(row and access.record_view('mission', mission, actor) is not None and may_approve(mission, actor))


@missions._mission_work
def answer_program_choice(mid, choice_id, option, actor):
    """Commit the run, adoption, choice binding and row outcome together."""
    from services import agent_tools_v2, library, budget_guard, project_audience, situations
    if option not in ('use', 'make_new', 'not_now'):
        return _refused('Choose Use, Make new, or Not now.')
    prepared = None
    with storage.db_lock:
        mission = storage.get_mission(mid)
        if not may_answer_program_choice(mission, choice_id, actor):
            return _refused('That choice is not yours to handle.')
        _, row = program_choice_for(mission, choice_id)
        if (row.get('result') or {}).get('run_id') or row['state'] == 'failed':
            return {'status': 'success', 'already': True, 'run_id': row['result'].get('run_id')}
        choice = row['result']['choice']
        stage, _ = program_choice_for(mission, choice_id)
        if (mission.get('paused_by_project') or
                stage is not None and (mission.get('plan') or {}).get('state') != 'approved'):
            return _refused('That choice is no longer open.')
    if option == 'make_new':
        if actor.get('role') not in ('adult', 'parent'):
            return _refused(library.EDIT_REFUSAL)
        try:
            with budget_guard.guard():
                prepared = library.prepare(choice['profile'], actor)
        except deletion.Cancelled:
            raise
        except Exception as exc:
            return {'status': 'error', 'message': str(exc)}
        if prepared.get('status') != 'success':
            return prepared
    continuation_key = None
    try:
        with storage.db_lock, storage.db.transaction():
            mission = storage.get_mission(mid)
            if not may_answer_program_choice(mission, choice_id, actor):
                return _refused('That choice is not yours to handle.')
            stage, row = program_choice_for(mission, choice_id)
            result = row['result']
            if result.get('run_id') or row['state'] == 'failed':
                return {'status': 'success', 'already': True, 'run_id': result.get('run_id')}
            if (mission.get('paused_by_project') or row['state'] != 'waiting_choice'
                    or stage is not None and (mission.get('status') in missions.TERMINAL
                        or (mission.get('plan') or {}).get('state') != 'approved')
                    or stage is None and mission.get('status') in ('blocked', 'dropped')):
                return _refused('Resume the project first.' if mission.get('paused_by_project') else 'That choice is no longer open.')
            if option == 'not_now':
                outcome = {'status': 'error', 'message': 'No program for now', 'created': []}
            else:
                outcome = agent_tools_v2._start_program_choice(result['choice'], actor,
                             make_new=option == 'make_new', prepared=prepared)
                if outcome.get('status') != 'success':
                    if option == 'use' and 'no longer available' in outcome.get('message', ''):
                        outcome = {**outcome, 'message': outcome['message'] + ' You can still Make new or Not now.'}
                    return outcome
            result = {**result, **outcome}
            if outcome.get('run_id'):
                result['choice']['run_id'] = outcome['run_id']
            row.update(state='done' if outcome['status'] == 'success' else 'failed', result=result)
            if stage is not None:
                # The marker survives a crash before continuation claims the stage.
                stage.update(state='proposed', continue_after_choice=True)
                continuation_key = (mid, stage['id'])
                _active_stages.add(continuation_key)
                storage.update_mission(mid, {'plan': mission['plan']})
            else:
                storage.update_mission(mid, {'program_choices': mission['program_choices']})
            storage.update_action_proposal(row['proposal_id'], {
                'status': 'approved' if row['state'] == 'done' else 'failed', 'result': result})
            if row['state'] == 'done':
                bound = _bind_created(mid, result['created'])
                if bound:
                    project_audience.narrow_on_bind(bound[0], situations.load(*bound))
            _settle(mid, 'program_choice', {'use': 'Use', 'make_new': 'Make new', 'not_now': 'Not now'}[option])
            if stage is None:
                if any(r['state'] == 'waiting_choice' for r in mission['program_choices']):
                    _offer_program_choice(mid, {'rows': mission['program_choices']})
                else:
                    resume = mission.get('program_choice_resume') or {}
                    missions._close(mid, resume.get('status') or 'running', program_choice_resume=None)
                    previous = resume.get('ask')
                    if resume.get('status') == 'waiting_user' and previous:
                        details = previous.get('result_json') or {}
                        _ask(mid, previous['name'], details.get('question') or '',
                             **{k: v for k, v in details.items() if k != 'question'})
        continued = _continue_program_choice(mid, stage['id']) if stage is not None else {'status': 'success'}
        return {'status': 'success', 'run_id': result.get('run_id'), 'message': outcome['message'],
                'continued': continued.get('status')}
    finally:
        if continuation_key is not None:
            with storage.db_lock:
                _active_stages.discard(continuation_key)


@missions._mission_work
def run_stage(mission_id, stage_id, snap, actor):
    from services import missions, chat_actions, budget_guard, projects
    key = (mission_id, stage_id)
    with storage.db_lock:
        mission, plan, stage, error = _stage_for_change(mission_id, stage_id, snap, actor)
        if error:
            return error
        if stage['state'] in ('running', 'done'):
            return {'status': 'success', 'already': True, 'message': 'Already doing it.'}
        if list(missions.subject_of(mission)) != stage.get('subject'):
            return {'status': 'success', 'moved': True, 'message': 'The subject moved; look again.'}
        if stage['state'] != 'proposed' or plan['state'] != 'approved':
            return _refused()
        if snapshot(stage, stage['subject'], plan['rev']) != snap:
            return _refused('The plan moved; look again.')
        stage['state'] = 'running'
        stage.pop('continue_after_choice', None)
        storage.update_mission(mission_id, {'plan': plan})
        projects.on_stage_started(mission_id, stage_id)
        if stage['kind'] == 'work':
            _settle(mission_id, 'stage', 'Going')
            missions._close(mission_id, 'running')
            return {'status': 'success', 'message': 'Going.'}
        _active_stages.add(key)
        pause_rev = int(mission.get('project_pause_rev') or 0)
        _settle(mission_id, 'stage', 'Doing it')
        started = _clock()
    narrowing_error = None
    stage_error = False
    try:
        for row_id in [r['id'] for r in stage['rows']]:
            with storage.db_lock:
                current = storage.get_mission(mission_id)
                plan = current['plan']
                stage = next(s for s in plan['stages'] if s['id'] == stage_id)
                if (plan['state'] != 'approved' or current.get('paused_by_project')
                        or int(current.get('project_pause_rev') or 0) != pause_rev):
                    break
                completed = {r['id']: r for r in stage['rows']}
                row = completed[row_id]
                if row['state'] != 'proposed':
                    continue
                dependencies = _row_dependencies(row)
                if any(completed.get(dep, {}).get('state') in ('waiting_choice', 'proposed') for dep in dependencies):
                    continue
                if any(completed.get(dep, {}).get('state') != 'done' for dep in dependencies):
                    row['state'] = 'skipped'
                    _dismiss_rows({'rows': [row]})
                    storage.update_mission(mission_id, {'plan': plan})
                    continue
                if _clock() - started > CAPS['stage_seconds']:
                    break
                row['state'] = 'running'
                storage.update_mission(mission_id, {'plan': plan})
            try:
                args = _resolve_refs(row['args'], completed)
                if CONTRACT[row['tool']].get('creates') in ('thread', 'program'):
                    args.setdefault('project_id', mission.get('project_id'))
                if row['tool'] == 'draft_message':
                    result = {'status': 'success', 'message': 'Draft saved.', 'created': [],
                              'to': args.get('to'), 'words': args.get('words')}
                else:
                    storage.update_action_proposal(row['proposal_id'], {'payload': args})
                    with budget_guard.guard() if CONTRACT[row['tool']]['model_calls'] else nullcontext():
                        result = chat_actions.run_row(row['proposal_id'], actor, row.get('idem'))
            except budget_guard.BudgetExhausted:
                result = {'status': 'error', 'message': "the day's limit", 'created': [], 'budget': True}
            except deletion.Cancelled:
                raise
            except Exception as exc:
                result = {'status': 'error', 'message': str(exc), 'created': []}
            if result.get('budget') is True:
                result = {'status': 'error', 'message': "the day's limit", 'created': [], 'budget': True}
            with storage.db_lock:
                plan = storage.get_mission(mission_id)['plan']
                stage = next(s for s in plan['stages'] if s['id'] == stage_id)
                row = next(r for r in stage['rows'] if r['id'] == row_id)
                row.update(result=result, state='waiting_choice' if result['status'] == 'waiting_choice'
                           else 'done' if result['status'] == 'success' else 'failed')
                storage.update_mission(mission_id, {'plan': plan})
                if row['state'] == 'failed':
                    _dismiss_rows({'rows': [row]})
                elif row['state'] == 'done':
                    bound = _bind_created(mission_id, result.get('created') or [])
                    if bound:
                        from services import project_audience, situations
                        try:
                            project_audience.narrow_on_bind(bound[0], situations.load(*bound))
                        except deletion.Cancelled:
                            raise
                        except Exception as exc:
                            # The row result is saved; finish stage bookkeeping before raising.
                            if narrowing_error is None:
                                narrowing_error = exc
            if result.get('budget') is True:
                break
        with storage.db_lock:
            current = storage.get_mission(mission_id)
            plan = current['plan']
            stage = next(s for s in plan['stages'] if s['id'] == stage_id)
            if plan['state'] == 'stopped':
                stage['state'] = 'skipped'
                storage.update_mission(mission_id, {'plan': plan})
                return {'status': 'success', 'message': 'Stopped.'}
            if any(r['state'] == 'waiting_choice' for r in stage['rows']):
                stage['state'] = 'waiting_choice'
                storage.update_mission(mission_id, {'plan': plan})
                _offer_program_choice(mission_id, stage)
                return {'status': 'success', 'message': 'Waiting for a program choice.'}
            if (current.get('paused_by_project')
                    or int(current.get('project_pause_rev') or 0) != pause_rev):
                stage.update(state='partial', paused_by_project=True)
                storage.update_mission(mission_id, {'plan': plan})
                if not current.get('paused_by_project'):
                    _ask(mission_id, 'stage', 'Partly done; carry on?', stage_id=stage_id)
                return {'status': 'success', 'message': 'Paused.'}
            stage['state'] = 'done' if all(r['state'] in ('done', 'excluded', 'skipped', 'uncertain') for r in stage['rows']) else 'partial'
            if can_resume_stage(stage):
                storage.update_mission(mission_id, {'plan': plan})
                _ask(mission_id, 'stage', 'Partly done; carry on later.', stage_id=stage_id)
            else:
                missions._close(mission_id, 'running', plan=plan)
                if stage['state'] == 'done':
                    projects.on_stage_done(mission_id, stage_id, {'summary': '; '.join(
                        r['summary'] for r in stage['rows'] if r['state'] == 'done')})
                else:
                    reason = next(((r.get('result') or {}).get('message') for r in stage['rows']
                                   if r['state'] == 'failed'), 'Stage could not finish.')
                    projects.on_stage_blocked(mission_id, stage_id, reason)
        return {'status': 'success', 'message': 'Stage done.' if stage['state'] == 'done' else 'Partly done; carry on later.'}
    except BaseException:
        stage_error = True
        raise
    finally:
        with storage.db_lock:
            _active_stages.discard(key)
        if narrowing_error is not None and not stage_error:
            raise narrowing_error


def reconcile():
    """A lost claim is evidence to check, never permission to repeat a write."""
    from services import projects, access
    with storage.db_lock:
        for mission in storage.get_missions():
            if access.gone('mission', mission):
                continue
            plan = mission.get('plan') or {}
            if plan.get('state') == 'approving':
                with deletion.acting_for('mission', mission['id']):
                    _complete_approval(mission, plan)
        waiting_projects = {missions.subject_of(m)[1] for m in storage.get_missions(status='waiting_step')
                            if missions.subject_of(m)[0] == 'project'}
        for pid in waiting_projects:
            projects.resume_waiting(pid)
        for project in storage.get_projects():
            if project.get('state') == 'active':
                projects.advance(project['id'])
        for mission in storage.get_missions():
            if access.gone('mission', mission):
                continue
            with deletion.acting_for('mission', mission['id']):
                plan = mission.get('plan') or {}
                standalone = [r for r in mission.get('program_choices') or [] if r['state'] == 'waiting_choice']
                if standalone and not mission.get('paused_by_project') and mission.get('status') not in ('blocked', 'dropped'):
                    _offer_program_choice(mission['id'], {'rows': standalone})
                if plan.get('state') in ('stopped', 'done'):
                    continue
                changed, uncertain = False, []
                for stage in plan.get('stages', []):
                    if stage['kind'] == 'work':
                        continue  # The normal persisted planner loop resumes work after restart.
                    if stage.get('continue_after_choice') and (mission['id'], stage['id']) not in _active_stages:
                        _recover_choice_continuation(mission, stage)
                        continue
                    if stage['state'] == 'waiting_choice':
                        if not mission.get('paused_by_project'):
                            _offer_program_choice(mission['id'], stage)
                        continue
                    if stage['state'] != 'running' or (mission['id'], stage['id']) in _active_stages:
                        continue
                    if any(r['state'] == 'waiting_choice' for r in stage.get('rows', [])) and not any(
                            r['state'] == 'running' for r in stage.get('rows', [])):
                        stage['state'] = 'waiting_choice'
                        storage.update_mission(mission['id'], {'plan': plan})
                        _offer_program_choice(mission['id'], stage)
                        continue
                    for row in stage.get('rows', []):
                        if row['state'] == 'running':
                            row['state'] = 'uncertain'
                            if row.get('proposal_id'):
                                storage.update_action_proposal(row['proposal_id'], {'status': 'uncertain'})
                            uncertain.append({'stage_id': stage['id'], 'row_id': row['id'], 'summary': row.get('summary')})
                    stage['state'] = ('waiting_choice' if any(r['state'] == 'waiting_choice'
                                      for r in stage.get('rows', [])) else 'uncertain')
                    if mission.get('paused_by_project'):
                        stage['paused_by_project'] = True
                    changed = True
                if changed:
                    storage.update_mission(mission['id'], {'plan': plan})
                    if not mission.get('paused_by_project'):
                        waiting = next((s for s in plan['stages'] if s['state'] == 'waiting_choice'), None)
                        if waiting:
                            _offer_program_choice(mission['id'], waiting)
                        else:
                            _ask(mission['id'], 'stage_check', 'Please check what happened before carrying on.', rows=uncertain)
