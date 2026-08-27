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
CAPS_DEFAULT = {'think': 20, 'sentinel': 400, 'promote': 50}


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
            driver = _driver_name(d_id) if d_id and not str(d_id).startswith('ghost_') else 'unassigned'
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
        return '\n'.join(f"- [{_fmt_ts(m.get('ts'))}] {m.get('member_id')}: "
                         f"{m.get('text') or ''}" for m in msgs
                         if (m.get('text') or '').strip())

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

    def _noticings():
        rows = storage.get_mind_noticings(consumed=False)
        return '\n'.join(f"- [{r.get('source')}] {r.get('line')}" for r in rows[:40])

    def _own_insights():
        rows = storage.get_mind_insights()
        lines = []
        for r in rows[-30:]:
            tag = r['state'] if r['state'] == 'active' else \
                f"{r['state']}/{r.get('outcome')}"
            lines.append(f"- [{tag}] ({r.get('category')}) {r.get('line')}")
        return '\n'.join(lines)

    section('CALENDAR NEXT 7 DAYS', _calendar)
    section('OPEN FINDINGS (already watched — do not repeat these)', _findings)
    section('FAMILY CHANNEL (spoken in the living room)', _family_chat)
    section('SHOPPING LISTS', _shopping)
    section('CARS', _cars)
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
                  'CARS')


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
    if viewer and viewer.get('role') in ('parent', 'admin'):
        return rows
    return [r for r in rows if r.get('sensitivity') != 'sensitive']


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
                if (m.get('text') or '').strip():
                    deltas.append(f"[chat] {m.get('member_id')}: {m['text']}")

    # Calendar: id->fingerprint map diffed against the stored one. Same real
    # cached-schedule shape snapshot()'s _calendar() reads: events carry
    # id/title/start/end, and the driver for an event lives in the separate
    # assignments map keyed by event id (not on the event itself).
    sched = storage.get_cached_schedule() or {}
    assignments = dict(sched.get('assignments') or {})
    cur = {str(e.get('id')): f"{e.get('start')}|{e.get('end')}|"
           f"{assignments.get(e.get('id'))}"
           for e in (sched.get('events') or [])}
    prev = dict(storage.get_app_state('mind_event_state') or {})
    if cur != prev:
        storage.set_app_state('mind_event_state', cur)
        added = [k for k in cur if k not in prev]
        gone = [k for k in prev if k not in cur]
        changed = [k for k in cur if k in prev and cur[k] != prev[k]]
        if prev:  # first run is baseline, not a delta storm
            for k in added[:10]:
                deltas.append(f"[calendar] new: {k}")
            for k in gone[:10]:
                deltas.append(f"[calendar] removed: {k}")
            for k in changed[:10]:
                deltas.append(f"[calendar] changed: {k} -> {cur[k]}")

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
