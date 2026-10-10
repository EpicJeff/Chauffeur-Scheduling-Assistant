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
import os
import threading
import time

from services import storage, model_pools

logger = logging.getLogger(__name__)

CAPS_DEFAULT = {'launch': 3, 'steps': 40, 'pro_calls': 120}
# One LLM call per 30s beat, not three: a running mission must never make
# runway/presence/prep beats wait behind it in the same push-loop tick. A
# dedicated loop is the phase-2 fix if one-per-tick proves too slow.
STEPS_PER_TICK = 1
RETRY_DELAY_S = 300
MAX_CONSEC_ERRORS = 3
# A browse (services/browse.py) runs in its own thread while the mission sits
# in `browsing`; a browse step with no result after this long is reclaimed by
# the tick (the thread died, or the process restarted).
BROWSE_LOST_S = 600
BROWSE_CAP_DEFAULT = 400
_browse_async = True                     # tests run the runner inline
RETENTION_DAYS = 120

# Default-deny read classification: a registry tool NOT named here is offered
# only in propose-wrapped form. Adding a tool to the registry later leaves it
# write-classed until someone consciously promotes it.
READ_TOOLS = frozenset({
    'list_situations', 'explain_situation',
    'get_current_state', 'get_errands', 'get_pet_status', 'get_point_balances',
    'get_family_goals', 'get_family_messages', 'list_chores',
    'list_open_findings', 'list_insights', 'list_programs',
    'get_routine_status', 'get_kid_tasks', 'get_shopping_list_items',
    'get_tonights_plate', 'get_meal_rules', 'get_occasion',
    'get_occasion_insights', 'get_occasion_gaps', 'get_run_sheet',
    'get_prep_ahead', 'search_places', 'suggest_gift_ideas',
    'search_mail', 'read_mail',
})

# Never offered, not even propose-wrapped. DMs are private space (mind law).
EXCLUDED_TOOLS = frozenset({'send_direct_message'})


def proposable_tools() -> frozenset:
    from services import agent_tools_v2, chat_actions
    return (frozenset(agent_tools_v2.TOOL_HANDLERS) - READ_TOOLS - EXCLUDED_TOOLS) \
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
    from services import agent_tools_v2
    lines = []
    for name in sorted(READ_TOOLS):
        schema = agent_tools_v2.TOOL_SCHEMAS.get(name) or {}
        props = ', '.join((schema.get('properties') or {}).keys()) or 'no args'
        lines.append(f"- READ {name}({props})")
    for name in sorted(proposable_tools()):
        schema = agent_tools_v2.TOOL_SCHEMAS.get(name) or {}
        props = ', '.join((schema.get('properties') or {}).keys()) or 'payload'
        lines.append(f"- PROPOSE {name}({props})")
    return '\n'.join(lines)


def _family_context(settings: dict) -> str:
    """The standing facts every mission needs regardless of its goal: where
    home is and who the family is. Deep context stays pull-based (the READ
    tools); this header just stops the model guessing the basics."""
    lines = []
    home = ((settings or {}).get('home_location') or '').strip()
    if home:
        lines.append(f"The family's home is: {home}. 'Here', 'near us', and "
                     "any local search mean that place — never guess a city.")
    try:
        members = [m for m in storage.get_all_members()
                   if not m.get('system') and (m.get('status') or 'active') == 'active']
    except Exception:
        members = []
    if members:
        roster = ', '.join(f"{m.get('name')} ({m.get('role') or 'member'})"
                           for m in members if m.get('name'))
        if roster:
            lines.append(f"The family: {roster}.")
    return ('\n'.join(lines) + '\n') if lines else ''


def _system_prompt(now: datetime.datetime, settings: dict = None) -> str:
    return (
        f"Today is {now.strftime('%A %Y-%m-%d')}. "
        + _family_context(settings) +
        "You are Argyle working a "
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
        '{"action":"browse","goal":"<what to learn or do on the site, in words>","site":"<the site, e.g. bodewell.com>"}\n'
        '{"action":"draft","thread_title":"<thread>","intent":"<what the '
        'message should do>"}\n'
        '{"action":"ask_user","question":"<one question>"}\n'
        '{"action":"finish","summary":"<what was achieved + what awaits '
        'approval>"}\n'
        '{"action":"give_up","reason":"<honest blocker>"}\n\n'
        "Prefer finishing with a small set of strong proposals over endless "
        "research.\n"
        "To find a thing's details, search our own mail (search_mail) before "
        "the web. To deal with a company, prefer its official site. Use browse "
        "only for what reading cannot answer, and name the site. Before any "
        "form that wants the family's details, expect a release step and wait "
        "for it. A browse that stops at a wall is a result, not a failure: the "
        "person is handed the link. Never claim a booking, a price or a slot a "
        "browse did not show.\n"
        "If the outcome is a choice the family must make, use ask_user and "
        "wait for the answer — NEVER finish with a question in your summary; "
        "a finished mission cannot hear replies.\n"
        "If information the goal depends on is missing (a budget, a "
        "preference, who it is for, dates, addresses) and no READ tool "
        "provides it, ask_user EARLY with one precise question — never "
        "guess, and never research around a blank you could just ask "
        "about.\n"
        "Summaries, questions, whys and drafts are PLAIN TEXT — no markdown, "
        "no asterisks, no ** formatting.\n"
        "When the right next move is contacting someone outside the family "
        "(a vendor, a company, a coach), propose create_thread for them — a "
        "person approves it and messages get drafted on that thread "
        "afterwards; say in your summary what the first message should "
        "cover.\n"
        "Available tools:\n" + _catalog()
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
    from services import situations as _sit
    _sit.touched('mission', mission_id)
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


def browse_dir(mission_id: str) -> str:
    """Screenshots live under the data dir, never under the moments media
    root (the wall's screensaver draws from there)."""
    d = os.path.join(os.path.dirname(storage.DB_PATH), 'browse', mission_id)
    os.makedirs(d, exist_ok=True)
    return d


def _browse_live(**kw):
    from services import browse
    return browse.run(**kw)


_browse = _browse_live


def _post(dm, argyle, body, card=None):
    from services.agent_tools_v2 import _post_chat_message
    return _post_chat_message(dm, argyle, body, card=card)


def _dm_person(mission: dict, text: str) -> None:
    """One message to whoever started the mission (the parents when nobody
    did), in their Argyle DM. Never raises."""
    try:
        argyle = storage.ensure_argyle_member()
        who = storage.get_member(mission.get('created_by') or '') if mission.get('created_by') else None
        people = [who] if who else [m for m in storage.get_all_members() if m.get('role') == 'parent' and not m.get('system')]
        for m in people:
            _post(storage.get_or_create_dm(argyle['id'], m['id']), argyle, text)
    except Exception as e:
        logger.warning(f"[missions] DM failed: {e}")


def _released_for(mission: dict, site: str) -> dict:
    """The contact-card values a parent already released to this site in
    this mission (one approval per site per mission)."""
    from services import browse as _b
    card = _b.contact_card()
    for r in mission.get('releases') or []:
        if r.get('site') == _b._domain(f'https://{site}' if '://' not in site else site):
            return {f: card[f] for f in r.get('fields') or [] if f in card}
    return {}


def start_browse(mission: dict, goal: str, site: str, start_url: str = None, released: dict = None) -> str:
    """Add the browse step, park the mission in `browsing`, run the runner in
    a daemon thread (inline in tests). Returns the step id, or '' when the
    day's turn cap refuses the run."""
    mid = mission['id']
    settings = storage.get_settings() or {}
    cap = int(settings.get('mission_cap_browse_turns', BROWSE_CAP_DEFAULT))
    day = datetime.date.today().isoformat()
    used = int((storage.get_app_state(f'mission_calls:{day}') or {}).get('browse_turns', 0))
    if used >= cap:
        storage.add_mission_step(mid, {'kind': 'note', 'name': 'refused',
                                       'result_json': {'note': f"browse cap ({cap} turns/day) reached; try tomorrow or raise it"}})
        return ''
    sid = storage.add_mission_step(mid, {'kind': 'browse', 'name': site, 'args_json': {'goal': goal, 'site': site, 'start_url': start_url},
                                         'result_json': None})
    storage.update_mission(mid, {'status': 'browsing'})
    kw = dict(goal=goal, site=site, released=released if released is not None else _released_for(mission, site),
              consent={'captcha': bool(settings.get('missions_captcha_attempts'))}, start_url=start_url, out_dir=browse_dir(mid))

    def work():
        try:
            report = _browse(**kw)
        except Exception as e:
            report = {'outcome': 'error', 'text': str(e)[:200], 'learned': {}, 'stopped_at': start_url or site, 'wanted_fields': [],
                      'turns': 0, 'tokens_in': 0, 'tokens_out': 0, 'seconds': 0, 'screenshots': [], 'filled': {}}
        finish_browse(mid, sid, report)

    if _browse_async:
        threading.Thread(target=work, daemon=True).start()
    else:
        work()
    return sid


def finish_browse(mission_id: str, step_id: str, report: dict) -> None:
    """The report becomes the step's result; the outcome maps to running (the
    planner reads it), a `release` ask, or a `handoff` ask."""
    from services import browse as _b
    mission = storage.get_mission(mission_id)
    if not mission:
        return
    step_row = next((s for s in storage.get_mission_steps(mission_id) if s['id'] == step_id), None)
    args = (step_row or {}).get('args_json') or {}
    site = args.get('site') or ''
    # Count the day's turns, whatever the outcome.
    day = datetime.date.today().isoformat()
    with storage.db_lock:
        counts = dict(storage.get_app_state(f'mission_calls:{day}') or {})
        counts['browse_turns'] = int(counts.get('browse_turns', 0)) + int(report.get('turns') or 0)
        storage.set_app_state(f'mission_calls:{day}', counts)
    shots = [os.path.basename(p) for p in report.get('screenshots') or []]
    storage.update_mission_step(step_id, {'result_json': {**report, 'screenshots': shots}})
    outcome = report.get('outcome')
    text = report.get('text') or ''
    if outcome == 'needs_release':
        card = _b.contact_card()
        fields = [f for f in report.get('wanted_fields') or [] if f in card]
        missing = [f for f in report.get('wanted_fields') or [] if f not in card]
        if not fields:
            storage.add_mission_step(mission_id, {'kind': 'note', 'name': 'browse',
                                                  'result_json': {'note': f"the form wants {', '.join(missing)}; the contact card has none of it (Missions settings)"}})
            _close(mission_id, 'running')
            return
        values = {f: card[f] for f in fields}
        domain = _b._domain(f'https://{site}')
        q = f"Share with {domain}: " + ' · '.join(values.values()) + '?'
        storage.add_mission_step(mission_id, {'kind': 'ask', 'name': 'release',
                                              'result_json': {'question': q, 'site': domain, 'fields': fields, 'values': values,
                                                              'missing': missing,
                                                              'browse': {'goal': args.get('goal'), 'site': site, 'start_url': report.get('stopped_at')}}})
        _close(mission_id, 'waiting_user')
        _dm_person(mission, f"Argyle needs a yes: {q} (mission: {mission.get('goal')}). Approve on the Missions page or the thread card.")
        return
    if outcome == 'captcha_failed' or (outcome == 'blocked' and 'payment' in text.lower()):
        url = report.get('stopped_at') or ''
        filled = report.get('filled') or {}
        reason = text
        q = (f"I got as far as {url}. " + (f"Filled so far: {', '.join(f'{k}={v}' for k, v in filled.items())}. " if filled else '')
             + f"{reason}. Finish it on your phone and tell me what you found.")
        storage.add_mission_step(mission_id, {'kind': 'ask', 'name': 'handoff',
                                              'result_json': {'question': q, 'url': url, 'filled': filled, 'reason': reason}})
        _close(mission_id, 'waiting_user')
        _dm_person(mission, q)
        return
    _close(mission_id, 'running')


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
    res = _llm(mission, _system_prompt(now, settings), _user_prompt(mission),
               settings)
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
        from services import agent_tools_v2
        out = agent_tools_v2.execute_tool(name, res.get('args') or {})
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
        from services import situations as _sit
        _sit.touched('mission', mid)
        return storage.get_mission(mid)

    if action == 'research':
        from services import web
        out = web.research((res.get('question') or '').strip())
        storage.add_mission_step(mid, {'kind': 'tool', 'name': 'research',
                                       'args_json': {'question': res.get('question')},
                                       'result_json': out})
        return storage.get_mission(mid)

    if action == 'browse':
        goal = (res.get('goal') or '').strip()
        site = (res.get('site') or '').strip().lower().replace('https://', '').replace('http://', '').split('/')[0]
        if not goal or not site:
            storage.add_mission_step(mid, {'kind': 'note', 'name': 'refused',
                                           'result_json': {'note': 'browse needs a goal and a site'}})
            return storage.get_mission(mid)
        start_browse(storage.get_mission(mid), goal, site)
        return storage.get_mission(mid)

    if action == 'draft':
        thread = None
        if mission.get('origin_kind') == 'thread':
            thread = storage.get_thread(mission.get('origin_ref'))
        thread = thread or _match_thread(res.get('thread_title'))
        if not thread:
            storage.add_mission_step(mid, {'kind': 'note', 'name': 'refused',
                'result_json': {'note': 'no unambiguous thread matched — a tie '
                                        'declines; ask the user which thread, or '
                                        'finish with the draft text in your '
                                        'summary'}})
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


def _seed_thread_context(mission_id: str, thread: dict) -> None:
    """Doorway 2 (thread) must not ship the mission blind (spec: the mission's
    context needs title/goal/counterparty/history-tail). One note step, added
    before the engine ever calls the model, so the very first digest
    `_user_prompt` builds already carries what the thread knows — before this
    fix all it said was '(Opened from thread <id>)', an opaque id the model
    has no way to use. Covers both thread doorways at once (the button and
    chat's fuzzy title match) because both funnel through `launch()`."""
    counterparty = {k: thread.get(k) for k in
                    ('counterparty_name', 'counterparty_email', 'contact_id')}
    history_tail = [{'kind': h.get('kind'), 'text': _compact(h.get('text'), 300)}
                    for h in (thread.get('history') or [])[-5:]]
    storage.add_mission_step(mission_id, {'kind': 'note', 'name': 'thread_context',
        'result_json': {
            'title': thread.get('title'),
            'goal': thread.get('goal'),
            'counterparty': counterparty,
            'state': thread.get('state'),
            'next_action': thread.get('next_action'),
            'next_action_at': thread.get('next_action_at'),
            'history_tail': history_tail,
        }})


def launch(goal: str, origin_kind: str = 'manual', origin_ref=None,
           created_by=None, tier: str = 'mission') -> dict:
    settings = storage.get_settings() or {}
    if not settings.get('missions_enabled', False):
        return {'status': 'disabled',
                'message': 'Missions are switched off (Config → Missions).'}
    goal = (goal or '').strip()
    if not goal:
        return {'status': 'empty', 'message': 'Give the mission a goal first.'}
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
    if origin_kind == 'thread' and origin_ref:
        thread = storage.get_thread(origin_ref)
        if thread:
            _seed_thread_context(mid, thread)
    from services import situations as _sit
    _sit.touched('mission', mid)
    logger.info(f"[missions] launched {mid} ({origin_kind}): {goal[:80]}")
    return {'status': 'launched', 'mission_id': mid,
            'message': 'Mission started — watch the Missions page; nothing '
                       'runs without approval.'}


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

    # A browse whose thread died (crash, restart) must not strand the mission.
    for row in storage.get_missions(status='browsing'):
        steps = storage.get_mission_steps(row['id'])
        b = next((s for s in reversed(steps) if s.get('kind') == 'browse'), None)
        if b and b.get('result_json') is None and (b.get('ts') or 0) < ts - BROWSE_LOST_S:
            storage.add_mission_step(row['id'], {'kind': 'note', 'name': 'browse',
                                                 'result_json': {'note': 'the browse was lost (no result after 10 minutes)'}})
            storage.update_mission(row['id'], {'status': 'running'})

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
