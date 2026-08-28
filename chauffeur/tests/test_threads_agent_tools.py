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
    res = agent_tools_v2.list_threads(acting_member=parent)
    check(res['status'] == 'success', f"got {res}")
    check('Deck permit' in res.get('message', ''), f"got {res}")
    # Any RESOLVED member may read — a child sees the list too.
    res_kid = agent_tools_v2.list_threads(acting_member={'id': 'k', 'role': 'child'})
    check(res_kid['status'] == 'success', f"a resolved child may read, got {res_kid}")


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


THREAD_TOOLS = ('list_threads', 'create_thread', 'update_thread_action',
                'add_thread_note', 'draft_thread_message', 'close_thread')


def scenario_draft_tool_returns_words_and_cannot_send():
    _reset()
    from services import threads as _threads, mailer as _m
    parent = {'id': 'm-parent', 'role': 'parent'}
    agent_tools_v2.create_thread('Pool', counterparty_email='pool@example.com',
                                 acting_member=parent)
    sent = []
    orig_pool, orig_send = _threads._pool_call, _m.send
    try:
        _threads._pool_call = lambda *a, **k: {'subject': 'Following up',
                                               'body': 'Hi — checking in.'}
        _m.send = lambda *a, **k: sent.append(a) or {'sent': True}
        res = agent_tools_v2.draft_thread_message('Pool', acting_member=parent)
        check(res['status'] == 'success', f"got {res}")
        check(res.get('subject') == 'Following up'
              and 'checking in' in res.get('body', ''),
              f"the draft text comes BACK to the caller, got {res}")
        check('nothing has been sent' in res['message'],
              f"the reply must say so, so the model does not promise a "
              f"send, got {res['message']!r}")
        check(not sent, "THE DRAFT TOOL MUST NEVER SEND")
        row = storage.get_threads(include_closed=True)[0]
        check(not any(h.get('kind') == 'sent' for h in row['history']),
              "and must not claim it did in the record")
        res_kid = agent_tools_v2.draft_thread_message(
            'Pool', acting_member={'id': 'k', 'role': 'child'})
        check(res_kid['status'] == 'error', f"child draft refused, got {res_kid}")
    finally:
        _threads._pool_call, _m.send = orig_pool, orig_send


def scenario_close_tool_closes_and_holds_the_enum():
    _reset()
    parent = {'id': 'm-parent', 'role': 'parent'}
    agent_tools_v2.create_thread('Dresser', acting_member=parent)

    res = agent_tools_v2.close_thread('Dresser', state='banana',
                                      acting_member=parent)
    check(res['status'] == 'error', f"a state outside done/dropped refused, got {res}")
    res = agent_tools_v2.close_thread('Dresser', acting_member=parent)
    check(res['status'] == 'error', f"a missing state refused, got {res}")
    row = storage.get_threads(include_closed=True)[0]
    check(row['state'] == 'open', f"refusals wrote nothing, got {row['state']}")

    res = agent_tools_v2.close_thread('Dresser', state='dropped',
                                      acting_member={'id': 'k', 'role': 'child'})
    check(res['status'] == 'error', f"child close refused, got {res}")

    res = agent_tools_v2.close_thread('Dresser', state='dropped',
                                      acting_member=parent)
    check(res['status'] == 'success', f"got {res}")
    row = storage.get_threads(include_closed=True)[0]
    check(row['state'] == 'dropped', f"got {row['state']}")
    check(row['history'][-1]['kind'] == 'closed', "the close is logged")


def scenario_unresolved_caller_is_refused_on_every_tool():
    """/api/chat is WALL_OR_SERVICE: an anonymous kitchen wall panel reaches
    these tools with acting_member None. Every thread tool — the read
    included, since /threads is deliberately hidden from kiosks to keep
    counterparty data off shared screens — must refuse an unresolved actor,
    not wave role-None past a blocklist."""
    _reset()
    parent = {'id': 'm-parent', 'role': 'parent'}
    agent_tools_v2.create_thread('Gutters', acting_member=parent)

    for res, name in (
        (agent_tools_v2.list_threads(acting_member=None), 'list_threads'),
        (agent_tools_v2.create_thread('X', acting_member=None), 'create_thread'),
        (agent_tools_v2.update_thread_action('Gutters', 'x', acting_member=None),
         'update_thread_action'),
        (agent_tools_v2.add_thread_note('Gutters', 'x', acting_member=None),
         'add_thread_note'),
        (agent_tools_v2.draft_thread_message('Gutters', acting_member=None),
         'draft_thread_message'),
        (agent_tools_v2.close_thread('Gutters', state='done', acting_member=None),
         'close_thread'),
    ):
        check(res['status'] == 'error',
              f"{name} let an unresolved caller through: {res}")
    row = storage.get_threads(include_closed=True)[0]
    check(row['state'] == 'open' and len(row['history']) == 1
          and len(storage.get_threads(include_closed=True)) == 1,
          "and none of the refusals wrote anything")


def scenario_no_tool_can_reach_mailer_send():
    """There is no send tool, and no tool module path to services.mailer at
    all: agent_tools_v2 never imports it, and the one thread function that
    does (threads.send_drafted) is reachable only from the /send endpoint —
    a person's tap. Static check plus a live one."""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(here, 'services', 'agent_tools_v2.py'),
               encoding='utf-8').read()
    check('import mailer' not in src and 'from services import mailer' not in src
          and 'mailer.send' not in src,
          "agent_tools_v2 must never import services.mailer or call its send")
    names = [t['name'] for t in agent_tools_v2.get_available_tools()]
    check(not any('send' in n and 'thread' in n for n in names),
          f"no thread-send tool may exist in the catalog, got {names}")


def scenario_model_cannot_spoof_identity():
    for tool in agent_tools_v2.get_available_tools():
        if tool['name'] in THREAD_TOOLS:
            props = tool['parameters'].get('properties', {})
            check('member' not in props and 'role' not in props
                  and 'acting_member' not in props and 'member_role' not in props
                  and 'owner' not in props,
                  f"{tool['name']} exposes identity to the model: {list(props)}")


def scenario_registered():
    names = [t['name'] for t in agent_tools_v2.get_available_tools()]
    for tool in THREAD_TOOLS:
        check(tool in names, f"{tool} missing from the catalog")


def scenario_dispatch_wired():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    router = open(os.path.join(here, 'services', 'agent_router.py'),
                 encoding='utf-8').read()
    for tool in THREAD_TOOLS:
        check('"%s"' % tool in router,
              f"{tool} is not wired into the router's dispatch chain")


if __name__ == '__main__':
    scenario_create_round_trips_and_records_owner()
    scenario_list_shows_what_was_created()
    scenario_update_thread_action_advances_it()
    scenario_add_thread_note_logs_movement()
    scenario_child_is_refused_on_every_write()
    scenario_draft_tool_returns_words_and_cannot_send()
    scenario_close_tool_closes_and_holds_the_enum()
    scenario_unresolved_caller_is_refused_on_every_tool()
    scenario_no_tool_can_reach_mailer_send()
    scenario_model_cannot_spoof_identity()
    scenario_registered()
    scenario_dispatch_wired()
    print("test_threads_agent_tools OK")
