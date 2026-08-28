"""Chat can carry a thread — identity is resolved at dispatch, never the model."""
import os
from harness import check
from services import storage, agent_tools_v2


def _reset():
    storage.threads_table.truncate()


def scenario_create_round_trips_and_records_owner():
    _reset()
    parent = {'id': 'm-parent', 'role': 'parent'}
    res = agent_tools_v2.create_thread('Pest control', next_action='Call them back',
                                       next_action_at='2026-09-01',
                                       acting_member=parent)
    check(res['status'] == 'success', f"got {res}")
    rows = storage.get_threads(include_closed=True)
    check(len(rows) == 1, f"one thread created, got {rows}")
    check(rows[0]['title'] == 'Pest control', "title recorded")
    check(rows[0]['owner_member_id'] == 'm-parent',
          "the acting member becomes owner when one resolves")


def scenario_list_shows_what_was_created():
    _reset()
    parent = {'id': 'm-parent', 'role': 'parent'}
    agent_tools_v2.create_thread('Deck permit', acting_member=parent)
    res = agent_tools_v2.list_threads()
    check(res['status'] == 'success', f"got {res}")
    check('Deck permit' in res.get('message', ''), f"got {res}")


def scenario_update_thread_action_advances_it():
    _reset()
    parent = {'id': 'm-parent', 'role': 'parent'}
    agent_tools_v2.create_thread('Gutters', acting_member=parent)
    res = agent_tools_v2.update_thread_action('Gutters', 'Get a quote',
                                              next_action_at='2026-09-10',
                                              acting_member=parent)
    check(res['status'] == 'success', f"got {res}")
    row = storage.get_threads(include_closed=True)[0]
    check(row['next_action'] == 'Get a quote', "next action set")
    check(row['next_action_at'] == '2026-09-10', "next action date set")
    check(len(row['history']) == 2, "advance logged")


def scenario_add_thread_note_logs_movement():
    _reset()
    parent = {'id': 'm-parent', 'role': 'parent'}
    agent_tools_v2.create_thread('Gutters', acting_member=parent)
    res = agent_tools_v2.add_thread_note('Gutters', 'Left a voicemail',
                                         acting_member=parent)
    check(res['status'] == 'success', f"got {res}")
    row = storage.get_threads(include_closed=True)[0]
    check(len(row['history']) == 2, "note logged")
    check(row['history'][-1]['text'] == 'Left a voicemail', "note text recorded")


def scenario_child_is_refused_on_every_write():
    _reset()
    parent = {'id': 'm-parent', 'role': 'parent'}
    child = {'id': 'm-kid', 'role': 'child'}
    agent_tools_v2.create_thread('Gutters', acting_member=parent)

    res = agent_tools_v2.create_thread('Should not exist', acting_member=child)
    check(res['status'] == 'error', f"child create refused, got {res}")
    check(len(storage.get_threads(include_closed=True)) == 1,
          "refused create writes nothing")

    res = agent_tools_v2.update_thread_action('Gutters', 'Nope', acting_member=child)
    check(res['status'] == 'error', f"child advance refused, got {res}")

    res = agent_tools_v2.add_thread_note('Gutters', 'Nope', acting_member=child)
    check(res['status'] == 'error', f"child note refused, got {res}")

    row = storage.get_threads(include_closed=True)[0]
    check(len(row['history']) == 1, "refused writes leave the history alone")


def scenario_model_cannot_spoof_identity():
    for tool in agent_tools_v2.get_available_tools():
        if tool['name'] in ('list_threads', 'create_thread',
                            'update_thread_action', 'add_thread_note'):
            props = tool['parameters'].get('properties', {})
            check('member' not in props and 'role' not in props
                  and 'acting_member' not in props and 'member_role' not in props,
                  f"{tool['name']} exposes identity to the model: {list(props)}")


def scenario_registered():
    names = [t['name'] for t in agent_tools_v2.get_available_tools()]
    for tool in ('list_threads', 'create_thread', 'update_thread_action',
                'add_thread_note'):
        check(tool in names, f"{tool} missing from the catalog")


def scenario_dispatch_wired():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    router = open(os.path.join(here, 'services', 'agent_router.py'),
                 encoding='utf-8').read()
    for tool in ('list_threads', 'create_thread', 'update_thread_action',
                'add_thread_note'):
        check('"%s"' % tool in router,
              f"{tool} is not wired into the router's dispatch chain")


if __name__ == '__main__':
    scenario_create_round_trips_and_records_owner()
    scenario_list_shows_what_was_created()
    scenario_update_thread_action_advances_it()
    scenario_add_thread_note_logs_movement()
    scenario_child_is_refused_on_every_write()
    scenario_model_cannot_spoof_identity()
    scenario_registered()
    scenario_dispatch_wired()
    print("test_threads_agent_tools OK")
