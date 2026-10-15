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
import re
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
# the tick (the thread died, or the process restarted). Longer than the
# runner's own clock (browse.DEFAULT_CAPS['seconds'], 600 s) plus a slow last
# model call, so a live worker is never reclaimed mid-run.
BROWSE_LOST_S = 900
BROWSE_CAP_DEFAULT = 400
_browse_async = True                     # tests run the runner inline
RETENTION_DAYS = 120
# Full subject lookups reach the next planner call once, never storage.
_last_lookups = {}
# A browse must still be about the record the planner read.
_plan_subject = {}

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
    'search_mail', 'read_mail', 'find_in_chauffeur',
    'get_calendar_events', 'get_household_tasks', 'get_household_load',
    'get_requests', 'get_assist_coverage', 'list_threads', 'program_progress',
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


def _system_prompt(now: datetime.datetime, settings: dict = None, mission: dict = None) -> str:
    return (
        f"Today is {now.strftime('%A %Y-%m-%d')}. "
        + _family_context(settings) + about_block(mission) +
        "You are Argyle working a "
        "MISSION for the family: a multi-step goal you advance one action at "
        "a time. You cannot execute changes yourself — every change you want "
        "is a PROPOSAL a parent approves later, and drafted messages are "
        "never sent by you (a person reviews and sends). Never claim "
        "something was sent, booked, or paid that the transcript does not "
        "show (a `submitted` note).\n\n"
        "A user_steer note is the person correcting course and outranks the goal's earlier reading.\n"
        "When the goal names something the family already has and no ABOUT block is above, call find_in_chauffeur first and bind it with the subject action; when ABOUT is above, it is the truth, not the transcript's older reading; a subject_changed note means re-read before acting.\n"
        "Respond with EXACTLY ONE JSON object, one of:\n"
        '{"action":"tool","tool":"<READ tool>","args":{...}}\n'
        '{"action":"subject","kind":"<kind>","id":"<id from find_in_chauffeur>"}\n'
        '{"action":"propose","tool":"<PROPOSE tool>","args":{...},'
        '"summary":"<one line a parent reads>","why":"<reason>"}\n'
        '{"action":"research","question":"<web question>"}\n'
        '{"action":"browse","goal":"<what to learn or do on the site, in words>","site":"<the site, e.g. bodewell.com>",'
        '"start_url":"<optional: to RESUME a capped browse, its stopped_at>"}\n'
        '{"action":"draft","thread_title":"<thread>","intent":"<what the '
        'message should do>"}\n'
        '{"action":"ask_user","question":"<one question>"}\n'
        '{"action":"finish","summary":"<what was achieved + what awaits '
        'approval>","next_action":"<the one thing the person should do next, '
        'short, imperative; optional>","next_action_at":"<YYYY-MM-DD, optional>"}\n'
        '{"action":"give_up","reason":"<honest blocker>"}\n\n'
        "Prefer finishing with a small set of strong proposals over endless "
        "research.\n"
        "To find a thing's details, search our own mail (search_mail) before "
        "the web. To deal with a company, prefer its official site. Use browse "
        "only for what reading cannot answer, and name the site. Before any "
        "form that wants the family's details, expect a release step and wait "
        "for it. A browse that stops at a wall (a check, a payment field) is a "
        "result, not a failure: the person is handed the link. A browse that was "
        "capped (out of turns or time) is unfinished: resume it ONCE with "
        "start_url set to its stopped_at. Start a browse at the deepest relevant "
        "URL you already know (the scheduling page research found, where a past "
        "browse stopped), not the home page. The thread's earlier notes and next "
        "step ('call them', a past conclusion) are history to verify by browsing, "
        "never facts to repeat: a site needs a phone call only when a browse of it "
        "in THIS mission showed so. Never claim a booking, a price or a slot a "
        "browse did not show, and never finish with 'I found the site' or 'it "
        "requires a phone call' when the goal asked for windows, a fee or a way to "
        "book and you have not browsed: browse, resume, ask the person, or hand "
        "them the link.\n"
        + ("A browse may end needs_submit: a parent is asked to approve the press; wait for it. A `submit_attempt` on the transcript whose "
           "outcome is not confirmed, rejected, continued or failed is a commitment that may have happened: never press again on this "
           "mission; ask the person. After a `submitted` note the thing IS booked: say so, and never book it twice.\n"
           if (settings or {}).get('missions_submit_enabled', True) else
           "Booking is off for this family: a browse never books or submits; hand the person the link instead.\n") +
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
    last_real = max((i for i, s in enumerate(steps)
                     if s.get('kind') in ('browse', 'tool', 'proposal', 'ask', 'draft')), default=-1)
    steers = [s for s in steps[last_real + 1:]
              if s.get('kind') == 'note' and s.get('name') == 'user_steer']
    if steers:
        lines.append("THE PERSON SAID, MID-MISSION (act on this before anything else):")
        lines.extend(f"- {(s.get('result_json') or {}).get('text') or ''}" for s in steers)
    lines.append("TRANSCRIPT SO FAR (oldest first):")
    for s in steps[-25:]:
        rj = s.get('result_json')
        if s['kind'] == 'browse' and isinstance(rj, dict):
            # The planner reads the outcome, where it stopped and what was
            # learned before the model's prose; the turn ledger is for people.
            rj = {'outcome': rj.get('outcome'), 'stopped_at': rj.get('stopped_at'), 'learned': rj.get('learned'),
                  'wanted_fields': rj.get('wanted_fields'), 'turns': rj.get('turns'), 'text': (rj.get('text') or '')[:500],
                  'submit': {'button': (rj.get('submit') or {}).get('button')} if rj.get('submit') else None,
                  'attempt': {'outcome': (rj.get('attempt') or {}).get('outcome')} if rj.get('attempt') else None}
        lines.append(f"[{s['idx']}] {s['kind']} {s.get('name') or ''} "
                     f"args={_compact(s.get('args_json'), 200)} "
                     f"result={_compact(rj)}")
    if not steps:
        lines.append("(none yet — plan your first move)")
    lookup = _last_lookups.pop(mission['id'], None)
    if lookup is not None:
        lines.append("LAST LOOKUP (shown once, not kept):")
        lines.append(json.dumps(lookup, ensure_ascii=False))
    lines.append("Reply with your ONE next action as JSON.")
    return '\n'.join(lines)


def _close(mission_id: str, status: str, **fields) -> dict:
    before = storage.get_mission(mission_id) or {}
    fields = {'status': status, **fields}
    if status in ('done', 'blocked', 'dropped'):
        fields.setdefault('finished_at', time.time())
    storage.update_mission(mission_id, fields)
    from services import situations as _sit
    _sit.touched('mission', mission_id)
    # The thread carries its mission's ask (browse missions §4): when the
    # mission starts or stops waiting on the person, or ends, the thread
    # moved too, so its note is re-asked for with the ask in its facts.
    if before.get('origin_kind') == 'thread' and before.get('origin_ref') and (
            status in ('waiting_user', 'done', 'blocked', 'dropped') or before.get('status') == 'waiting_user'):
        _sit.touched('thread', before['origin_ref'])
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


def ask_card(mission: dict) -> dict | None:
    """Draw the current ask with the mission's own situation options."""
    from services import situations
    row = situations.load('mission', mission['id'])
    if not row or not (row.get('status') == 'waiting_user' or verify_open(row)):
        return None
    opts = [o for o in situations._options_mission(row)
            if o['verb'] in ('answer', 'release', 'submit', 'verify')]
    if not opts:
        return None
    asked = next((s for s in reversed(row.get('steps') or []) if s.get('kind') == 'ask'), None)
    if not asked:
        return None
    result = asked.get('result_json') or {}
    card = {'kind': 'mission_ask', 'mission_id': mission['id'], 'ask_id': asked['id'],
            'ask': asked.get('name'), 'question': result.get('question'),
            'goal': mission.get('goal'), 'state': 'open', 'options': opts}
    card.update({k: result[k] for k in ('site', 'url', 'facts', 'button', 'fields', 'values') if k in result})
    return card


def _card_moved(message: dict) -> None:
    """An open phone redraws a settled card (the same SSE a new message fires);
    main is the running app module and absent in tests."""
    try:
        import main as _main
        channel = storage.get_channel(message.get('channel_id')) or {}
        recipients = channel.get('member_ids') if channel.get('kind') in ('dm', 'group') else None
        _main._push_message_event(message.get('channel_id'), recipients)
    except Exception:
        pass


def settle_ask_cards(mission_id, ask_id, outcome: str) -> None:
    """All copies of an ask follow its decision. Safe to repeat; never raises."""
    try:
        asked = next((s for s in storage.get_mission_steps(mission_id)
                      if s.get('kind') == 'ask' and s['id'] == ask_id), None)
        for message_id in (asked or {}).get('chat_message_ids') or []:
            try:
                with storage.db_lock:
                    card = (storage.get_chat_message(message_id) or {}).get('card')
                    if card and card.get('kind') == 'mission_ask' and card.get('ask_id') == ask_id:
                        storage.update_chat_message_card(message_id, {
                            **card, 'state': 'answered', 'outcome': outcome, 'options': []})
                        _card_moved(storage.get_chat_message(message_id) or {})
            except Exception as e:
                logger.warning(f"[missions] card settlement failed: {e}")
    except Exception as e:
        logger.warning(f"[missions] card settlement failed: {e}")


def subject_of(mission: dict) -> tuple:
    """A thread-origin mission always reads its subject from the thread."""
    row = mission or {}
    if row.get('origin_kind') == 'thread' and row.get('origin_ref'):
        row = storage.get_thread(row['origin_ref']) or {}
    if not row.get('subject_kind'):
        return (None, None, 0)
    return (row['subject_kind'], row.get('subject_id'), int(row.get('subject_rev') or 0))


def read_viewer(mission: dict) -> dict:
    """Generic reads may store only what the transcript's audience may see."""
    from services import subjects
    adult = {'id': None, 'role': 'adult'}
    parent = {'id': None, 'role': 'parent'}
    records = subjects.subject_records('mission', mission or {})
    if records and all(not subjects.visible(kind, row, adult)
                       and subjects.visible(kind, row, parent) for kind, row in records):
        return parent
    return adult


def _finder(mission: dict) -> dict | None:
    """Read as the creator who still has access, else the parent of record."""
    from services import situations
    member = storage.get_member((mission or {}).get('created_by') or '')
    return member if member and storage.member_has_access(member) else situations.parent_of_record()


def about_block(mission: dict) -> str:
    """Fresh subject context for this call only, authorised as the finder."""
    from services import subjects
    kind, sid, _ = subject_of(mission)
    if not kind:
        return ''
    ctx = subjects.context(kind, sid, _finder(mission))
    if ctx is None:
        return "ABOUT: the subject is not readable here; do not guess its contents.\n"
    row = subjects.load(kind, sid)
    if row is None:
        return "ABOUT: the subject is not readable here; do not guess its contents.\n"
    title = subjects.title_of(kind, row)
    facets = ', '.join(subjects.facets(kind)) or 'none'
    return (f'ABOUT: {kind} "{title}"\n{ctx}\n'
            f'(This is the record as it stands now; it outranks anything older in the transcript. '
            f'Facets you can read with find_in_chauffeur: {facets}.)\n')


def _dm_person(mission: dict, text: str) -> None:
    """One message to whoever started the mission (the parents when nobody
    did), in their Argyle DM. Never raises."""
    try:
        steps = storage.get_mission_steps(mission['id'])
        newest = next((s for s in reversed(steps) if s.get('kind') == 'ask'), None)
        for step in steps:
            if step.get('kind') != 'ask' or step['id'] == (newest or {}).get('id'):
                continue
            if any(((storage.get_chat_message(i) or {}).get('card') or {}).get('state') == 'open'
                   for i in step.get('chat_message_ids') or []):
                settle_ask_cards(mission['id'], step['id'], 'Moved on')
        card = ask_card(mission)
        argyle = storage.ensure_argyle_member()
        who = storage.get_member(mission.get('created_by') or '') if mission.get('created_by') else None
        people = [who] if who else [m for m in storage.get_all_members() if m.get('role') == 'parent' and not m.get('system')]
        if not who:
            from services import situations
            people = [m for m in people if situations.can_see('mission', mission, m)]
        for m in people:
            message = _post(storage.get_or_create_dm(argyle['id'], m['id']), argyle, text, card=card)
            if card and message and message.get('id'):
                with storage.db_lock:
                    asked = next(s for s in storage.get_mission_steps(mission['id']) if s['id'] == card['ask_id'])
                    ids = list(asked.get('chat_message_ids') or [])
                    ids.append(message['id'])
                    # Keep delivery metadata out of the result hashed by voice approval.
                    storage.update_mission_step(asked['id'], {'chat_message_ids': ids})
    except Exception as e:
        logger.warning(f"[missions] DM failed: {e}")


def _released_for(mission: dict, site: str) -> dict:
    """The contact-card values a parent already released to this site in
    this mission (one approval per site per mission)."""
    from services import browse as _b
    card = _b.contact_card()
    for r in mission.get('releases') or []:
        if r.get('site') == _b._domain(f'https://{site}' if '://' not in site else site):
            if (r.get('approval_context') or {}).get('channel') == 'voice':
                return dict(r.get('approved_values') or {})
            return {f: card[f] for f in r.get('fields') or [] if f in card}
    return {}


# --- the submit gate (spec 2026-10-11) ----------------------------------------

BOOK_WORDS = re.compile(r'(book|schedul|appointment|reserv)', re.I)
UNRESOLVED = (None, 'unknown')


def attempts_for(mission_id: str) -> list:
    """Every submit_attempt on the mission, oldest first, each with its step id."""
    out = []
    for s in storage.get_mission_steps(mission_id):
        if s.get('kind') == 'note' and s.get('name') == 'submit_attempt' and isinstance(s.get('result_json'), dict):
            out.append({**s['result_json'], 'step_id': s['id']})
    return out


def _write_attempt(step_id: str, data: dict) -> None:
    storage.update_mission_step(step_id, {'result_json': {k: v for k, v in data.items() if k != 'step_id'}})


def _submit_verb(record: dict, goal: str) -> str:
    text = ' '.join([record.get('button') or '', record.get('intent') or '', goal or ''])
    return 'book' if BOOK_WORDS.search(text) else 'submit'


def submit_question(domain: str, verb: str, facts: dict, button: str) -> str:
    """Deterministic (spec §2): '{Book|Submit} at {domain}: {facts} (button '{button}')?'"""
    lead = 'Book' if verb == 'book' else 'Submit'
    vals = [str(v) for v in (facts or {}).values() if str(v).strip()]
    if vals:
        return f"{lead} at {domain}: {', '.join(vals)} (button '{button}')?"
    return f"{lead} at {domain} with the button '{button}'?"


def _on_attempt_for(mission_id: str, step_id: str):
    """The runner's authorization and record, in one lock (spec §2): this
    browse is live, its approval is this ask and unspent, no attempt on the
    mission is unresolved; then the attempt note and the spent mark."""
    def on_attempt(record: dict) -> bool:
        with storage.db_lock:
            mission = storage.get_mission(mission_id)
            if not mission or mission.get('status') != 'browsing':
                return False
            steps = storage.get_mission_steps(mission_id)
            newest = next((s for s in reversed(steps) if s.get('kind') == 'browse'), None)
            if not newest or newest['id'] != step_id:
                return False
            args = dict(newest.get('args_json') or {})
            if not args.get('approved_ask_id') or args.get('approved_ask_id') != record.get('ask_id') or args.get('approval_spent'):
                return False
            if any(a.get('outcome') in UNRESOLVED for a in attempts_for(mission_id)):
                return False
            storage.update_mission_step(step_id, {'args_json': {**args, 'approval_spent': True}})
            storage.add_mission_step(mission_id, {'kind': 'note', 'name': 'submit_attempt',
                                                  'result_json': {'ask_id': record.get('ask_id'), 'browse_step_id': step_id, 'button': record.get('button'),
                                                                  'url': record.get('url'), 'state': record.get('state') or {}, 'pressed_at': record.get('pressed_at') or time.time(),
                                                                  'outcome': None, 'text': ''}})
        return True
    return on_attempt


def _ask_by_id(mission_id: str, ask_id: str):
    if not ask_id:
        return None
    return next((s for s in storage.get_mission_steps(mission_id) if s.get('kind') == 'ask' and s['id'] == ask_id), None)


def _confirmation_number(text: str) -> str:
    m = re.search(r'confirmation\s*(?:number|#|code|no\.?)?\s*[:#]?\s*([A-Z0-9-]{4,})', text or '', re.I)
    return m.group(1) if m else ''


def _resolve_attempts(mission_id: str, step_id: str, report: dict, live: bool) -> None:
    """The report's attempts onto their notes: `attempt` and every record in
    `attempts_extra` (an unasked press beside an approved one). A human
    resolution is never overwritten; an unasked attempt is added after the
    fact; only `on_attempt` mints an approved attempt's note, so a reported
    attempt with no note is never invented here. Then, always, a pending
    attempt on this step with nothing said about it is unknown now (nothing
    is left to the reclaim). Under db_lock: each note is a read-modify-write
    that a parent's verify tap (same lock) must never interleave with."""
    with storage.db_lock:
        _resolve_attempts_locked(mission_id, step_id, report, live)


def _resolve_attempts_locked(mission_id: str, step_id: str, report: dict, live: bool) -> None:
    reps = [r for r in [report.get('attempt')] + list(report.get('attempts_extra') or []) if isinstance(r, dict)]
    for rep in reps:
        if rep.get('unasked'):
            storage.add_mission_step(mission_id, {'kind': 'note', 'name': 'submit_attempt',
                                                  'result_json': {'ask_id': None, 'browse_step_id': step_id, 'button': rep.get('button') or '', 'url': rep.get('url') or '',
                                                                  'state': rep.get('state') or {}, 'pressed_at': rep.get('pressed_at') or time.time(), 'outcome': 'unknown',
                                                                  'text': (rep.get('text') or '')[:500], 'unasked': True}})
            continue
        for a in attempts_for(mission_id):
            if a.get('browse_step_id') != step_id or a.get('unasked') or a.get('ask_id') != rep.get('ask_id'):
                continue
            if a.get('resolved_by'):
                late = list(a.get('late_reports') or []) + [{'outcome': rep.get('outcome') or 'unknown', 'text': (rep.get('text') or '')[:300], 'ts': time.time()}]
                _write_attempt(a['step_id'], {**a, 'late_reports': late})
                if (rep.get('outcome') or 'unknown') != a.get('outcome'):
                    storage.add_mission_step(mission_id, {'kind': 'note', 'name': 'late_evidence',
                                                          'result_json': {'note': f"the browser later reported '{(rep.get('text') or rep.get('outcome') or '')[:120]}'; "
                                                                                  f"{a['resolved_by'].get('name') or 'the parent'}'s answer stands"}})
            else:
                _write_attempt(a['step_id'], {**a, 'outcome': rep.get('outcome') or 'unknown', 'text': (rep.get('text') or '')[:500]})
    if live:
        for a in attempts_for(mission_id):
            if a.get('browse_step_id') == step_id and a.get('outcome') is None:
                _write_attempt(a['step_id'], {**a, 'outcome': 'unknown'})


def _changed_lead(line: str) -> str:
    """'selected: Thu (approved: Tue)' reads 'selected Thu (approved: Tue)'."""
    return re.sub(r'^(\w+):\s*', r'\1 ', (line or '').strip())


def _submit_ask(mission: dict, args: dict, report: dict) -> None:
    from services import browse as _b
    rec = report['submit']
    site = args.get('site') or ''
    domain = _b._domain(rec.get('url') or f'https://{site}')
    verb = _submit_verb(rec, mission.get('goal'))
    # The price is part of what is approved: when the model's facts name no
    # amount (an approved re-run often has none), the page's own prices do.
    qfacts = dict(rec.get('facts') or {})
    prices = list(dict.fromkeys((rec.get('state') or {}).get('prices') or []))
    if prices and not any(_b.MONEY.search(str(v)) for v in qfacts.values()):
        qfacts['price'] = ', '.join(prices)
    q = submit_question(domain, verb, qfacts, rec.get('button') or 'the button')
    changed = list(report.get('changed') or [])
    # A re-ask names everything that moved, not only the first thing; the
    # bare "text: changed" is implied by any other line and said alone otherwise.
    lead = [_changed_lead(c) for c in changed if (c or '').strip() != 'text: changed']
    if lead:
        q = f"The page changed: {'; '.join(lead)}. {q}"
    elif changed:
        q = f"The page changed since you approved. {q}"
    storage.add_mission_step(mission['id'], {'kind': 'ask', 'name': 'submit',
                                             'result_json': {'question': q, 'verb': verb, 'site': domain, 'url': rec.get('url'), 'button': rec.get('button'),
                                                             'state': rec.get('state') or {}, 'display': rec.get('display') or '', 'facts': rec.get('facts') or {},
                                                             'intent': rec.get('intent') or '', 'filled': report.get('filled') or {}, 'changed': changed,
                                                             'browse': {'goal': args.get('goal'), 'site': site, 'start_url': rec.get('url'),
                                                                        'released': _released_for(mission, site)}}})
    _close(mission['id'], 'waiting_user')
    # The approve button reads the question itself (never a blind "Book it"), so the DM points at the question.
    what = 'booking question' if verb == 'book' else 'question'
    _dm_person(mission, f"{q} (mission: {mission.get('goal')}). Tap the {what} here, on the Missions page or the thread card to approve it, "
                        f"or I'll finish it myself / Stop there.")


VERIFY_TAIL = " (Tap It went through / It did not go through here, on the Missions page or the thread card.)"


def _add_verify_ask(mission_id: str, attempt: dict, payment: bool = False) -> str:
    """The verify ask's step alone (storage only, safe under db_lock); returns the question."""
    url, button = attempt.get('url') or '', attempt.get('button') or 'the button'
    if payment:
        q = f"I pressed '{button}' at {url}; the page then asked for payment, which I never enter. Check whether the request went through, then tell me below."
    else:
        q = f"I pressed '{button}' at {url} and could not read whether it went through. Check your email or the site, then tell me below."
    ask = (_ask_by_id(mission_id, attempt.get('ask_id')) or {}).get('result_json') or {}
    storage.add_mission_step(mission_id, {'kind': 'ask', 'name': 'verify',
                                          'result_json': {'question': q, 'attempt_step_id': attempt['step_id'], 'button': button, 'url': url,
                                                          'facts': ask.get('facts') or {}, 'display': ask.get('display') or '', 'payment': bool(payment)}})
    return q


def _verify_ask(mission: dict, attempt: dict, payment: bool = False) -> None:
    """The press happened and nobody can read whether it went through: the
    parent says (spec §2). An unasked attempt has no submit ask behind it."""
    q = _add_verify_ask(mission['id'], attempt, payment)
    _close(mission['id'], 'waiting_user')
    _dm_person(mission, q + VERIFY_TAIL)


def _unverified_handoff(mission: dict, report: dict) -> None:
    """The runner reported a press (submitted / submit_unknown) and no attempt
    on this step backs it: nothing is counted as booked; the person checks."""
    att = report.get('attempt') or {}
    url = att.get('url') or report.get('stopped_at') or ''
    button = att.get('button') or 'a button'
    q = (f"The browser reported pressing '{button}' at {url}, but no approved press is on record, so I am not counting "
         f"anything as booked. Check your email or the site and tell me what you found.")
    storage.add_mission_step(mission['id'], {'kind': 'ask', 'name': 'handoff',
                                             'result_json': {'question': q, 'url': url, 'filled': report.get('filled') or {}, 'reason': 'unverified press'}})
    _close(mission['id'], 'waiting_user')
    _dm_person(mission, q)


def _pending_ask(mission_id: str, name: str):
    steps = storage.get_mission_steps(mission_id)
    ask = next((s for s in reversed(steps) if s.get('kind') == 'ask'), None)
    return ask if ask and ask.get('name') == name else None


TERMINAL = ('done', 'blocked', 'dropped')
TAP_ONLY_ASKS = ('release', 'submit', 'verify')


def _unverified(mission_id: str) -> list:
    """Every attempt on the mission at `unknown` that the pending verify ask
    (the newest ask, when it is a verify) does not already ask about."""
    steps = storage.get_mission_steps(mission_id)
    newest = next((s for s in reversed(steps) if s.get('kind') == 'ask'), None)
    covered = (newest.get('result_json') or {}).get('attempt_step_id') if newest and newest.get('name') == 'verify' else None
    return [a for a in attempts_for(mission_id) if a.get('outcome') == 'unknown' and a['step_id'] != covered]


def verify_open(mission: dict) -> bool:
    """A verify ask a parent can still answer: the newest ask is a verify
    whose attempt is unresolved, on a waiting mission or on one that ended
    before the late report arrived (spec §2; final review I1)."""
    steps = mission.get('steps') if mission.get('steps') is not None else storage.get_mission_steps(mission.get('id') or '')
    ask = next((s for s in reversed(steps or []) if s.get('kind') == 'ask'), None)
    if not ask or ask.get('name') != 'verify':
        return False
    if mission.get('status') == 'waiting_user':
        return True
    aid = (ask.get('result_json') or {}).get('attempt_step_id')
    att = next((s for s in (steps or []) if s.get('id') == aid), None)
    return mission.get('status') in TERMINAL and bool(att) and (att.get('result_json') or {}).get('outcome') in UNRESOLVED


def tap_only_ask_pending(mission_id: str) -> bool:
    """A release, submit or verify is waiting on a tap: free text never answers
    it (the answer path would move the mission and bury the ask)."""
    mission = storage.get_mission(mission_id) or {}
    ask = next((s for s in reversed(storage.get_mission_steps(mission_id)) if s.get('kind') == 'ask'), None)
    if not ask or ask.get('name') not in TAP_ONLY_ASKS:
        return False
    return mission.get('status') == 'waiting_user' or verify_open({**mission, 'id': mission_id})


def answer(mission_id: str, text: str, actor: dict) -> dict:
    """The one free-text door: answer a question or steer a live mission."""
    if (actor or {}).get('role') not in ('parent', 'adult'):
        return {'status': 'refused', 'message': 'Only a parent or adult can handle these.'}
    with storage.db_lock:
        mission = storage.get_mission(mission_id)
        if not mission:
            return {'status': 'error', 'message': 'No such mission'}
        text = (text or '').strip()
        if not text:
            return {'status': 'error', 'message': 'Say something to send.'}
        if tap_only_ask_pending(mission_id):
            return {'status': 'error', 'message': 'Answer that one with its buttons.'}
        status = mission.get('status')
        if status in TERMINAL:
            return {'status': 'error', 'message': 'That mission has ended.'}
        if status == 'waiting_user':
            storage.add_mission_step(mission_id, {'kind': 'note', 'name': 'user_answer', 'result_json': {'text': text}})
            storage.update_mission(mission_id, {'status': 'running'})
            message = 'Answered.'
        elif status in ('running', 'browsing', 'waiting_retry'):
            storage.add_mission_step(mission_id, {'kind': 'note', 'name': 'user_steer', 'result_json': {'text': text}})
            if status == 'browsing':
                storage.set_app_state(f'mission_steer:{mission_id}', {'text': text, 'ts': time.time()})
            message = 'Told it; it picks that up at its next step.'
        else:
            return {'status': 'error', 'message': 'That mission cannot take an answer right now.'}
    from services import situations
    situations.touched('mission', mission_id)
    return {'status': 'success', 'message': message}


def _steer_check(mission_id: str):
    """Consume a person's stop flag once, between browse turns."""
    def check():
        with storage.db_lock:
            key = f'mission_steer:{mission_id}'
            steer = storage.get_app_state(key)
            if steer:
                storage.set_app_state(key, {})
                return steer.get('text')
        return None
    return check


def _late_verify(mission_id: str) -> None:
    """A late report that left an attempt at `unknown` with no verify ask on
    it (an unasked press the backstop caught after the mission moved on):
    the parent is asked, never left with an attempt that bars every later
    press. A live browse finishes for itself; an ended mission keeps its
    status and is told the booking may have happened."""
    with storage.db_lock:
        mission = storage.get_mission(mission_id) or {}
        if not mission or mission.get('status') == 'browsing':
            return
        orphans = _unverified(mission_id)
        if not orphans:
            return
        q = _add_verify_ask(mission_id, orphans[-1])
        ended = mission.get('status') in TERMINAL
        if not ended:
            storage.update_mission(mission_id, {'status': 'waiting_user'})
    if ended:
        from services import situations as _sit
        _sit.touched('mission', mission_id)
        _dm_person(mission, f"This mission had already ended, but a booking may have happened after all. {q}{VERIFY_TAIL}")
        return
    _close(mission_id, 'waiting_user')
    _dm_person(mission, q + VERIFY_TAIL)


def submit(mission_id: str, decision: str, actor: dict, ask_id: str = None, approval_context=None) -> dict:
    """A parent's answer to a submit ask (spec §2). The ask id IS the approval:
    a stale or missing id answers `moved` and changes nothing."""
    if not actor or (actor.get('role') or '') not in ('parent', 'adult'):
        return {'status': 'refused', 'message': 'Only a parent or adult can approve a booking.'}
    mission = storage.get_mission(mission_id)
    if not mission:
        return {'status': 'error', 'message': 'No such mission.'}
    moved = {'status': 'success', 'moved': True, 'message': 'That question has moved on; look at the card again.'}
    if decision == 'approve' and not (storage.get_settings() or {}).get('missions_submit_enabled', True):
        # The switch is off: an approval re-runs nothing (the card offers no
        # approve then; this is the door for a card drawn before the switch moved).
        return {'status': 'success', 'message': 'Booking is switched off (Missions → Browser).'}
    with storage.db_lock:
        row = storage.get_mission(mission_id) or {}
        ask = _pending_ask(mission_id, 'submit')
        if not ask or row.get('status') != 'waiting_user':
            return {'status': 'success', 'already': True, 'message': 'That was already answered.'}
        if not ask_id or ask['id'] != ask_id:
            return moved
        rj = ask.get('result_json') or {}
        if approval_context is not None:
            from services import voice_approval
            if not voice_approval.valid(approval_context, ask, actor):
                return {'status': 'refused', 'message': 'The booking or your verification changed. Ask for a new readback.'}
        rec = {k: rj.get(k) for k in ('button', 'url', 'state', 'display', 'facts', 'intent')}
        # The decision is claimed under the lock: a second tap after this
        # finds the mission (or its newest ask) moved and answers `already`.
        if decision == 'approve':
            storage.update_mission(mission_id, {'status': 'running',
                                               **({'voice_approval': approval_context.record()} if approval_context else {})})
        elif decision == 'decline':
            q = f"I got as far as {rec['url']}. I did not press '{rec['button']}'. Finish it yourself and tell me what you found."
            storage.add_mission_step(mission_id, {'kind': 'ask', 'name': 'handoff',
                                                  'result_json': {'question': q, 'url': rec['url'], 'filled': rj.get('filled') or {}, 'reason': 'not approved'}})
        elif decision == 'stop':
            err = _stop_text(mission_id)
            storage.update_mission(mission_id, {'status': 'blocked', 'error': err, 'finished_at': time.time()})
        else:
            return {'status': 'error', 'message': 'approve, decline or stop'}
    if decision == 'approve':
        storage.add_mission_step(mission_id, {'kind': 'note', 'name': 'submit_approved',
                                              'result_json': {'ask_id': ask_id, 'button': rec['button'], 'url': rec['url'], 'approved_by': actor.get('id'),
                                                              **({'approval_context': approval_context.record()} if approval_context else {})}})
        pending = rj.get('browse') or {}
        sid = start_browse(storage.get_mission(mission_id), pending.get('goal') or mission.get('goal'), pending.get('site') or rj.get('site'),
                           start_url=rec['url'], released=pending.get('released'), approved={**rec, 'ask_id': ask_id})
        if not sid:
            # The day's turn cap refused the run (start_browse noted it; the mission runs on).
            return {'status': 'success', 'message': 'The browse cap for today is reached; try tomorrow or raise it.'}
        return {'status': 'success', 'message': ('Booking' if rj.get('verb') == 'book' else 'Submitting') + ' it now.'}
    if decision == 'decline':
        _close(mission_id, 'waiting_user')
        _dm_person(mission, q)
        return {'status': 'success', 'message': 'Left it to you.'}
    _close(mission_id, 'blocked', error=err)
    return {'status': 'success', 'message': 'Stopped.'}


def _stop_text(mission_id: str) -> str:
    atts = attempts_for(mission_id)
    conf = next((a for a in reversed(atts) if a.get('outcome') == 'confirmed'), None)
    if conf:
        return f"stopped; the booking already made stands (confirmation {_confirmation_number(conf.get('text') or conf.get('detail') or '') or 'on record'})"
    open_ = next((a for a in reversed(atts) if a.get('outcome') in UNRESOLVED), None)
    if open_:
        return f"stopped; a press of '{open_.get('button')}' at {open_.get('url')} may have gone through: check your email or the site"
    return 'the family did not book'


def verify(mission_id: str, ask_id: str, outcome: str, actor: dict, detail: str = '') -> dict:
    """A parent resolves an attempt by tap: confirmed, failed or unsure (spec §2)."""
    if not actor or (actor.get('role') or '') not in ('parent', 'adult'):
        return {'status': 'refused', 'message': 'Only a parent or adult can answer that.'}
    mission = storage.get_mission(mission_id)
    if not mission:
        return {'status': 'error', 'message': 'No such mission.'}
    if outcome not in ('confirmed', 'failed', 'unsure'):
        return {'status': 'error', 'message': 'confirmed, failed or unsure'}
    nxt_q = None
    with storage.db_lock:
        ask = _pending_ask(mission_id, 'verify')
        status = (storage.get_mission(mission_id) or {}).get('status')
        # An ended mission keeps a verify a late report raised (final review I1): answerable, its status unchanged.
        ended = status in TERMINAL
        if not ask or not ask_id or ask['id'] != ask_id or not (status == 'waiting_user' or ended):
            return {'status': 'success', 'moved': True, 'message': 'That question has moved on; look at the card again.'}
        rj = ask.get('result_json') or {}
        att = next((a for a in attempts_for(mission_id) if a['step_id'] == rj.get('attempt_step_id')), None)
        if not att:
            return {'status': 'error', 'message': 'No attempt to resolve.'}
        if att.get('resolved_by'):
            # (An ended mission's status never moves, so a second tap lands here.)
            return {'status': 'success', 'already': True, 'message': 'That was already answered.'}
        if outcome == 'unsure':
            return {'status': 'success', 'message': 'Still waiting; tell me when you know.'}
        _write_attempt(att['step_id'], {**att, 'outcome': outcome, 'resolved_by': {'id': actor.get('id'), 'name': actor.get('name') or ''},
                                        'resolved_at': time.time(), 'detail': (detail or '').strip()[:300]})
        if not ended:
            # Another attempt still unknown (two unasked presses): ask about it
            # next, never run on past it. Inside the lock: a second tap on
            # this card finds a newer ask or a mission no longer waiting.
            rest = _unverified(mission_id)
            if rest:
                nxt_q = _add_verify_ask(mission_id, rest[-1])
            else:
                storage.update_mission(mission_id, {'status': 'running'})
    if outcome == 'confirmed':
        storage.add_mission_step(mission_id, {'kind': 'note', 'name': 'submitted',
                                              'result_json': {'verb': _submit_verb({'button': att.get('button')}, mission.get('goal')), 'facts': rj.get('facts') or {},
                                                              'confirmation': _confirmation_number(detail), 'text': (detail or '').strip(), 'by_hand': True,
                                                              'by': actor.get('name') or ''}})
    else:
        storage.add_mission_step(mission_id, {'kind': 'note', 'name': 'submit_failed', 'result_json': {'detail': (detail or '').strip()}})
    said = 'Noted; carrying on.' if outcome == 'confirmed' else 'Noted; it did not go through.'
    if ended:
        from services import situations as _sit
        _sit.touched('mission', mission_id)
        return {'status': 'success', 'message': 'Noted.' if outcome == 'confirmed' else 'Noted; it did not go through.'}
    if nxt_q:
        _close(mission_id, 'waiting_user')
        _dm_person(mission, nxt_q + VERIFY_TAIL)
        return {'status': 'success', 'message': said + ' One more press needs your answer.'}
    _close(mission_id, 'running')
    return {'status': 'success', 'message': said}


def start_browse(mission: dict, goal: str, site: str, start_url: str = None, released: dict = None, approved: dict = None) -> str:
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
    if not start_url:
        # The planner named no page: start where a past browse of this site
        # got furthest (its form, its scheduling page), not the front door.
        start_url = _site_page(site)
    args = {'goal': goal, 'site': site, 'start_url': start_url,
            **({'approved_ask_id': approved.get('ask_id'), 'approval_spent': False} if approved else {})}
    sid = storage.add_mission_step(mid, {'kind': 'browse', 'name': site, 'args_json': args, 'result_json': None})
    with storage.db_lock:
        if mid in _plan_subject and subject_of(storage.get_mission(mid)) != _plan_subject.get(mid):
            text = 'the subject changed before the browse started'
            storage.update_mission_step(sid, {'result_json': {'outcome': 'stale', 'text': text}})
            storage.add_mission_step(mid, {'kind': 'note', 'name': 'stale_plan', 'result_json': {'note': text}})
            storage.update_mission(mid, {'status': 'running'})
            return sid
        storage.set_app_state(f'mission_steer:{mid}', {})
        storage.update_mission(mid, {'status': 'browsing'})
    kw = dict(goal=goal, site=site, released=released if released is not None else _released_for(mission, site),
              consent={'captcha': bool(settings.get('missions_captcha_attempts'))}, start_url=start_url, out_dir=browse_dir(mid),
              approved=approved, on_attempt=_on_attempt_for(mid, sid), should_stop=_steer_check(mid))

    def work():
        try:
            report = _browse(**kw)
        except Exception as e:
            report = {'outcome': 'error', 'text': str(e)[:200], 'learned': {}, 'stopped_at': start_url or site, 'wanted_fields': [],
                      'turns': 0, 'tokens_in': 0, 'tokens_out': 0, 'seconds': 0, 'screenshots': [], 'filled': {},
                      'submit': None, 'attempt': None, 'changed': [], 'attempts_extra': []}
        finish_browse(mid, sid, report)

    if _browse_async:
        threading.Thread(target=work, daemon=True).start()
    else:
        work()
    return sid


def finish_browse(mission_id: str, step_id: str, report: dict) -> None:
    """The report becomes the step's result. Only the mission's LIVE browse
    (status browsing, newest browse step == this step) may move the mission;
    a late report is evidence on its own step. Attempts are resolved first,
    a parent's resolution is never overwritten, and an unresolved attempt
    forces the verify hand-off whatever the report says (spec §2). Otherwise
    the outcome maps to running (the planner reads it), a `submit` ask, a
    `release` ask, or a `handoff` ask."""
    from services import browse as _b
    mission = storage.get_mission(mission_id)
    if not mission:
        return
    step_row = next((s for s in storage.get_mission_steps(mission_id) if s['id'] == step_id), None)
    args = (step_row or {}).get('args_json') or {}
    site = args.get('site') or ''
    _remember_site_page(site, report)
    # Count the day's turns, whatever the outcome.
    day = datetime.date.today().isoformat()
    with storage.db_lock:
        counts = dict(storage.get_app_state(f'mission_calls:{day}') or {})
        counts['browse_turns'] = int(counts.get('browse_turns', 0)) + int(report.get('turns') or 0)
        storage.set_app_state(f'mission_calls:{day}', counts)
        # The thread may return after the mission moved on (dropped by a
        # parent, reclaimed by the tick, a newer browse started): the report
        # stays on its step as evidence, nothing else moves.
        newest = next((s for s in reversed(storage.get_mission_steps(mission_id)) if s.get('kind') == 'browse'), None)
        live = (storage.get_mission(mission_id) or {}).get('status') == 'browsing' and bool(newest) and newest['id'] == step_id
        # In the same lock: the tick's reclaim tests `result_json is None`.
        shots = [os.path.basename(p) for p in report.get('screenshots') or []]
        storage.update_mission_step(step_id, {'result_json': {**report, 'screenshots': shots}})
    _resolve_attempts(mission_id, step_id, report, live)
    if not live:
        storage.add_mission_step(mission_id, {'kind': 'note', 'name': 'browse',
                                              'result_json': {'note': 'the browse finished after the mission had moved on; its report is above'}})
        _late_verify(mission_id)
        return
    mission = storage.get_mission(mission_id)
    outcome = report.get('outcome')
    text = report.get('text') or ''
    # Every attempt on the MISSION still at unknown, this step's first: the
    # mission was browsing, so no verify ask is pending on any of them, and
    # one left unasked would bar every later press (on_attempt check 3).
    unknown = [a for a in attempts_for(mission_id) if a.get('outcome') == 'unknown']
    if unknown:
        mine = [a for a in unknown if a.get('browse_step_id') == step_id]
        _verify_ask(mission, (mine or unknown)[-1], payment=(bool(mine) and outcome == 'blocked' and 'payment' in text.lower()))
        return
    if outcome == 'needs_submit' and report.get('submit'):
        _submit_ask(mission, args, report)
        return
    if outcome in ('submitted', 'submit_unknown'):
        a = next((x for x in reversed(attempts_for(mission_id)) if x.get('browse_step_id') == step_id and x.get('outcome') == 'confirmed'), None)
        if not a or outcome == 'submit_unknown':
            # A press reported with no authorized attempt on record (on_attempt
            # mints every approved attempt) is a contract breach, never a
            # booking: the person checks, the mission waits.
            _unverified_handoff(mission, report)
            return
        approved_ask = (_ask_by_id(mission_id, a.get('ask_id')) or {}).get('result_json') or {}
        facts = dict(approved_ask.get('facts') or report.get('learned') or {})
        storage.add_mission_step(mission_id, {'kind': 'note', 'name': 'submitted',
                                              'result_json': {'verb': _submit_verb({'button': a.get('button')}, mission.get('goal')), 'facts': facts,
                                                              'confirmation': _confirmation_number(a.get('text') or text), 'text': a.get('text') or text,
                                                              'by_hand': False}})
        _close(mission_id, 'running')
        return
    if outcome == 'submit_rejected':
        storage.add_mission_step(mission_id, {'kind': 'note', 'name': 'submit_rejected', 'result_json': {'error': text}})
        _close(mission_id, 'running')
        return
    if outcome == 'needs_release':
        card = _b.contact_card()
        fields = [f for f in report.get('wanted_fields') or [] if f in card]
        missing = [f for f in report.get('wanted_fields') or [] if f not in card]
        values = {f: card[f] for f in fields}
        domain = _b._domain(f'https://{site}')
        # A field the card lacks is a QUESTION, never a guess and never a
        # hand-off (2026-10-11): the ask names it and where to fill it, and
        # Share keeps waiting until the card has it (release() re-reads).
        if values:
            q = f"Share with {domain}: " + ' · '.join(values.values()) + '?'
            if missing:
                q += f" It also needs your {', '.join(missing)}: fill them in the contact card (Missions settings), then tap Share."
        else:
            q = (f"{domain} needs your {', '.join(missing)} to go on. Fill them in the contact card "
                 f"(Missions settings), then tap Share.")
        storage.add_mission_step(mission_id, {'kind': 'ask', 'name': 'release',
                                              'result_json': {'question': q, 'site': domain, 'fields': fields, 'values': values,
                                                              'missing': missing,
                                                              'browse': {'goal': args.get('goal'), 'site': site, 'start_url': report.get('stopped_at')}}})
        _close(mission_id, 'waiting_user')
        _dm_person(mission, f"Argyle needs a yes: {q} (mission: {mission.get('goal')}). Approve here, on the Missions page or the thread card.")
        return
    if outcome == 'captcha_failed' or (outcome == 'blocked' and 'payment' in text.lower()):
        url = report.get('stopped_at') or ''
        filled = report.get('filled') or {}
        reason = _plain_reason(text)
        q = (f"I got as far as {url}. " + (f"Filled so far: {', '.join(f'{k}={v}' for k, v in filled.items())}. " if filled else '')
             + f"{reason} Finish it on your phone and tell me what you found.")
        storage.add_mission_step(mission_id, {'kind': 'ask', 'name': 'handoff',
                                              'result_json': {'question': q, 'url': url, 'filled': filled, 'reason': reason}})
        _close(mission_id, 'waiting_user')
        _dm_person(mission, q)
        return
    _close(mission_id, 'running')


def delete(mission_id: str) -> dict:
    """A person's delete, by hand only (no agent tool): the mission, its
    steps, its asks and its screenshot folder. The thread it came from stays."""
    import shutil
    if not storage.get_mission(mission_id):
        return {'status': 'not_found'}
    storage.delete_mission_rows(mission_id)
    storage.delete_asks_for('mission', mission_id)
    d = os.path.join(os.path.dirname(storage.DB_PATH), 'browse', mission_id)
    shutil.rmtree(d, ignore_errors=True)
    return {'status': 'ok'}


def release(mission_id: str, decision: str, actor: dict, ask_id: str = None, approval_context=None) -> dict:
    """The person's answer to a release ask: approve (record the site and
    fields on the mission and resume the pending browse with the values),
    decline (hand the page over), stop (block the mission). Idempotent: a
    release already acted on answers `already`; an ask id that is not the
    pending ask answers `moved` and changes nothing (no id: moved too)."""
    if not actor or (actor.get('role') or '') not in ('parent', 'adult'):
        return {'status': 'refused', 'message': "Only a parent or adult can release the family's details."}
    mission = storage.get_mission(mission_id)
    if not mission:
        return {'status': 'error', 'message': 'No such mission.'}
    steps = storage.get_mission_steps(mission_id)
    ask = next((s for s in reversed(steps) if s.get('kind') == 'ask'), None)
    if not ask or ask.get('name') != 'release' or mission.get('status') != 'waiting_user':
        return {'status': 'success', 'already': True, 'message': 'That release was already answered.'}
    if not ask_id or ask['id'] != ask_id:
        return {'status': 'success', 'moved': True, 'message': 'That question has moved on; look at the card again.'}
    rj = ask.get('result_json') or {}
    if decision == 'approve':
        from services import browse as _b
        card = _b.contact_card()
        wanted = list(rj.get('fields') or []) + [f for f in (rj.get('missing') or []) if f not in (rj.get('fields') or [])]
        still = [f for f in wanted if f not in card]
        if still:
            # Nothing leaves the house that the card does not hold: the ask stays.
            return {'status': 'success', 'already': False,
                    'message': f"The contact card still has no {', '.join(still)}. Fill it in Missions settings, then tap Share."}
        rel = {'site': rj.get('site'), 'fields': wanted, 'approved_by': actor.get('id'), 'at': time.time()}
        with storage.db_lock:
            row = storage.get_mission(mission_id)
            if row.get('status') != 'waiting_user':
                return {'status': 'success', 'already': True, 'message': 'Already answered.'}
            current = _pending_ask(mission_id, 'release')
            if not current or current['id'] != ask_id:
                return {'status': 'success', 'moved': True, 'message': 'That question has moved on.'}
            if approval_context is not None:
                from services import voice_approval
                card = _b.contact_card()
                if not voice_approval.valid(approval_context, current, actor, card):
                    return {'status': 'refused', 'message': 'The details or your verification changed. Ask for a new readback.'}
                # Use the validated record under the lock, never an earlier
                # read of this ask that might carry another site/field set.
                rj = current.get('result_json') or {}
                wanted = list(dict.fromkeys([*(rj.get('fields') or []), *(rj.get('missing') or [])]))
                rel.update(site=rj.get('site'), fields=wanted)
                rel['approval_context'] = approval_context.record()
                rel['approved_values'] = {field: card[field] for field in wanted}
            storage.update_mission(mission_id, {'releases': (row.get('releases') or []) + [rel], 'status': 'running'})
        storage.add_mission_step(mission_id, {'kind': 'note', 'name': 'release_approved', 'result_json': {'site': rel['site'], 'fields': rel['fields']}})
        pending = rj.get('browse') or {}
        # The card as it is NOW: a parent who fixed a stale value, or filled a
        # missing one, before tapping Share releases what the card holds now.
        values = {f: card[f] for f in rel['fields'] if f in card} or (rj.get('values') or {})
        start_browse(storage.get_mission(mission_id), pending.get('goal') or mission.get('goal'), pending.get('site') or rel['site'],
                     start_url=pending.get('start_url'), released=values)
        return {'status': 'success', 'message': f"Shared with {rel['site']}. Carrying on."}
    if decision == 'decline':
        url = ((rj.get('browse') or {}).get('start_url')) or ''
        q = (f"I got as far as {url}. The form wants {', '.join(rj.get('fields') or [])}, which you kept. "
             f"If a value was wrong, fix the contact card in Missions settings and start the mission again; "
             f"otherwise finish it on your phone and tell me what you found.")
        storage.add_mission_step(mission_id, {'kind': 'ask', 'name': 'handoff', 'result_json': {'question': q, 'url': url, 'filled': {}, 'reason': 'details not shared'}})
        _close(mission_id, 'waiting_user')
        _dm_person(mission, q)
        return {'status': 'success', 'message': 'Kept. Fix the contact card in Missions settings if a value was wrong; otherwise finish it on your phone and tell me what you found.'}
    if decision == 'stop':
        _close(mission_id, 'blocked', error='the family kept its details')
        return {'status': 'success', 'message': 'Stopped.'}
    return {'status': 'error', 'message': 'approve, decline or stop'}


def _plain_reason(text: str) -> str:
    """The runner's report as one short sentence for a person: the LEARNED:,
    NEED: and WALL: lines are the runner's, not the person's."""
    lines = [ln.strip() for ln in (text or '').split('\n')
             if ln.strip() and not re.match(r'^(LEARNED|NEED|WALL):', ln.strip(), re.I)]
    out = ' '.join(' '.join(lines).split())
    if len(out) > 320:
        cut = out[:320]
        out = cut[:cut.rfind('. ') + 1] if '. ' in cut[120:] else cut.rstrip() + '…'
    if out and out[-1] not in '.!?…':
        out += '.'
    return out


def _site_page(site: str):
    """Where a past browse of this site got furthest, or None."""
    from services import browse as _b
    mem = storage.get_app_state('browse_site_pages') or {}
    return (mem.get(_b._domain(f'https://{site}')) or {}).get('url') or None


def _remember_site_page(site: str, report: dict) -> None:
    """A browse that stopped ON the site at a form that wanted the card or at
    a human check reached the deep page worth starting from next time. A
    finish (anywhere on the site), a page elsewhere, a cap, an error or a
    refusal teaches nothing and never overwrites that page."""
    from services import browse as _b
    url = report.get('stopped_at') or ''
    if report.get('outcome') not in ('needs_release', 'captcha_failed') or not url.startswith('http'):
        return
    dom = _b._domain(f'https://{site}')
    if _b._domain(url) != dom:
        return
    with storage.db_lock:
        mem = dict(storage.get_app_state('browse_site_pages') or {})
        mem[dom] = {'url': url, 'at': time.time()}
        storage.set_app_state('browse_site_pages', mem)


SITE_GOAL = re.compile(r'(pric|cost|fee|quote|availab|schedul|appointment|book|slot|window|sign ?up|register|order)', re.I)


def _finish_too_early(mission: dict, res: dict):
    """The reason a finish is refused, or None. A goal that asks a company's
    site for prices, slots, quotes or a booking path is not finished until
    this mission has browsed a site; one refusal per mission, then the
    planner is free (the step cap bounds the rest)."""
    if not SITE_GOAL.search(mission.get('goal') or ''):
        return None
    steps = storage.get_mission_steps(mission['id'])
    # Real work was done: a browse, a proposal for a parent, or a question
    # to the person. Only a finish on top of nothing is refused.
    if any(st.get('kind') in ('browse', 'proposal', 'ask') for st in steps):
        return None
    if any(st.get('kind') == 'note' and st.get('name') == 'finish_refused' for st in steps):
        return None
    return ("Not finished: this goal asks a company's site for prices, availability or a way to book, and this "
            "mission has not browsed any site yet. The thread's earlier notes (a 'call them' next step, a past "
            "conclusion) are history to verify, not facts: browse the official site now, starting at the deepest "
            "scheduling or pricing page you know, or ask the person. Finish only after that.")


def _land_finish(mission: dict, res: dict) -> None:
    """A finish reaches the thread (a `mission` history entry and a
    pre-filled next step) and the person (a DM). A `submitted` note is said
    outright ("Booked: {facts}, confirmation {n}"); otherwise "Nothing is
    booked" whenever a browse touched a site. The `mission` entry is
    appended AFTER the advance so it is the newest real entry the card's
    lead reads (situations._reply_option)."""
    summary = (res.get('summary') or '').strip()
    nxt = (res.get('next_action') or '').strip() or "Read Argyle's summary"
    when = res.get('next_action_at')
    steps = storage.get_mission_steps(mission['id'])
    touched_site = any(s.get('kind') == 'browse' for s in steps)
    booked = next((s for s in reversed(steps) if s.get('kind') == 'note' and s.get('name') == 'submitted'), None)
    if booked:
        # The thing IS booked (a confirmed press, or a parent's "it went through").
        rj = booked.get('result_json') or {}
        facts = ', '.join(str(v) for v in (rj.get('facts') or {}).values() if str(v).strip())
        lead = 'Booked' if rj.get('verb') == 'book' else 'Submitted'
        tail = (f" {lead}" + (f": {facts}" if facts else '')
                + (f", confirmation {rj['confirmation']}" if rj.get('confirmation') else '')
                + (f" (confirmed by {rj['by']})" if rj.get('by_hand') and rj.get('by') else '') + '.')
    else:
        tail = ' Nothing is booked.' if touched_site else ''
    tid = mission.get('origin_ref') if mission.get('origin_kind') == 'thread' else None
    thread = storage.get_thread(tid) if tid else None
    if not thread:
        _dm_person(mission, f"{summary} Next: {nxt}.{tail}")
        return
    from services import situations as _sit, threads as _threads
    if thread.get('state') not in ('done', 'dropped'):
        _threads.advance(tid, nxt, next_action_at=when, who=None)
        entry_next, entry_when = nxt, _threads._clean_next_action_at(when)
        _dm_person(mission, f"{summary} Next: {nxt}.{tail}")
    else:
        # Closed by hand while the mission ran: the note lands, the thread
        # stays closed and is not advanced.
        entry_next, entry_when = None, None
        _dm_person(mission, f"{summary} (The thread \"{thread.get('title')}\" was closed, so I left it closed.){tail}")
    storage.append_thread_history(tid, {'kind': 'mission', 'text': summary + tail, 'next_action': entry_next,
                                        'next_action_at': entry_when, 'mission_id': mission['id'], 'who': 'argyle'})
    _sit.touched('thread', tid)


def step(mission: dict) -> dict:
    """Advance ONE step. Returns the fresh mission row. All state transitions
    live here so tick() stays a scheduler and tests drive this directly."""
    try:
        return _step_once(mission)
    finally:
        _plan_subject.pop(mission['id'], None)


def _step_once(mission: dict) -> dict:
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
    before = subject_of(mission)
    _plan_subject[mid] = before
    res = _llm(mission, _system_prompt(now, settings, mission), _user_prompt(mission),
               settings)
    if subject_of(storage.get_mission(mid)) != before:
        storage.add_mission_step(mid, {'kind': 'note', 'name': 'stale_plan',
            'result_json': {'note': 'the subject changed while planning; planning again'}})
        return _close(mid, 'running')
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
        args = res.get('args') or {}
        stored_args = args
        if name == 'find_in_chauffeur':
            from services import subjects
            out = agent_tools_v2.find_in_chauffeur(
                args.get('query') or '', args.get('kind') or '', args.get('facet') or '',
                acting_member=_finder(mission))
            candidates = out.get('candidates') or []
            kept = [c for c in candidates if subjects.visible(
                c['kind'], subjects.load(c['kind'], c['id']), agent_tools_v2._REGISTRY_READER)]
            withheld = len(candidates) - len(kept)
            if withheld:
                # The generated query can itself be the withheld title.
                stored_args = {k: v for k, v in args.items() if k != 'query'}
            if subject_of(mission)[0]:
                _last_lookups[mid] = out
            else:
                safe_candidates = [c if c in kept else {'kind': c['kind'], 'id': c['id'], 'withheld': True}
                                   for c in candidates]
                # A clear winner is returned alone; a tie has no context.
                _last_lookups[mid] = {
                    'status': out.get('status'), 'candidates': safe_candidates,
                    'context': subjects.context(safe_candidates[0]['kind'], safe_candidates[0]['id'],
                                               agent_tools_v2._REGISTRY_READER, facet=args.get('facet') or None)
                               if out.get('context') and safe_candidates and not safe_candidates[0].get('withheld') else None,
                }
            # The stored words name only what any adult may read: the tool's own
            # message can name the withheld record ("Found Disney World.").
            said = out.get('message') if not withheld else (
                f"{withheld} record(s) only some of the family may see; shown to the planner once, not kept."
                + (" Also: " + '; '.join(c['title'] for c in kept) if kept else ''))
            out = {'status': out.get('status'), 'message': said, 'candidates': kept, 'withheld': withheld}
        else:
            out = agent_tools_v2.execute_tool(name, args, actor=read_viewer(mission))
        storage.add_mission_step(mid, {'kind': 'tool', 'name': name,
                                       'args_json': stored_args,
                                       'result_json': out})
        return storage.get_mission(mid)

    if action == 'subject':
        from services import subjects
        kind = (res.get('kind') or '').strip()
        sid = str(res.get('id') or '').strip()
        row = subjects.load(kind, sid) if kind in subjects.KINDS else None
        if row is None or not subjects.visible(kind, row, _finder(mission)):
            storage.add_mission_step(mid, {'kind': 'note', 'name': 'refused',
                                           'result_json': {'note': 'no readable record to bind'}})
            return storage.get_mission(mid)
        with storage.db_lock:
            if mission.get('origin_kind') == 'thread' and mission.get('origin_ref'):
                thread = storage.get_thread(mission['origin_ref'])
                if not thread:
                    storage.add_mission_step(mid, {'kind': 'note', 'name': 'refused',
                                                   'result_json': {'note': 'no thread to bind'}})
                    return storage.get_mission(mid)
                if thread.get('subject_kind'):
                    storage.add_mission_step(mid, {'kind': 'note', 'name': 'refused',
                        'result_json': {'note': f"already about {thread['subject_kind']} {thread.get('subject_id')}; a person unlinks it"}})
                    return storage.get_mission(mid)
                storage.update_thread(thread['id'], {'subject_kind': kind, 'subject_id': sid,
                    'subject_rev': int(thread.get('subject_rev') or 0) + 1,
                    'subject_history': subjects.history_after_binding(thread, kind, sid)})
            else:
                storage.update_mission(mid, {'subject_kind': kind, 'subject_id': sid,
                    'subject_rev': int(mission.get('subject_rev') or 0) + 1,
                    'subject_history': subjects.history_after_binding(mission, kind, sid)})
            storage.add_mission_step(mid, {'kind': 'note', 'name': 'subject',
                'result_json': {'kind': kind, 'id': sid, 'title': subjects.title_of(kind, row)}})
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
            extra_allowed=proposable_tools(), extra={'origin_kind': 'mission', 'origin_id': mid})
        storage.add_mission_step(mid, {'kind': 'proposal', 'name': name,
                                       'args_json': res.get('args') or {},
                                       'result_json': {**made,
                                                       'why': res.get('why')}})
        from services import situations as _sit
        _sit.touched('mission', mid)
        return storage.get_mission(mid)

    if action == 'research':
        from services import web
        question = (res.get('question') or '').strip()
        # A mission is paid work: its research bills the paid key (the pro
        # pool's), out of reach of the free key's per-minute cap that the Mind,
        # the notes and the vision reads all share. No paid key: the free one.
        paid = model_pools.api_key_for_pool('pro', settings)
        out = web.research(question, api_key=paid or None)
        msg = str(out.get('message') or '') if isinstance(out, dict) else ''
        if out.get('status') == 'error' and '429' in msg and not any(w in msg.lower() for w in ('per day', 'perday', 'daily')):
            # A per-minute cap is a two-minute matter, not a failed step: park
            # the mission (the tick promotes waiting_retry) and ask again.
            storage.add_mission_step(mid, {'kind': 'note', 'name': 'research_retry',
                                           'result_json': {'note': f"rate limited while searching for '{question}'; trying again in 2 minutes"}})
            storage.update_mission(mid, {'status': 'waiting_retry', 'retry_at': time.time() + 120})
            return storage.get_mission(mid)
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
        from services import browse as _b
        start_url = (res.get('start_url') or '').strip() or None
        if start_url and _b._domain(start_url) != _b._domain(f'https://{site}'):
            start_url = None            # resume only where the site itself stopped
        start_browse(storage.get_mission(mid), goal, site, start_url=start_url)
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
        q = (res.get('question') or '').strip()
        storage.add_mission_step(mid, {'kind': 'ask', 'name': 'question', 'result_json': {'question': q}})
        row = _close(mid, 'waiting_user')
        # Coming back (browse missions §4): the question reaches the person
        # with the ways to answer.
        _dm_person(mission, f"{q} (mission: {mission.get('goal')}). Reply here, or on the thread card.")
        return row

    if action == 'finish':
        why = _finish_too_early(mission, res)
        if why:
            # Once: a goal about a site's prices, slots or scheduling is not
            # finished until this mission has browsed the site (2026-10-11: the
            # planner repeated the thread's old "call them" and finished in one step).
            storage.add_mission_step(mid, {'kind': 'note', 'name': 'finish_refused', 'result_json': {'note': why}})
            return storage.get_mission(mid)
        storage.add_mission_step(mid, {'kind': 'llm', 'name': 'finish',
                                       'result_json': res})
        row = _close(mid, 'done', summary=(res.get('summary') or '').strip())
        _land_finish(storage.get_mission(mid), res)
        return row

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
        # One lock for the decision and its writes: a worker's on_attempt (same
        # lock) either pressed before this (its attempt is pending here and is
        # verified) or finds the mission no longer browsing and presses nothing.
        question = None
        with storage.db_lock:
            cur = storage.get_mission(row['id']) or {}
            if cur.get('status') != 'browsing':
                continue
            steps = storage.get_mission_steps(row['id'])
            b = next((s for s in reversed(steps) if s.get('kind') == 'browse'), None)
            if not (b and b.get('result_json') is None and (b.get('ts') or 0) < ts - BROWSE_LOST_S):
                continue
            storage.add_mission_step(row['id'], {'kind': 'note', 'name': 'browse',
                                                 'result_json': {'note': f'the browse was lost (no result after {BROWSE_LOST_S // 60} minutes)'}})
            # A dead worker that had pressed: the press may have happened, so
            # the parent is asked; the mission never just runs on (spec §2).
            pending = [a for a in attempts_for(row['id']) if a.get('browse_step_id') == b['id'] and a.get('outcome') is None]
            if pending:
                for a in pending:
                    _write_attempt(a['step_id'], {**a, 'outcome': 'unknown'})
                question = _add_verify_ask(row['id'], {**pending[-1], 'outcome': 'unknown'})
                storage.update_mission(row['id'], {'status': 'waiting_user'})
            else:
                storage.update_mission(row['id'], {'status': 'running'})
        if question:
            _close(row['id'], 'waiting_user')
            _dm_person(cur, question + VERIFY_TAIL)

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
