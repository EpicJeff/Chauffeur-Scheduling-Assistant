"""Mission engine — one generic agent loop, many thin doorways.

Spec: docs/superpowers/specs/2026-09-04-mission-engine-design.md.
Laws in force here:
- The engine executes READ tools only. Every write intent becomes an
  action proposal a parent approves on /missions; approval executes on the
  same chat_actions rail every other proposal uses.
- The pro pool (paid key) is reachable only through tier 'mission'; a
  mission never falls back to a free pool — it pauses instead.
- send_direct_message is never offered in any form. Mail drafting goes
  through threads.draft_message, which cannot send.
"""
import datetime
import json
import logging
import time

from services import storage, model_pools

logger = logging.getLogger(__name__)

CAPS_DEFAULT = {'launch': 3, 'steps': 40, 'pro_calls': 120}
STEPS_PER_TICK = 3
RETRY_DELAY_S = 300
MAX_CONSEC_ERRORS = 3
RETENTION_DAYS = 120

# Default-deny read classification: a registry tool NOT named here is offered
# only in propose-wrapped form. Adding a tool to the registry later leaves it
# write-classed until someone consciously promotes it.
READ_TOOLS = frozenset({
    'get_current_state', 'get_errands', 'get_pet_status', 'get_point_balances',
    'get_family_goals', 'get_family_messages', 'list_chores',
    'list_open_findings', 'list_insights', 'list_programs',
    'get_routine_status', 'get_kid_tasks', 'get_shopping_list_items',
    'get_tonights_plate', 'get_meal_rules', 'get_occasion',
    'get_occasion_insights', 'get_occasion_gaps', 'get_run_sheet',
    'get_prep_ahead', 'search_places', 'suggest_gift_ideas',
})

# Never offered, not even propose-wrapped. DMs are private space (mind law).
EXCLUDED_TOOLS = frozenset({'send_direct_message'})


def proposable_tools() -> frozenset:
    from services import agent_tools, chat_actions
    return (frozenset(agent_tools.TOOL_HANDLERS) - READ_TOOLS - EXCLUDED_TOOLS) \
        | frozenset(chat_actions.ADMIN_ACTIONS)


def _bump_call(kind: str, cap: int) -> bool:
    """Day-keyed counter, mind's idiom; True = allowed (and counted)."""
    day = datetime.date.today().isoformat()
    key = f'mission_calls:{day}'
    counts = dict(storage.get_app_state(key) or {})
    if int(counts.get(kind, 0)) >= cap:
        return False
    counts[kind] = int(counts.get(kind, 0)) + 1
    storage.set_app_state(key, counts)
    return True


def _llm_live(mission: dict, system: str, user: str, settings: dict) -> dict:
    tier = 'mission' if mission.get('tier') != 'flash' else 'mission_flash'
    pool = 'pro' if tier == 'mission' else 'flash'
    api_key = model_pools.api_key_for_pool(pool, settings)
    if not api_key:
        return {'error': 'no api key for pool ' + pool, 'transient': False}
    return model_pools.call_pool_json(tier, api_key, system, user,
                                      settings=settings, timeout_s=120)


# Test seam: scenarios replace this with a scripted fake.
_llm = _llm_live


def _catalog() -> str:
    from services import agent_tools
    lines = []
    for name in sorted(READ_TOOLS):
        schema = agent_tools.TOOL_SCHEMAS.get(name) or {}
        props = ', '.join((schema.get('properties') or {}).keys()) or 'no args'
        lines.append(f"- READ {name}({props})")
    for name in sorted(proposable_tools()):
        from services import agent_tools as _at
        schema = _at.TOOL_SCHEMAS.get(name) or {}
        props = ', '.join((schema.get('properties') or {}).keys()) or 'payload'
        lines.append(f"- PROPOSE {name}({props})")
    return '\n'.join(lines)


def _system_prompt(now: datetime.datetime) -> str:
    return (
        f"Today is {now.strftime('%A %Y-%m-%d')}. You are Argyle working a "
        "MISSION for the family: a multi-step goal you advance one action at "
        "a time. You cannot execute changes yourself — every change you want "
        "is a PROPOSAL a parent approves later, and drafted messages are "
        "never sent by you (a person reviews and sends). Never claim "
        "something was sent, booked, or paid.\n\n"
        "Respond with EXACTLY ONE JSON object, one of:\n"
        '{"action":"tool","tool":"<READ tool>","args":{...}}\n'
        '{"action":"propose","tool":"<PROPOSE tool>","args":{...},'
        '"summary":"<one line a parent reads>","why":"<reason>"}\n'
        '{"action":"research","question":"<web question>"}\n'
        '{"action":"draft","thread_title":"<thread>","intent":"<what the '
        'message should do>"}\n'
        '{"action":"ask_user","question":"<one question>"}\n'
        '{"action":"finish","summary":"<what was achieved + what awaits '
        'approval>"}\n'
        '{"action":"give_up","reason":"<honest blocker>"}\n\n'
        "Prefer finishing with a small set of strong proposals over endless "
        "research. Available tools:\n" + _catalog()
    )


def _compact(value, limit=900):
    try:
        s = json.dumps(value) if not isinstance(value, str) else value
    except Exception:
        s = str(value)
    return s[:limit] + ('…' if len(s) > limit else '')


def _user_prompt(mission: dict) -> str:
    steps = storage.get_mission_steps(mission['id'])
    lines = [f"GOAL: {mission.get('goal')}"]
    if mission.get('origin_kind') == 'thread':
        lines.append(f"(Opened from thread {mission.get('origin_ref')})")
    lines.append("TRANSCRIPT SO FAR (oldest first):")
    for s in steps[-25:]:
        lines.append(f"[{s['idx']}] {s['kind']} {s.get('name') or ''} "
                     f"args={_compact(s.get('args_json'), 200)} "
                     f"result={_compact(s.get('result_json'))}")
    if not steps:
        lines.append("(none yet — plan your first move)")
    lines.append("Reply with your ONE next action as JSON.")
    return '\n'.join(lines)


def _close(mission_id: str, status: str, **fields) -> dict:
    fields = {'status': status, **fields}
    if status in ('done', 'blocked', 'dropped'):
        fields.setdefault('finished_at', time.time())
    storage.update_mission(mission_id, fields)
    return storage.get_mission(mission_id)


def _match_thread(title: str):
    title = (title or '').strip().lower()
    if not title:
        return None
    rows = storage.get_threads()
    exact = [t for t in rows if (t.get('title') or '').strip().lower() == title]
    if len(exact) == 1:
        return exact[0]
    sub = [t for t in rows if title in (t.get('title') or '').lower()]
    return sub[0] if len(sub) == 1 else None


def step(mission: dict) -> dict:
    """Advance ONE step. Returns the fresh mission row. All state transitions
    live here so tick() stays a scheduler and tests drive this directly."""
    mid = mission['id']
    settings = storage.get_settings() or {}
    caps = {'steps': int(settings.get('mission_step_cap', CAPS_DEFAULT['steps'])),
            'pro_calls': int(settings.get('mission_cap_pro_calls',
                                          CAPS_DEFAULT['pro_calls']))}
    if int(mission.get('step_count') or 0) >= caps['steps']:
        return _close(mid, 'blocked',
                      error=f"step cap ({caps['steps']}) reached")
    if mission.get('tier') != 'flash' and not _bump_call('pro', caps['pro_calls']):
        storage.update_mission(mid, {'status': 'waiting_retry',
                                     'retry_at': time.time() + 1800})
        return storage.get_mission(mid)

    now = datetime.datetime.now()
    res = _llm(mission, _system_prompt(now), _user_prompt(mission), settings)
    storage.update_mission(mid, {'step_count': int(mission.get('step_count') or 0) + 1})

    if not isinstance(res, dict) or res.get('error'):
        err = (res or {}).get('error') if isinstance(res, dict) else 'bad response'
        if isinstance(res, dict) and res.get('transient'):
            storage.update_mission(mid, {'status': 'waiting_retry',
                                         'retry_at': time.time() + RETRY_DELAY_S})
            return storage.get_mission(mid)
        n = int(mission.get('consec_errors') or 0) + 1
        if n >= MAX_CONSEC_ERRORS:
            return _close(mid, 'blocked', error=str(err), consec_errors=n)
        storage.update_mission(mid, {'consec_errors': n})
        storage.add_mission_step(mid, {'kind': 'note', 'name': 'llm_error',
                                       'result_json': {'error': str(err)}})
        return storage.get_mission(mid)

    storage.update_mission(mid, {'consec_errors': 0})
    action = (res.get('action') or '').strip()

    if action == 'tool':
        name = res.get('tool') or ''
        if name not in READ_TOOLS:
            storage.add_mission_step(mid, {'kind': 'note', 'name': 'refused',
                'result_json': {'note': f"{name} is not a READ tool — use "
                                        f"propose for changes"}})
            return storage.get_mission(mid)
        from services import agent_tools
        out = agent_tools.execute_tool(name, res.get('args') or {})
        storage.add_mission_step(mid, {'kind': 'tool', 'name': name,
                                       'args_json': res.get('args') or {},
                                       'result_json': out})
        return storage.get_mission(mid)

    if action == 'propose':
        name = res.get('tool') or ''
        if name in EXCLUDED_TOOLS or name not in proposable_tools():
            storage.add_mission_step(mid, {'kind': 'note', 'name': 'refused',
                'result_json': {'note': f"{name} is not proposable"}})
            return storage.get_mission(mid)
        from services import chat_actions
        summary = (res.get('summary') or res.get('why') or name).strip()
        made = chat_actions.create_action_proposal(
            name, summary, res.get('args') or {},
            created_by_member_id=mission.get('created_by'),
            extra_allowed=proposable_tools())
        storage.add_mission_step(mid, {'kind': 'proposal', 'name': name,
                                       'args_json': res.get('args') or {},
                                       'result_json': {**made,
                                                       'why': res.get('why')}})
        return storage.get_mission(mid)

    if action == 'research':
        from services import web
        out = web.research((res.get('question') or '').strip())
        storage.add_mission_step(mid, {'kind': 'tool', 'name': 'research',
                                       'args_json': {'question': res.get('question')},
                                       'result_json': out})
        return storage.get_mission(mid)

    if action == 'draft':
        thread = None
        if mission.get('origin_kind') == 'thread':
            thread = storage.get_thread(mission.get('origin_ref'))
        thread = thread or _match_thread(res.get('thread_title'))
        if not thread:
            storage.add_mission_step(mid, {'kind': 'note', 'name': 'refused',
                'result_json': {'note': 'no unambiguous thread matched — a tie '
                                        'declines, ask the user or open one via '
                                        'propose'}})
            return storage.get_mission(mid)
        from services import threads as _threads
        out = _threads.draft_message(thread['id'],
                                     intent=(res.get('intent') or '').strip())
        storage.add_mission_step(mid, {'kind': 'draft', 'name': thread.get('title'),
                                       'args_json': {'intent': res.get('intent')},
                                       'result_json': out})
        return storage.get_mission(mid)

    if action == 'ask_user':
        storage.add_mission_step(mid, {'kind': 'ask', 'name': 'question',
            'result_json': {'question': (res.get('question') or '').strip()}})
        return _close(mid, 'waiting_user')

    if action == 'finish':
        storage.add_mission_step(mid, {'kind': 'llm', 'name': 'finish',
                                       'result_json': res})
        return _close(mid, 'done', summary=(res.get('summary') or '').strip())

    if action == 'give_up':
        storage.add_mission_step(mid, {'kind': 'llm', 'name': 'give_up',
                                       'result_json': res})
        return _close(mid, 'blocked', error=(res.get('reason') or '').strip())

    storage.add_mission_step(mid, {'kind': 'note', 'name': 'unparsed',
                                   'result_json': {'got': _compact(res, 300)}})
    return storage.get_mission(mid)


def launch(goal: str, origin_kind: str = 'manual', origin_ref=None,
           created_by=None, tier: str = 'mission') -> dict:
    settings = storage.get_settings() or {}
    if not settings.get('missions_enabled', False):
        return {'status': 'disabled'}
    goal = (goal or '').strip()
    if not goal:
        return {'status': 'empty'}
    if tier != 'flash' and not model_pools.api_key_for_pool('pro', settings):
        return {'status': 'no_key',
                'message': 'Missions need the paid Gemini key (Config → Missions).'}
    cap = int(settings.get('mission_cap_launch', CAPS_DEFAULT['launch']))
    if not _bump_call('launch', cap):
        return {'status': 'capped',
                'message': f"That's {cap} missions today — the cap resets tomorrow."}
    mid = storage.add_mission({'goal': goal, 'origin_kind': origin_kind,
                               'origin_ref': origin_ref, 'created_by': created_by,
                               'tier': tier})
    logger.info(f"[missions] launched {mid} ({origin_kind}): {goal[:80]}")
    return {'status': 'launched', 'mission_id': mid}


def tick(now: datetime.datetime = None) -> dict:
    """The one entry the push loop calls (mirrors mind.tick). All gating —
    enabled flag, retry promotion, one-mission-at-a-time, steps-per-tick —
    lives here so main.py stays a two-line block and tests drive this."""
    now = now or datetime.datetime.now()
    settings = storage.get_settings() or {}
    if not settings.get('missions_enabled', False):
        return {'status': 'disabled'}
    ts = now.timestamp()

    for row in storage.get_missions(status='waiting_retry'):
        if (row.get('retry_at') or 0) <= ts:
            storage.update_mission(row['id'], {'status': 'running',
                                               'retry_at': None})

    running = sorted(storage.get_missions(status='running'),
                     key=lambda r: r.get('created_at') or 0)
    out = {'status': 'ticked', 'advanced': 0}
    if running:
        mission = running[0]
        for _ in range(STEPS_PER_TICK):
            mission = step(mission)
            out['advanced'] += 1
            if mission.get('status') != 'running':
                break
    else:
        cutoff = ts - RETENTION_DAYS * 86400
        pruned = storage.prune_missions(cutoff)
        if pruned:
            out['pruned'] = pruned
    return out
