"""Admission contract and approval records for planned mission stages."""

import hashlib
import json
import time
from contextlib import nullcontext

from services import storage, subjects

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
    return ((actor or {}).get('role') in ('parent', 'adult')
            and all(subjects.visible(kind, record, actor)
                    for kind, record in subjects.subject_records('mission', mission)))


def stage_pending(mission):
    return any(s.get('state') in ('proposed', 'running')
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
        if not plan or plan['state'] != 'interviewing' or mission.get('status') in ('done', 'blocked', 'dropped'):
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


def approve_plan(mission_id, rev, actor):
    from services import missions
    with storage.db_lock:
        mission, plan, error = _plan_for_change(mission_id, actor, rev)
        if error:
            return error
        if plan['state'] != 'proposed':
            return _refused()
        plan.update(state='approved', approved_by=actor.get('id'), approved_at=time.time())
        missions._close(mission_id, 'running', plan=plan)
        _settle(mission_id, 'plan', 'Looks good')
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


def stop_plan(mission_id, actor):
    with storage.db_lock:
        mission, plan, error = _plan_for_change(mission_id, actor)
        if error:
            return error
        if any(s['state'] == 'running' for s in plan['stages']):
            return _refused('Finish the running stage first.')
        plan['state'] = 'stopped'
        for stage in plan['stages']:
            _dismiss_rows(stage)
        storage.update_mission(mission_id, {'plan': plan})
        _settle(mission_id, 'plan', 'Stopped')
        _settle(mission_id, 'stage', 'Stopped')
        from services import missions
        missions._close(mission_id, 'dropped')
    return {'status': 'success', 'message': 'Stopped.'}


def _dismiss_rows(stage):
    for row in stage.get('rows', []):
        pid = row.get('proposal_id')
        prop = storage.get_action_proposal(pid) if pid else None
        if prop and prop.get('status') == 'proposed':
            storage.update_action_proposal(pid, {'status': 'dismissed'})


def _stage_for_change(mid, stage_id, snap, actor):
    mission, plan, error = _plan_for_change(mid, actor)
    if error:
        return None, None, None, error
    stage = next((s for s in plan['stages'] if s['id'] == stage_id), None)
    if not stage or stage.get('snapshot') != snap:
        return None, None, None, {'status': 'success', 'moved': True, 'message': 'The stage moved; look again.'}
    return mission, plan, stage, None


def can_resume_stage(stage):
    return (stage.get('kind') == 'build' and stage.get('state') == 'partial'
            and any(r['state'] == 'proposed' or
                    (r['state'] == 'failed' and (r.get('result') or {}).get('budget') is True)
                    for r in stage.get('rows', [])))


def resume_stage(mission_id, stage_id, snap, actor):
    from services import missions
    with storage.db_lock:
        mission, plan, stage, error = _stage_for_change(mission_id, stage_id, snap, actor)
        if error:
            return error
        if plan['state'] != 'approved' or not can_resume_stage(stage) or stage_pending(mission):
            return _refused()
        for row in stage['rows']:
            if row['state'] == 'failed' and (row.get('result') or {}).get('budget') is True:
                row['state'] = 'proposed'
                row.pop('result', None)
                if row.get('proposal_id'):
                    storage.update_action_proposal(row['proposal_id'], {'status': 'proposed', 'result': None})
        stage['state'] = 'proposed'
        stage['subject'] = list(missions.subject_of(mission))
        # Even unchanged inputs need fresh approval after a partial attempt.
        plan['rev'] += 1
        stage['snapshot'] = snapshot(stage, stage['subject'], plan['rev'])
        storage.update_mission(mission_id, {'plan': plan})
        _settle(mission_id, 'stage', 'Carry on')
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
        if stage['state'] != 'proposed' and not can_resume_stage(stage):
            return _refused()
        stage['state'] = 'skipped'
        _dismiss_rows(stage)
        missions._close(mission_id, 'running', plan=plan)
        _settle(mission_id, 'stage', 'Not this one')
    return {'status': 'success', 'message': 'Stage skipped.'}


def planner_action(mid, action):
    """Admit a planner action against the current persisted phase."""
    from services import missions, occasions
    with storage.db_lock:
        mission = storage.get_mission(mid)
        plan = mission.get('plan')
        name = action['action']
        if mission['status'] != 'running':
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
                if (not isinstance(stage, dict) or not stage.get('id') or stage['id'] in seen
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
            plan['stages'] = [{k: s.get(k) for k in ('id', 'kind', 'title', 'why', 'makes', 'owner_member_id', 'goal', 'step_budget')}
                              | {'state': 'pending'} for s in stages]
            plan.update(state='proposed', rev=plan['rev'] + 1)
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
        if not plan or mission['status'] != 'running' or plan['state'] != 'approved' or stage_pending(mission):
            return _refused()
        stage = next((s for s in plan['stages'] if s['state'] == 'pending'), None)
        if not stage or stage['id'] != stage_id or stage['kind'] != 'build':
            return _refused('Only the next pending build stage can propose rows.')
        if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
            return _refused('A stage needs rows.')
        error = check_rows(rows)
        if error:
            return _refused(error)
        seen = set()
        for row in rows:
            if not row.get('id') or row['id'] in seen or not set(row.get('needs') or []) <= seen:
                return _refused('Rows need unique ids and earlier prerequisites.')
            seen.add(row['id'])
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


def _resolve_refs(value, completed):
    if isinstance(value, dict):
        if '$ref' in value:
            row = completed.get(value['$ref']) or {}
            found = next((c['id'] for c in (row.get('result') or {}).get('created', [])
                          if c.get('kind') == value.get('kind')), None) if row.get('state') == 'done' else None
            if found is None:
                raise ValueError(f"No created {value.get('kind')} from {value['$ref']}.")
            return found
        return {k: _resolve_refs(v, completed) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_refs(v, completed) for v in value]
    return value


def _bind_created(mid, created):
    from services import missions
    mission = storage.get_mission(mid)
    if missions.subject_of(mission)[0]:
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


def run_stage(mission_id, stage_id, snap, actor):
    from services import missions, chat_actions, budget_guard
    key = (mission_id, stage_id)
    with storage.db_lock:
        mission, plan, stage, error = _stage_for_change(mission_id, stage_id, snap, actor)
        if error:
            return error
        if stage['state'] in ('running', 'done'):
            return {'status': 'success', 'already': True, 'message': 'Already doing it.'}
        if list(missions.subject_of(mission)) != stage.get('subject'):
            return {'status': 'success', 'moved': True, 'message': 'The subject moved; look again.'}
        if stage['state'] != 'proposed' or stage['kind'] != 'build' or plan['state'] != 'approved':
            return _refused()
        stage['state'] = 'running'
        storage.update_mission(mission_id, {'plan': plan})
        _active_stages.add(key)
        _settle(mission_id, 'stage', 'Doing it')
        started = _clock()
    try:
        for row_id in [r['id'] for r in stage['rows']]:
            with storage.db_lock:
                plan = storage.get_mission(mission_id)['plan']
                stage = next(s for s in plan['stages'] if s['id'] == stage_id)
                completed = {r['id']: r for r in stage['rows']}
                row = completed[row_id]
                if row['state'] != 'proposed':
                    continue
                if any(completed.get(dep, {}).get('state') != 'done' for dep in row['needs']):
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
                if row['tool'] == 'draft_message':
                    result = {'status': 'success', 'message': 'Draft saved.', 'created': [],
                              'to': args.get('to'), 'words': args.get('words')}
                else:
                    storage.update_action_proposal(row['proposal_id'], {'payload': args})
                    with budget_guard.guard() if CONTRACT[row['tool']]['model_calls'] else nullcontext():
                        result = chat_actions.run_row(row['proposal_id'], actor, row.get('idem'))
            except budget_guard.BudgetExhausted:
                result = {'status': 'error', 'message': "the day's limit", 'created': [], 'budget': True}
            except Exception as exc:
                result = {'status': 'error', 'message': str(exc), 'created': []}
            if result.get('budget') is True:
                result = {'status': 'error', 'message': "the day's limit", 'created': [], 'budget': True}
            with storage.db_lock:
                plan = storage.get_mission(mission_id)['plan']
                stage = next(s for s in plan['stages'] if s['id'] == stage_id)
                row = next(r for r in stage['rows'] if r['id'] == row_id)
                row.update(result=result, state='done' if result['status'] == 'success' else 'failed')
                storage.update_mission(mission_id, {'plan': plan})
                if row['state'] == 'failed':
                    _dismiss_rows({'rows': [row]})
                else:
                    _bind_created(mission_id, result.get('created') or [])
            if result.get('budget') is True:
                break
        with storage.db_lock:
            plan = storage.get_mission(mission_id)['plan']
            stage = next(s for s in plan['stages'] if s['id'] == stage_id)
            stage['state'] = 'done' if all(r['state'] in ('done', 'excluded') for r in stage['rows']) else 'partial'
            if can_resume_stage(stage):
                storage.update_mission(mission_id, {'plan': plan})
                _ask(mission_id, 'stage', 'Partly done; carry on later.', stage_id=stage_id)
            else:
                missions._close(mission_id, 'running', plan=plan)
        return {'status': 'success', 'message': 'Stage done.' if stage['state'] == 'done' else 'Partly done; carry on later.'}
    finally:
        with storage.db_lock:
            _active_stages.discard(key)


def reconcile():
    """A lost claim is evidence to check, never permission to repeat a write."""
    with storage.db_lock:
        for mission in storage.get_missions():
            plan = mission.get('plan') or {}
            changed, uncertain = False, []
            for stage in plan.get('stages', []):
                if stage['state'] != 'running' or (mission['id'], stage['id']) in _active_stages:
                    continue
                for row in stage.get('rows', []):
                    if row['state'] == 'running':
                        row['state'] = 'uncertain'
                        uncertain.append({'stage_id': stage['id'], 'row_id': row['id'], 'summary': row.get('summary')})
                stage['state'] = 'uncertain'
                changed = True
            if changed:
                storage.update_mission(mission['id'], {'plan': plan})
                _ask(mission['id'], 'stage_check', 'Please check what happened before carrying on.', rows=uncertain)
