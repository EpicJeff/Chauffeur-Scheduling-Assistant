"""Admission contract and approval records for planned mission stages."""

import hashlib
import json

from services import storage, subjects


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
