"""The Mind: phase-C executive loop (spec: docs/superpowers/specs/
2026-08-27-mind-executive-loop-design.md).

Boundaries are structural, not filtered: this module never imports or calls
any DM accessor (family channel only) and never touches occasion-secrecy
records. Keep it that way — tests assert on this file's source."""
import datetime
import hashlib
import json
import logging
import re
import time
from typing import List, Optional

from services import storage

logger = logging.getLogger(__name__)

WAKE_START_DEFAULT = '06:00'
WAKE_END_DEFAULT = '22:00'
RETENTION_DAYS = 14          # noticings; retired insights get 120d at the prune call
MAX_INSIGHTS_DEFAULT = 7
CAPS_DEFAULT = {'think': 20, 'sentinel': 400, 'promote': 50, 'handle': 30}
THINK_ATTEMPT_FLOOR_S = 300  # a due-but-erroring/unchanged think never
                             # re-attempts faster than this (promote bypasses)


def _mins(val, dflt):
    try:
        h, m = [int(x) for x in str(val or dflt).split(':')[:2]]
    except Exception:
        h, m = [int(x) for x in dflt.split(':')]
    return h * 60 + m


def in_wake_window(now: datetime.datetime, settings: dict) -> bool:
    start = _mins(settings.get('mind_wake_start'), WAKE_START_DEFAULT)
    end = _mins(settings.get('mind_wake_end'), WAKE_END_DEFAULT)
    cur = now.hour * 60 + now.minute
    if start == end:
        return True
    if start < end:
        return start <= cur < end
    return cur >= start or cur < end


def _bump_call(kind: str, cap: int) -> bool:
    """Day-keyed counter; True = allowed (and counted), False = capped."""
    day = datetime.date.today().isoformat()
    key = f'mind_calls:{day}'
    counts = dict(storage.get_app_state(key) or {})
    if int(counts.get(kind, 0)) >= cap:
        return False
    counts[kind] = int(counts.get(kind, 0)) + 1
    storage.set_app_state(key, counts)
    return True


def _fmt_ts(ts) -> str:
    try:
        return datetime.datetime.fromtimestamp(float(ts)).strftime('%a %H:%M')
    except Exception:
        return ''


def _driver_name(driver_id) -> str:
    """Same resolution family_digest.py uses: a member's driver_id first,
    then the raw drivers table, else the id itself."""
    if not driver_id:
        return 'unassigned'
    m = storage.get_member_by_driver_id(driver_id)
    if m:
        return m.get('name') or str(driver_id)
    for d in storage.get_all_drivers():
        if d.get('id') == driver_id:
            return d.get('name') or str(driver_id)
    return str(driver_id)


def _event_dt(raw):
    try:
        return datetime.datetime.fromisoformat(str(raw).replace('Z', '+00:00')).replace(tzinfo=None)
    except Exception:
        return None


def snapshot(now: datetime.datetime = None) -> str:
    """One compact text block of family state. Sections are independent:
    a provider that raises contributes nothing and never sinks the rest."""
    now = now or datetime.datetime.now()
    parts = [f"SNAPSHOT {now.strftime('%A %Y-%m-%d %H:%M')}"]

    def section(title, fn):
        try:
            body = fn()
        except Exception as e:
            logger.warning(f"[mind] snapshot section {title} failed: {e}")
            return
        if body:
            parts.append(f"## {title}\n{body}")

    def _calendar():
        sched = storage.get_cached_schedule() or {}
        events = sched.get('events') or []
        assignments = dict(sched.get('assignments') or {})
        # Ghost assignments are outside hands covering a ride — merged the
        # way family_digest.py:64 does, so a covered event never reads as
        # unassigned here.
        assignments.update(sched.get('ghost_assignments') or {})
        horizon = (now + datetime.timedelta(days=7)).date()
        # calendar_ids -> member name, so an event's attendees read as people
        # rather than opaque calendar ids (members own calendar_ids now).
        cal_owner = {}
        for m in storage.get_all_members():
            for cid in (m.get('calendar_ids') or []):
                cal_owner[str(cid)] = m.get('name') or str(cid)
        lines = []
        for e in events:
            dt = _event_dt(e.get('start'))
            if dt is None or not (now.date() <= dt.date() <= horizon):
                continue
            attendees = [cal_owner.get(str(c), str(c)) for c in (e.get('calendar_ids') or [])]
            d_id = assignments.get(e.get('id'))
            if not d_id:
                driver = 'unassigned'
            elif str(d_id).startswith('ghost_'):
                driver = 'covered (outside hand)'
            else:
                driver = _driver_name(d_id)
            lines.append(f"- {dt.strftime('%Y-%m-%d %H:%M')} "
                         f"{e.get('title') or '?'} [{', '.join(attendees)}] "
                         f"driver: {driver}")
        return '\n'.join(lines[:120])

    def _findings():
        from services import findings as _f
        return '\n'.join(f"- ({r.get('severity')}) {r.get('line')}"
                         for r in _f.open_findings()[:30])

    def _family_chat():
        fam = storage.get_family_channel()
        if not fam:
            return ''
        since = float(storage.get_app_state('mind_chat_snapshot_ts') or 0) \
            or (time.time() - 86400)
        msgs = storage.get_channel_messages(fam['id'], after_ts=since, limit=80)
        # Real ChatMessage rows carry body/sender_member_id (models/schemas.py
        # ChatMessage) — never text/member_id.
        return '\n'.join(f"- [{_fmt_ts(m.get('ts'))}] {m.get('sender_member_id')}: "
                         f"{m.get('body') or ''}" for m in msgs
                         if (m.get('body') or '').strip())

    def _shopping():
        from services import shopping as _shop
        rows = _shop.lists_needing_a_trip(min_items=1) or []
        lines = []
        for r in rows:
            lst = r.get('list') or {}
            reason = 'a deadline item' if r.get('because') == 'deadline' else \
                f"{r.get('open_count', '?')} items waiting"
            lines.append(f"- list {lst.get('name') or lst.get('id')}: {reason}")
        return '\n'.join(lines)

    def _cars():
        from services import cars as _cars
        lines = []
        for car in _cars_list():
            lv = _cars.car_levels(car) or {}
            lines.append(f"- {car.get('name')}: {lv}")
        return '\n'.join(lines)

    def _fmt_day(ts):
        try:
            return datetime.datetime.fromtimestamp(float(ts)).strftime('%a %m-%d')
        except Exception:
            return '?'

    def _noticings():
        rows = storage.get_mind_noticings(consumed=False)
        return '\n'.join(f"- [{_fmt_day(r.get('ts'))}] [{r.get('source')}] "
                         f"{r.get('line')}" for r in rows[:40])

    def _own_insights():
        rows = storage.get_mind_insights()
        lines = []
        for r in rows[-30:]:
            tag = r['state'] if r['state'] == 'active' else \
                f"{r['state']}/{r.get('outcome')}"
            lines.append(f"- [{tag}] [{_fmt_day(r.get('created_ts'))}] "
                         f"({r.get('category')}) {r.get('line')}")
        return '\n'.join(lines)

    def _vitals():
        from services import vitals as _v
        return _v.snapshot_section(now)

    def _threads():
        from services import threads as _th
        rows = _th.stalled(today=now.date()) or []
        # Open-but-not-stalled threads still matter (a stalled one is the
        # loudest signal, not the only one worth showing).
        stalled_ids = {r['id'] for r in rows}
        rows = rows + [t for t in storage.get_threads(include_closed=False)
                       if t['id'] not in stalled_ids]
        lines = []
        for t in rows[:40]:
            owner = storage.get_member(t.get('owner_member_id') or '') or {}
            reason = t.get('stall_reason')
            tag = f" [{reason}]" if reason else ''
            next_action = t.get('next_action') or 'no next action set'
            lines.append(f"- {t.get('title') or '?'} (owner: "
                         f"{owner.get('name') or 'unassigned'}) — {next_action}"
                         f"{tag}")
        return '\n'.join(lines)

    section('FAMILY VITALS (against this family\'s own baseline — never '
            'another family, never another person)', _vitals)
    section('CALENDAR NEXT 7 DAYS', _calendar)
    section('OPEN FINDINGS (already watched — do not repeat these)', _findings)
    section('FAMILY CHANNEL (spoken in the living room)', _family_chat)
    section('SHOPPING LISTS', _shopping)
    section('CARS', _cars)
    section('OPEN THREADS (open loops with people outside the family)', _threads)
    section('FRESH NOTICINGS', _noticings)
    section('YOUR OWN INSIGHTS AND HOW THE FAMILY REACTED', _own_insights)
    return '\n\n'.join(parts)


def _cars_list() -> list:
    """The family's cars, same filter cars.run_sweep uses (cars.py:350-351)."""
    from services import cars as _cars
    return [c for c in storage.get_all_cars()
            if not c.get('is_disabled') and _cars.has_telemetry(c)]


_TS_NOISE = re.compile(r'\b\d{1,2}:\d{2}\b')

# Only SLOW state decides "has anything changed". The Mind's own sections
# (noticings, prior insights) change on every think, and chat is consumed as
# it is read — hashing those would make the skip never fire. Chat still
# triggers thinks, but through noticings, which deep_think checks separately.
_HASH_SECTIONS = ('CALENDAR NEXT 7 DAYS', 'OPEN FINDINGS', 'SHOPPING LISTS',
                  'CARS', 'FAMILY VITALS', 'OPEN THREADS')


def snapshot_hash(text: str) -> str:
    """Hash of the slow-state sections only, clock noise stripped."""
    keep = []
    for block in text.split('\n\n'):
        title = block.splitlines()[0].lstrip('# ').strip() if block else ''
        if any(title.startswith(s) for s in _HASH_SECTIONS):
            keep.append(block)
    return hashlib.sha256(_TS_NOISE.sub('', '\n\n'.join(keep))
                          .encode('utf-8')).hexdigest()


def visible_insights(viewer: Optional[dict]) -> List[dict]:
    """Server-side sensitivity gate. No identity (wall panel) or non-parent
    identity gets a payload that never contained sensitive rows."""
    rows = storage.get_mind_insights(state='active')
    # 'parent' is the only role that sees sensitive rows — the codebase has
    # no 'admin' role.
    if viewer and viewer.get('role') in ('parent',):
        return rows
    return [r for r in rows if r.get('sensitivity') != 'sensitive']


# --- Handle it: on-demand proposal for one insight ------------------------

def _agent_request(prompt: str, actor: dict) -> dict:
    """Indirection so tests stub one attribute. The live path is the same
    agent stack chat uses — its tools build and validate the proposal payload
    (the suggestion funnel in chat_actions.py rides the identical rail)."""
    from services.agent_router import process_agent_request
    return process_agent_request(prompt, source='family', acting_member=actor)


def propose_fix(insight_id: str, actor: dict = None,
                now: datetime.datetime = None) -> dict:
    """Ask the agent for ONE concrete move on an insight. Attaches
    {proposal_id, summary} to the insight when the agent produces a card;
    an honest no-move otherwise. Never executes anything — the approve tap
    stays a separate, human act."""
    now = now or datetime.datetime.now()
    rows = [r for r in storage.get_mind_insights() if r['id'] == insight_id]
    if not rows or rows[0].get('state') != 'active':
        return {'status': 'not_found'}
    row = rows[0]
    existing = row.get('proposal_json') or {}
    if existing.get('proposal_id'):
        return {'status': 'proposed', 'proposal_id': existing['proposal_id'],
                'summary': existing.get('summary') or ''}
    settings = storage.get_settings() or {}
    if not settings.get('llm_gemini_api_key', ''):
        return {'status': 'no_key'}
    cap = int(settings.get('mind_cap_handle', CAPS_DEFAULT['handle']))
    if not _bump_call('handle', cap):
        return {'status': 'capped'}
    prompt = (f"Today is {now.strftime('%A %Y-%m-%d')}. You noticed this about "
              f"the family: \"{row.get('line')}\""
              + (f" ({row.get('detail')})" if row.get('detail') else '')
              + ". Propose exactly ONE concrete action that would resolve it, "
                "using your action tools. If no schedule or household action "
                "genuinely helps, say so plainly instead of forcing one.")
    try:
        res = _agent_request(prompt, actor) or {}
    except Exception as e:
        logger.warning(f"[mind] propose_fix agent run failed: {e}")
        return {'status': 'error'}
    card = res.get('card') or {}
    if card.get('proposal_id'):
        pj = {'proposal_id': card['proposal_id'],
              'summary': card.get('title') or res.get('message') or 'proposed action'}
        storage.update_mind_insight(insight_id, {'proposal_json': pj})
        return {'status': 'proposed', **pj}
    return {'status': 'no_move', 'note': res.get('message') or ''}


GRADUATION_MIN_RESOLVED = 10
GRADUATION_MIN_ACT_RATE = 0.60


def category_counters() -> dict:
    """Per-category counts for the admin lane. Task 11 fills this in."""
    out = {}
    for r in storage.get_mind_insights(state='retired'):
        cat = r.get('category') or 'other'
        bucket = out.setdefault(cat, {'acted': 0, 'dismissed': 0, 'expired': 0})
        if r.get('outcome') in bucket:
            bucket[r['outcome']] += 1
    return out


def graduation_candidates() -> list:
    """Categories worth promoting out of the lane. Task 11 fills this in."""
    settings = storage.get_settings() or {}
    already = set(settings.get('mind_direct_categories') or [])
    out = []
    for cat, c in category_counters().items():
        if cat in already:
            continue
        resolved = c['acted'] + c['dismissed'] + c['expired']
        answered = c['acted'] + c['dismissed']
        if resolved >= GRADUATION_MIN_RESOLVED and answered \
                and c['acted'] / answered >= GRADUATION_MIN_ACT_RATE:
            out.append({'category': cat, 'resolved': resolved,
                        'act_rate': round(c['acted'] / answered, 2)})
    return sorted(out, key=lambda x: -x['act_rate'])


# --- Sentinel: coalesced deltas -> one gemma call -> noticings -------------

SENTINEL_SYSTEM = (
    "You are Argyle, the quiet ear of a family's home assistant. You are shown "
    "only what CHANGED since your last look: new family-channel messages "
    "(spoken openly, as in the living room), calendar changes, new findings, "
    "shopping changes. Note anything the house should remember or act on: a "
    "need said out loud, a new conflict, something unusual. Return STRICT JSON: "
    '{"noticings": [{"line": "<one short sentence>", '
    '"source": "chat|calendar|findings|supply", "urgency": "low|high"}]} '
    "Return {\"noticings\": []} when nothing matters. Never invent facts."
)


def _pool_call(tier, api_key, system, prompt, **kw):
    """Indirection so tests stub one attribute."""
    from services import model_pools
    return model_pools.call_pool_json(tier, api_key, system, prompt, **kw)


def _gather_deltas(now: datetime.datetime) -> list:
    deltas = []

    # Chat: new family-channel messages past the watermark.
    fam = storage.get_family_channel()
    if fam:
        wm = float(storage.get_app_state('mind_chat_watermark') or 0)
        msgs = storage.get_channel_messages(fam['id'], after_ts=wm, limit=40)
        if msgs:
            storage.set_app_state('mind_chat_watermark', max(m['ts'] for m in msgs))
            for m in msgs:
                # body/sender_member_id: the real ChatMessage field names.
                if (m.get('body') or '').strip():
                    deltas.append(f"[chat] {m.get('sender_member_id')}: {m['body']}")

    # Calendar: id -> {title, fp} map diffed against the stored one. Same real
    # cached-schedule shape snapshot()'s _calendar() reads: events carry
    # id/title/start/end, and the driver for an event lives in the separate
    # assignments map keyed by event id (not on the event itself). Ghost
    # assignments merge in (family_digest.py:64) so an outside hand covering
    # a ride fingerprints as covered, not unassigned. Titles ride along so
    # the delta lines the sentinel reads name the event, not an opaque id —
    # and a removed event still names itself from the stored value.
    sched = storage.get_cached_schedule() or {}
    assignments = dict(sched.get('assignments') or {})
    assignments.update(sched.get('ghost_assignments') or {})
    # Only FUTURE events are diffed. The cache is a rolling forward window,
    # so a past event leaving it is time passing, not a removal — without
    # this filter every morning's expiry reads as "removed from the
    # calendar" and the Mind invents cancellations out of history.
    today_iso = now.date().isoformat()
    cur = {str(e.get('id')): {
               'title': e.get('title') or '?',
               'fp': f"{e.get('start')}|{e.get('end')}|"
                     f"{assignments.get(e.get('id'))}"}
           for e in (sched.get('events') or [])
           if str(e.get('start') or '')[:10] >= today_iso}
    prev = dict(storage.get_app_state('mind_event_state') or {})

    def _is_future(v):
        fp = v.get('fp') if isinstance(v, dict) else str(v or '')
        return (fp.split('|', 1)[0] or '')[:10] >= today_iso

    # The stored side gets the same cut with TODAY's date, so an event whose
    # date arrived and passed since the last look drops from both sides
    # silently instead of surfacing as "removed".
    prev = {k: v for k, v in prev.items() if _is_future(v)}

    def _cal_title(state, k):
        v = state.get(k)
        return v.get('title') if isinstance(v, dict) else str(k)

    def _cal_when(state, k):
        v = state.get(k)
        fp = v.get('fp') if isinstance(v, dict) else str(v or '')
        return (fp.split('|', 1)[0] or '?')[:16]

    if cur != prev:
        storage.set_app_state('mind_event_state', cur)
        added = [k for k in cur if k not in prev]
        gone = [k for k in prev if k not in cur]
        changed = [k for k in cur if k in prev and cur[k] != prev[k]]
        if prev:  # first run is baseline, not a delta storm
            for k in added[:10]:
                deltas.append(f"[calendar] new: {_cal_title(cur, k)} "
                              f"({_cal_when(cur, k)})")
            for k in gone[:10]:
                deltas.append(f"[calendar] removed: {_cal_title(prev, k)} "
                              f"({_cal_when(prev, k)})")
            for k in changed[:10]:
                deltas.append(f"[calendar] changed: {_cal_title(cur, k)} -> "
                              f"{cur[k]['fp']}")

    # Findings: new open keys.
    from services import findings as _f
    keys = sorted(r.get('key') or r.get('id') for r in _f.open_findings())
    prev_keys = list(storage.get_app_state('mind_finding_keys') or [])
    if keys != prev_keys:
        storage.set_app_state('mind_finding_keys', keys)
        for r in _f.open_findings():
            if (r.get('key') or r.get('id')) not in prev_keys and prev_keys:
                deltas.append(f"[findings] {r.get('line')}")

    # Shopping: coarse hash of list sizes.
    try:
        from services import shopping as _shop
        h = hashlib.sha256(json.dumps(
            [(l.get('id'), l.get('item_count'))
             for l in (_shop.lists_needing_a_trip(min_items=1) or [])],
            sort_keys=True).encode()).hexdigest()
        if h != storage.get_app_state('mind_shop_hash'):
            if storage.get_app_state('mind_shop_hash'):
                deltas.append("[supply] shopping lists changed")
            storage.set_app_state('mind_shop_hash', h)
    except Exception as e:
        logger.warning(f"[mind] shopping delta failed: {e}")

    return deltas


def sentinel_sweep(now: datetime.datetime = None) -> dict:
    now = now or datetime.datetime.now()
    settings = storage.get_settings() or {}
    api_key = settings.get('llm_gemini_api_key', '')
    deltas = _gather_deltas(now)      # watermarks advance even without a key
    if not deltas:
        return {'status': 'no_deltas'}
    if not api_key:
        return {'status': 'no_key'}
    cap = int(settings.get('mind_cap_sentinel', CAPS_DEFAULT['sentinel']))
    if not _bump_call('sentinel', cap):
        return {'status': 'capped'}
    res = _pool_call('background', api_key, SENTINEL_SYSTEM,
                     f"Today is {now.strftime('%A %Y-%m-%d')}.\n"
                     "CHANGES SINCE LAST LOOK:\n" + '\n'.join(deltas[:60]),
                     timeout_s=60, gemma_timeout_s=180)
    if not isinstance(res, dict) or res.get('error'):
        logger.warning(f"[mind] sentinel LLM failed: {res}")
        return {'status': 'error'}
    stored = 0
    for n in (res.get('noticings') or [])[:10]:
        line = (n.get('line') or '').strip()
        if line:
            storage.add_mind_noticing({'line': line,
                                       'source': n.get('source') or 'chat',
                                       'urgency': n.get('urgency') or 'low',
                                       'refs': []})
            stored += 1
    return {'status': 'swept', 'noticings': stored}


# --- Promoter: high-urgency noticings -> one lite call -> early think ------

PROMOTER_SYSTEM = (
    "A family home assistant noticed something and wonders whether to think "
    "hard about it NOW or wait for its next scheduled reflection (within the "
    "hour). Promote only genuinely time-relevant items. Return STRICT JSON: "
    '{"think_now": true|false}'
)


THINK_SYSTEM = (
    "You are Argyle, a family home's mind. Coded watchers already cover the "
    "mechanical things (the OPEN FINDINGS section) — never restate those. Your "
    "job is what only whole-picture judgment can see: cross-domain patterns, "
    "load building on one person, needs said out loud in the family channel, "
    "collisions nobody planned for, small kindnesses worth suggesting.\n\n"
    "VITALS: the FAMILY VITALS section is the family's pulse — each sign "
    "against this family's own past, never another family and never another "
    "person. Trends there are the richest thing you are shown: a level is a "
    "fact, a trend is a finding. Speak about the WEEK, never about who is "
    "failing it, and never render a person's load as a score.\n\n"
    "DATES: the snapshot header states today's date; every noticing and "
    "previous insight is stamped with its own date. The calendar shows the "
    "NEXT 7 DAYS only — an event before today is history, not missing and "
    "not cancelled; never claim something is absent this week from a memory "
    "older than the calendar you can see.\n\n"
    "THREADS: the OPEN THREADS section lists the household's open loops with "
    "people outside the family — a vendor, a school, a contractor, waiting "
    "on a reply or a next step. A thread marked [overdue] or [quiet] has "
    "stalled and is worth noticing. You may also propose starting a thread "
    "when you spot real outside-facing work with no home yet — but never "
    "invent one that isn't plainly there.\n\n"
    "You are shown your own previous insights and how the family reacted. A "
    "dismissed insight means they heard you and said no — do not repeat it. "
    "Curate: return the FULL DESIRED set of current insights (max {max_n}); "
    "any active slug you omit is retired. Keep a slug stable while the "
    "observation is the same one.\n\n"
    "Mark sensitivity 'sensitive' for anything about a child's emotional "
    "state, stress, health, or another member's private strain — those render "
    "to parents only.\n\n"
    "Return STRICT JSON: {{\"insights\": [{{\"slug\": \"kebab-case-stable\", "
    "\"line\": \"one plain sentence\", \"detail\": \"1-2 optional sentences\", "
    "\"domain\": \"kids|meals|cars|schedule|supply|other\", "
    "\"sensitivity\": \"normal|sensitive\", \"category\": "
    "\"reusable-pattern-slug\", \"confidence\": 0.0}}]}}. "
    "An empty list is a fine answer. Never invent facts."
)


def deep_think(now: datetime.datetime = None, force: bool = False) -> dict:
    now = now or datetime.datetime.now()
    settings = storage.get_settings() or {}
    if not settings.get('mind_enabled', False):
        return {'status': 'disabled'}
    api_key = settings.get('llm_gemini_api_key', '')
    if not api_key:
        return {'status': 'no_key'}
    if not force and not in_wake_window(now, settings):
        return {'status': 'asleep'}

    # The chat cutoff is the moment the snapshot is TAKEN, not the moment the
    # think finishes — a 90-180s LLM call later, time.time() would silently
    # skip every message that arrived mid-think.
    chat_cutoff = time.time()
    text = snapshot(now)
    h = snapshot_hash(text)
    fresh_noticings = storage.get_mind_noticings(consumed=False)
    if not force and h == storage.get_app_state('mind_last_snapshot_hash') \
            and not fresh_noticings:
        return {'status': 'unchanged'}
    cap = int(settings.get('mind_cap_think', CAPS_DEFAULT['think']))
    if not _bump_call('think', cap):
        return {'status': 'capped'}

    max_n = int(settings.get('mind_max_insights', MAX_INSIGHTS_DEFAULT))
    res = _pool_call('heavy', api_key, THINK_SYSTEM.format(max_n=max_n), text,
                     timeout_s=90, gemma_timeout_s=180)
    if not isinstance(res, dict) or res.get('error'):
        logger.warning(f"[mind] deep think failed: {res}")
        return {'status': 'error'}

    desired = [i for i in (res.get('insights') or [])
               if (i.get('slug') or '').strip() and (i.get('line') or '').strip()]
    desired = desired[:max_n]
    desired_slugs = {i['slug'] for i in desired}

    active = storage.get_mind_insights(state='active')
    for row in active:
        if row['slug'] not in desired_slugs:
            storage.update_mind_insight(row['id'], {
                'state': 'retired', 'outcome': 'expired',
                'resolved_ts': time.time()})
    # Only a DISMISSED slug stays suppressed — the family heard it and said
    # no. Acted and expired slugs may return: the situation being back is
    # exactly what the lane should say.
    dismissed_slugs = {r['slug']
                       for r in storage.get_mind_insights(state='retired')
                       if r.get('outcome') == 'dismissed'}
    for item in desired:
        existing = storage.get_mind_insight_by_slug(item['slug'])
        fields = {'line': item['line'], 'detail': item.get('detail') or '',
                  'domain': item.get('domain') or '',
                  'sensitivity': item.get('sensitivity') or 'normal',
                  'category': item.get('category') or 'other',
                  'confidence': item.get('confidence')}
        if existing and existing['state'] == 'active':
            storage.update_mind_insight(existing['id'], fields)
        elif item['slug'] in dismissed_slugs:
            pass  # a dismissed slug is never resurrected
        elif existing:
            # acted/expired slug returning: revive the SAME row (slugs stay
            # unique) as a fresh observation.
            storage.update_mind_insight(existing['id'], {
                **fields, 'state': 'active', 'outcome': None,
                'resolved_ts': None, 'created_ts': time.time()})
        else:
            storage.add_mind_insight({'slug': item['slug'], **fields})

    storage.consume_mind_noticings([r['id'] for r in fresh_noticings])
    storage.set_app_state('mind_last_snapshot_hash', h)
    storage.set_app_state('mind_last_think_ts', time.time())
    storage.set_app_state('mind_chat_snapshot_ts', chat_cutoff)
    storage.set_app_state('mind_think_requested', False)
    storage.prune_mind(time.time() - 120 * 86400,
                       time.time() - RETENTION_DAYS * 86400)
    return {'status': 'thought',
            'active': len(storage.get_mind_insights(state='active'))}


def tick(now: datetime.datetime = None) -> dict:
    """The one entry the push loop calls. All gating lives here so main.py
    stays a two-line block and tests drive this directly."""
    now = now or datetime.datetime.now()
    settings = storage.get_settings() or {}
    if not settings.get('mind_enabled', False):
        return {'status': 'disabled'}
    out = {'status': 'ticked'}
    ts = now.timestamp()

    cadence = int(settings.get('mind_sentinel_cadence_s', 120))
    last = float(storage.get_app_state('mind_sentinel_last') or 0)
    if ts - last >= cadence:
        storage.set_app_state('mind_sentinel_last', ts)   # marker FIRST
        out['sentinel'] = sentinel_sweep(now)
        out['promote'] = maybe_promote()

    think_every = int(settings.get('mind_think_cadence_min', 60)) * 60
    last_think = float(storage.get_app_state('mind_last_think_ts') or 0)
    requested = bool(storage.get_app_state('mind_think_requested'))
    if requested or ts - last_think >= think_every:
        # Attempt floor: a think that errors (or keeps coming back
        # 'unchanged') leaves mind_last_think_ts alone, so without this the
        # 30s push loop would rebuild the snapshot — and on error re-fire a
        # heavy LLM call — every single tick. A promoted request may go
        # sooner; everything else waits the floor out.
        last_attempt = float(storage.get_app_state('mind_think_attempt_ts') or 0)
        if requested or ts - last_attempt >= THINK_ATTEMPT_FLOOR_S:
            storage.set_app_state('mind_think_attempt_ts', ts)  # marker FIRST
            out['think'] = deep_think(now)
    return out


def maybe_promote() -> dict:
    urgent = [r for r in storage.get_mind_noticings(consumed=False)
              if r.get('urgency') == 'high' and not r.get('promoted_checked')]
    if not urgent:
        return {'status': 'nothing'}
    settings = storage.get_settings() or {}
    api_key = settings.get('llm_gemini_api_key', '')
    if not api_key:
        return {'status': 'no_key'}
    cap = int(settings.get('mind_cap_promote', CAPS_DEFAULT['promote']))
    if not _bump_call('promote', cap):
        return {'status': 'capped'}
    storage.mark_mind_noticings_checked([r['id'] for r in urgent])
    res = _pool_call('interactive', api_key, PROMOTER_SYSTEM,
                     '\n'.join(f"- {r['line']}" for r in urgent[:10]), timeout_s=30)
    if not isinstance(res, dict) or res.get('error'):
        return {'status': 'error'}
    if res.get('think_now'):
        storage.set_app_state('mind_think_requested', True)
        return {'status': 'promoted'}
    return {'status': 'held'}
