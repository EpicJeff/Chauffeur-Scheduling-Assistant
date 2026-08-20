"""The scope model: facets, presets, reach — family-network arc S3.

Ships DARK: nothing calls this yet. Its whole job at this stage is to hold
the model from `docs/family_network_design.md` (§5–§9) in one place and be
provably faithful to it (`tests/test_scope.py`), which is what makes every
later slice — audiences on trips (S4), `sees_people` in assemblers (S5),
route facets on the guard (S7) — a wiring change instead of a design change.

Three axes, each answering one question (§5):

  facet        what KIND of thing        (`FACETS`, the unit of enforcement)
  reach        how MUCH of it            none | own | all — a set of named
                                         steps, not a rank, same rule as
                                         auth tiers
  sees_people  about WHOM                stored as INTENT ('everyone',
                                         'children', …), never as a frozen
                                         expansion — a list nobody updates
                                         fails silently when the baby arrives

Plus two capabilities that are not views (§6 Chat B/C): `chat.initiate`
(may I start a conversation, and with whom) and `moments.contribute` (may I
hand the family a moment — S2 already enforces `when_present` for helpers).

Scope answers *what may you see*; role keeps answering *what may you
administer* (§6: administration is not a facet). Stages stay separate and
COMPOSE (§11): a stage is what a child is ready for and changes as they
grow; a scope is a standing decision that changes only when someone changes
it.
"""
from typing import Optional

# --- the facets (§6) --------------------------------------------------------
# kind: how it is enforced (§7).
#   route    — maps to endpoints serving nothing else; the auth guard checks
#              it where it already checks the tier (S7).
#   field    — shares a payload with facets a household wants set differently;
#              only the ASSEMBLER can redact a key (S9).
#   instance — the object carries its own allowlist (S8/S11).
# subject: True marks ◍ — the facet is about people, so `sees_people`
#          filters its rows (S5). Household-shaped facets ignore it.

FACETS = {
    # Calendar & driving
    'calendar.events':           {'kind': 'route',    'subject': True},
    'schedule.assignment':       {'kind': 'field',    'subject': True},
    'schedule.logistics':        {'kind': 'field',    'subject': True},
    'schedule.diagnostics':      {'kind': 'field',    'subject': False},
    'schedule.driver_calendars': {'kind': 'field',    'subject': False},
    'schedule.carpool_contacts': {'kind': 'field',    'subject': False},
    'drives.sheet':              {'kind': 'route',    'subject': False},
    'drives.status_writes':      {'kind': 'route',    'subject': False},
    # Chat — visibility (question A of §6; B and C are capabilities below)
    'chat.family':               {'kind': 'field',    'subject': True},
    'chat.groups':               {'kind': 'field',    'subject': False},
    'chat.dms':                  {'kind': 'field',    'subject': False},
    'chat.event_threads':        {'kind': 'field',    'subject': True},
    'chat.agent':                {'kind': 'route',    'subject': False},
    # Meals & lists
    'meals.plan':                {'kind': 'route',    'subject': False},
    'meals.repertoire':          {'kind': 'route',    'subject': False},
    'meals.prep':                {'kind': 'route',    'subject': False},
    'lists.shopping':            {'kind': 'instance', 'subject': False},
    'lists.errands':             {'kind': 'route',    'subject': False},
    'lists.household_tasks':     {'kind': 'route',    'subject': True},
    'lists.kid_tasks':           {'kind': 'route',    'subject': True},
    # Chores & the points economy
    'chores.board':              {'kind': 'route',    'subject': True},
    'routines':                  {'kind': 'route',    'subject': True},
    'points.balances':           {'kind': 'route',    'subject': True},
    'points.ledger':             {'kind': 'route',    'subject': True},
    'rewards':                   {'kind': 'route',    'subject': False},
    # Presence
    'presence.location':         {'kind': 'route',    'subject': True},
    'presence.status':           {'kind': 'route',    'subject': True},
    'presence.moments':          {'kind': 'route',    'subject': True},
    # Trips, occasions, music, pets
    'trips.gallery':             {'kind': 'route',    'subject': False},
    'trips.detail':              {'kind': 'route',    'subject': False},
    'trips.planning':            {'kind': 'route',    'subject': False},
    'occasions':                 {'kind': 'route',    'subject': True},
    'music':                     {'kind': 'route',    'subject': False},
    'pets':                      {'kind': 'route',    'subject': False},
}

# Reach values. 'parents' and 'invited' are PRESET-TABLE values, resolved by
# reach() — a caller never sees them:
#   'parents' — all for role parent, none otherwise (trips/occasions rows).
#   'invited' — none at the class level with instance membership still
#               honoured (§6A): you do not discover these conversations, but
#               one you are explicitly added to is yours. The Slack
#               external-guest shape; why instance grants are ADDITIVE over a
#               facet rather than bounded by it.
NONE, OWN, ALL = 'none', 'own', 'all'
_TABLE_VALUES = (NONE, OWN, ALL, 'parents', 'invited')

# --- the presets (§9) -------------------------------------------------------
# Role supplies a preset; the person deviates from it. Household adult,
# Child and Helper reproduce today's behaviour EXACTLY (tested per facet).
# Keeping up is the one preset that deliberately changes what a person sees
# (decided by the household 2026-08-20): the kids' calendar, no driving.
# Guest is the §1 answer — extended family, social surfaces only.

PRESETS = {
    'household_adult': {
        'sees_people': 'everyone',
        'chat.initiate': 'anyone',
        'moments.contribute': 'all',
        'facets': {
            'calendar.events': ALL, 'schedule.assignment': ALL,
            'schedule.logistics': ALL, 'schedule.diagnostics': ALL,
            'schedule.driver_calendars': ALL, 'schedule.carpool_contacts': ALL,
            'drives.sheet': ALL, 'drives.status_writes': ALL,
            'chat.family': ALL, 'chat.groups': ALL, 'chat.dms': ALL,
            'chat.event_threads': ALL, 'chat.agent': ALL,
            'meals.plan': ALL, 'meals.repertoire': ALL, 'meals.prep': ALL,
            'lists.shopping': ALL, 'lists.errands': ALL,
            'lists.household_tasks': ALL, 'lists.kid_tasks': ALL,
            'chores.board': ALL, 'routines': ALL,
            'points.balances': ALL, 'points.ledger': ALL, 'rewards': ALL,
            'presence.location': ALL, 'presence.status': ALL,
            'presence.moments': ALL,
            'trips.gallery': 'parents', 'trips.detail': 'parents',
            'trips.planning': 'parents', 'occasions': 'parents',
            'music': ALL, 'pets': ALL,
        },
    },
    'keeping_up': {
        'sees_people': 'children',
        'chat.initiate': 'household',
        'moments.contribute': NONE,
        'facets': {
            'calendar.events': ALL, 'schedule.assignment': NONE,
            'schedule.logistics': NONE, 'schedule.diagnostics': NONE,
            'schedule.driver_calendars': NONE, 'schedule.carpool_contacts': NONE,
            'drives.sheet': NONE, 'drives.status_writes': NONE,
            'chat.family': ALL, 'chat.groups': ALL, 'chat.dms': ALL,
            'chat.event_threads': ALL, 'chat.agent': ALL,
            'meals.plan': ALL, 'meals.repertoire': ALL, 'meals.prep': ALL,
            'lists.shopping': NONE, 'lists.errands': NONE,
            'lists.household_tasks': NONE, 'lists.kid_tasks': ALL,
            'chores.board': ALL, 'routines': ALL,
            'points.balances': ALL, 'points.ledger': NONE, 'rewards': ALL,
            'presence.location': NONE, 'presence.status': ALL,
            'presence.moments': ALL,
            'trips.gallery': NONE, 'trips.detail': NONE,
            'trips.planning': NONE, 'occasions': NONE,
            'music': ALL, 'pets': ALL,
        },
    },
    'child': {
        'sees_people': 'everyone',
        'chat.initiate': 'household',
        'moments.contribute': 'all',
        'facets': {
            'calendar.events': OWN, 'schedule.assignment': OWN,
            'schedule.logistics': OWN, 'schedule.diagnostics': NONE,
            'schedule.driver_calendars': NONE, 'schedule.carpool_contacts': NONE,
            'drives.sheet': NONE, 'drives.status_writes': NONE,
            'chat.family': ALL, 'chat.groups': ALL, 'chat.dms': ALL,
            'chat.event_threads': ALL, 'chat.agent': ALL,
            'meals.plan': ALL, 'meals.repertoire': ALL, 'meals.prep': ALL,
            'lists.shopping': ALL, 'lists.errands': NONE,
            'lists.household_tasks': OWN, 'lists.kid_tasks': OWN,
            'chores.board': OWN, 'routines': OWN,
            'points.balances': ALL, 'points.ledger': OWN, 'rewards': ALL,
            'presence.location': OWN, 'presence.status': ALL,
            'presence.moments': ALL,
            'trips.gallery': NONE, 'trips.detail': NONE,
            'trips.planning': NONE, 'occasions': NONE,
            'music': ALL, 'pets': ALL,
        },
    },
    'helper': {
        'sees_people': 'driven',
        'chat.initiate': 'parents',
        'moments.contribute': 'when_present',
        'facets': {
            'calendar.events': OWN, 'schedule.assignment': OWN,
            'schedule.logistics': OWN, 'schedule.diagnostics': NONE,
            'schedule.driver_calendars': NONE, 'schedule.carpool_contacts': NONE,
            'drives.sheet': OWN, 'drives.status_writes': OWN,
            'chat.family': NONE, 'chat.groups': NONE, 'chat.dms': ALL,
            'chat.event_threads': 'invited', 'chat.agent': NONE,
            'meals.plan': NONE, 'meals.repertoire': NONE, 'meals.prep': NONE,
            'lists.shopping': NONE, 'lists.errands': NONE,
            'lists.household_tasks': NONE, 'lists.kid_tasks': NONE,
            'chores.board': NONE, 'routines': NONE,
            'points.balances': NONE, 'points.ledger': NONE, 'rewards': NONE,
            'presence.location': NONE, 'presence.status': NONE,
            'presence.moments': NONE,
            'trips.gallery': NONE, 'trips.detail': NONE,
            'trips.planning': NONE, 'occasions': NONE,
            'music': NONE, 'pets': NONE,
        },
    },
    'guest': {
        # The §9 table writes '—' for a guest's sees_people: the axis does no
        # work for them (their two facets are household-shaped feeds), so it
        # stays 'everyone' rather than inventing a fourth meaning for empty.
        'sees_people': 'everyone',
        'chat.initiate': NONE,
        'moments.contribute': NONE,
        'facets': {
            'calendar.events': NONE, 'schedule.assignment': NONE,
            'schedule.logistics': NONE, 'schedule.diagnostics': NONE,
            'schedule.driver_calendars': NONE, 'schedule.carpool_contacts': NONE,
            'drives.sheet': NONE, 'drives.status_writes': NONE,
            'chat.family': 'invited', 'chat.groups': 'invited',
            'chat.dms': 'invited', 'chat.event_threads': 'invited',
            'chat.agent': NONE,
            'meals.plan': NONE, 'meals.repertoire': NONE, 'meals.prep': NONE,
            'lists.shopping': NONE, 'lists.errands': NONE,
            'lists.household_tasks': NONE, 'lists.kid_tasks': NONE,
            'chores.board': NONE, 'routines': NONE,
            'points.balances': NONE, 'points.ledger': NONE, 'rewards': NONE,
            'presence.location': NONE, 'presence.status': NONE,
            'presence.moments': ALL,
            'trips.gallery': NONE, 'trips.detail': NONE,
            'trips.planning': NONE, 'occasions': NONE,
            'music': NONE, 'pets': ALL,
        },
    },
}

# The role→preset mapping. 'keeping_up' is never inferred — the household
# retired the isKeepingUpAdult() heuristic on purpose (§9): it was guessing
# at a scope nobody could state. It becomes a preset somebody CHOOSES, stored
# in member['scope']['preset'].
_ROLE_PRESETS = {'parent': 'household_adult', 'adult': 'household_adult',
                 'child': 'child', 'helper': 'helper', 'guest': 'guest'}


def preset_for(member: dict) -> str:
    """The preset governing this member: their explicit pick, else role's.

    A record with NO role reads the way ensure_member_roles() would backfill
    it (is_child → child, else adult) — legacy rows must not quietly become
    guests. A role this module has never heard of DOES read as guest: for a
    novel role, the failure to survive is over-granting, not under."""
    chosen = ((member.get('scope') or {}).get('preset') or '').strip()
    if chosen in PRESETS:
        return chosen
    role = member.get('role')
    if not role:
        role = 'child' if member.get('is_child') else 'adult'
    return _ROLE_PRESETS.get(role, 'guest')


def _table_value(member: dict, facet: str) -> str:
    """Preset value with the member's overrides applied — still a TABLE value
    ('parents'/'invited' possible); reach() resolves it for callers."""
    if facet not in FACETS:
        raise KeyError(f"unknown facet: {facet}")
    overrides = (member.get('scope') or {}).get('overrides') or {}
    v = overrides.get(facet)
    if v in _TABLE_VALUES:
        return v
    return PRESETS[preset_for(member)]['facets'][facet]


def reach(member: dict, facet: str) -> str:
    """none | own | all — the resolved answer for this person and facet.

    'parents' resolves by role (a household adult's trips row means: parents
    see trips, other adults do not). 'invited' resolves to none — the class
    grants nothing; instance membership is honoured by can_see()."""
    v = _table_value(member, facet)
    if v == 'parents':
        return ALL if member.get('role') == 'parent' else NONE
    if v == 'invited':
        return NONE
    return v


def can_see(member: dict, facet: str,
            instance_member_ids: Optional[list] = None) -> bool:
    """May this person see this facet at all?

    `instance_member_ids` is the object's own membership (a channel's
    member_ids, a list's shared_with): instance grants are ADDITIVE over a
    facet (§7) — a guest added to one group has it without the class. But
    note the counterpart rule for secrets lives in audience_allows(), not
    here: a closed default is not a grant."""
    if reach(member, facet) != NONE:
        return True
    return bool(instance_member_ids) and member.get('id') in instance_member_ids


def may_be_added(member: dict, facet: str) -> bool:
    """May this person be PUT INTO an instance of this facet (a group, an
    event thread)? Every level except a hard 'none' qualifies — 'invited' is
    exactly the addable-but-cannot-discover level. This is where 'none' and
    'invited' actually differ: a guest is addable and then talks freely; a
    helper's group chat is never (their channel is a DM with a parent)."""
    return _table_value(member, facet) != NONE


def chat_initiate(member: dict) -> str:
    """none | parents | household | anyone (§6B) — who may this person OPEN a
    conversation with. Being added to one by somebody who can is always
    allowed; that is what 'none' deliberately does not prevent."""
    overrides = (member.get('scope') or {}).get('overrides') or {}
    v = overrides.get('chat.initiate')
    if v in ('none', 'parents', 'household', 'anyone'):
        return v
    return PRESETS[preset_for(member)]['chat.initiate']


def moments_contribute(member: dict) -> str:
    """none | when_present | all (§6C). Contribution is not membership —
    S2 already enforces when_present for helpers at the send endpoint."""
    overrides = (member.get('scope') or {}).get('overrides') or {}
    v = overrides.get('moments.contribute')
    if v in ('none', 'when_present', 'all'):
        return v
    return PRESETS[preset_for(member)]['moments.contribute']


def resolved_map(member: dict) -> dict:
    """The member's whole scope, RESOLVED, for the shell (family-network
    S13): every facet's reach plus the two capabilities. This is what the
    client shapes tabs and cards from — the app stops guessing at a scope
    nobody could state, because the server now states it."""
    return {
        'facets': {f: reach(member, f) for f in FACETS},
        'chat_initiate': chat_initiate(member),
        'moments_contribute': moments_contribute(member),
    }


# --- sees_people: the WHOSE axis (§5) ---------------------------------------
# Stored as intent, expanded at read time, so 'the children' self-updates
# when the family grows. Applies only to subject (◍) facets; household-shaped
# facets ignore it.

def sees_people(member: dict, all_members: list,
                sched: Optional[dict] = None) -> Optional[set]:
    """None = everyone (today's behaviour, and the empty-list convention the
    four existing allowlists already use). Otherwise the set of member ids
    whose rows this person may see on ◍ facets — always including themselves,
    because 'you may not see your own rows' is never a scope, only a bug."""
    intent = (member.get('scope') or {}).get('sees_people') \
        or PRESETS[preset_for(member)]['sees_people']
    if isinstance(intent, dict):        # {'kind': 'chosen', 'ids': [...]}
        ids = set(intent.get('ids') or [])
        ids.add(member.get('id'))
        return ids
    if intent == 'everyone':
        return None
    if intent == 'children':
        ids = {m['id'] for m in all_members if m.get('role') == 'child'}
        ids.add(member.get('id'))
        return ids
    if intent == 'driven':
        # The kids the schedule has this person driving — computed from the
        # same placement S2 trusts, so it needs no hand-kept list either.
        from services import presence, storage
        sched = sched or storage.get_cached_schedule() or {}
        ids = set()
        d_id = member.get('driver_id')
        if d_id:
            assignments = dict(sched.get('assignments') or {})
            assignments.update(sched.get('ghost_assignments') or {})
            for ev in sched.get('events') or []:
                ev_id = str(ev.get('id') or '')
                if assignments.get(ev_id) == d_id:
                    ids.update(m['id'] for m
                               in presence.members_at_event(ev, ev_id, sched))
        ids.add(member.get('id'))
        return ids
    return None


def filter_subjects(member: dict, facet: str, rows: list, all_members: list,
                    subject_of=lambda r: r.get('member_id'),
                    sched: Optional[dict] = None) -> list:
    """Apply sees_people to a ◍ facet's rows. Non-subject facets pass
    through untouched — the axis is about people, not about things."""
    if not FACETS.get(facet, {}).get('subject'):
        return rows
    allowed = sees_people(member, all_members, sched)
    if allowed is None:
        return rows
    return [r for r in rows if subject_of(r) in allowed]


# --- the welded schedule blob (§8.1) ----------------------------------------
# The ~30-key blob's driving keys, grouped by the facet that owns each. This
# is THE definition — /api/schedule and /api/home_board both redact through
# redact_schedule_blob, which is what makes §13's "home_board redacts exactly
# as /api/schedule does for the same viewer" true by construction.

SCHEDULE_BLOB_FACETS = {
    'schedule.assignment': ('assignments', 'ghost_assignments', 'ghost_drivers',
                            'car_assignments', 'assist_assignments'),
    # the operational picture: edges, chaining, and the live drives
    'schedule.logistics': ('route_edges', 'initial_edges', 'final_edges',
                           'completed_drives', 'in_progress_drives'),
    'schedule.carpool_contacts': ('assist_contacts',),
    'schedule.driver_calendars': ('driver_events',),
    # solver reasoning: unassigned causes, conflicts, AI notes, rule matches
    'schedule.diagnostics': ('diagnostics', 'ai_metadata', 'matched_rules',
                             'unassigned', 'true_unassigned', 'conflicts',
                             'lateness_warnings', 'overridden_events',
                             'no_location', 'solving_dates'),
}


def calendar_event_subjects(ev: dict, members, passengers_by_id) -> set:
    """Which members a calendar event belongs to — passenger calendar
    ownership, resolved passenger id, or title hashtag: My Day's binding,
    minus matched_rules (the §5 grain: events are attributed to people
    through calendar_ids). One definition for the raw-Google endpoint (S5)
    and the cached blob (S9)."""
    from services import family_digest
    subjects = set()
    for m in members:
        p_id = m.get('passenger_id')
        if not p_id:
            continue
        p = passengers_by_id.get(p_id) or {}
        p_cals = set(p.get('calendar_ids') or [])
        p_tags = {t.lower() for t in (p.get('hashtags') or [])}
        if family_digest._kid_event_match(ev, str(ev.get('id') or ''), p_id,
                                          p_cals, p_tags, {}):
            subjects.add(m['id'])
    return subjects


def redact_schedule_blob(blob: dict, viewer: Optional[dict]) -> dict:
    """The §8.1 split, applied where the data is ASSEMBLED (family-network
    S9). Keys whose facet the viewer does not reach are REMOVED, never
    emptied — an empty dict reads as "nobody assigned", a missing key reads
    as "not yours to know". Events narrow by sees_people only for a
    full-reach viewer whose scope names people (the keeping-up adult); 'own'
    viewers keep today's payload until S13 teaches the shells to ask for
    less. No viewer, no change — a panel is a place."""
    if not viewer or not isinstance(blob, dict):
        return blob
    out = dict(blob)
    for facet, keys in SCHEDULE_BLOB_FACETS.items():
        if reach(viewer, facet) == NONE:
            for k in keys:
                out.pop(k, None)
    if reach(viewer, 'calendar.events') == ALL:
        from services import storage
        members = storage.get_all_members()
        allowed = sees_people(viewer, members)
        if allowed is not None:
            passengers = {p.get('id'): p for p in storage.get_all_passengers()}
            out['events'] = [e for e in (out.get('events') or [])
                             if calendar_event_subjects(e, members, passengers)
                             & allowed]
    return out


def redact_board(data: dict, viewer: Optional[dict]) -> dict:
    """§13: the board redacts exactly as /api/schedule does for the same
    viewer — the drives/schedule tiles re-serve the blob as their 'schedule'
    sub-payload, so each goes through the same redactor. Copy-on-write:
    build()'s result is cached and shared with the panels, which must keep
    the unredacted original (a panel's own scope story is the shell's, S13)."""
    if not viewer or not isinstance(data, dict):
        return data
    tiles, changed = [], False
    for t in data.get('tiles') or []:
        if isinstance(t, dict) and isinstance(t.get('schedule'), dict):
            t = {**t, 'schedule': redact_schedule_blob(t['schedule'], viewer)}
            changed = True
        tiles.append(t)
    if not changed:
        return data
    return {**data, 'tiles': tiles}


# --- audience: per-object secrecy (§7) --------------------------------------
# Every shareable object may declare an `audience`; each object TYPE declares
# its default. The four existing allowlists (chores, cars, channels, lists)
# mean empty=open, which is right for a chore anyone may claim and wrong for
# a surprise — so trips and occasions default CLOSED. For anything secret,
# choose the direction whose failure you can survive: an allow-list that
# fails closed costs "I can't see the trip you're planning" (a complaint); a
# deny-list that fails open costs the surprise itself, silently.
# This supersedes docs/occasion_design.md's `hidden_from` proposal.

AUDIENCE_DEFAULTS = {
    'trip': 'parents',
    'occasion': 'parents',
    'gift_list': 'parents',      # when it exists — never 'household'
    'shopping_list': 'household',
    'chore': 'household',
    'car': 'household',
    'channel': 'household',
}


def audience_of(obj: dict, obj_type: str) -> str:
    aud = obj.get('audience')
    if aud in ('household', 'parents', 'shared'):
        return aud
    return AUDIENCE_DEFAULTS.get(obj_type, 'household')


def audience_allows(obj: dict, obj_type: str, member: Optional[dict]) -> bool:
    """May this person see this object? Parents always may — audience hides
    things FROM the household, never from the people planning the surprise.
    `member=None` is an ANONYMOUS surface — a wall panel is a place, not a
    person, and cannot hold a 'parents' audience just because a parent is
    standing in front of it (§7) — so only 'household' passes.
    Note the §7 rule this deliberately does not bend: a facet grant is not an
    audience grant ('trips.gallery: all' does not reveal a parents-audience
    trip), and vice versa — callers check both."""
    if member is None:
        return audience_of(obj, obj_type) == 'household'
    if member.get('role') == 'parent':
        return True
    aud = audience_of(obj, obj_type)
    if aud == 'household':
        return True
    if aud == 'shared':
        return member.get('id') in (obj.get('shared_with') or [])
    return False   # 'parents', and any unknown value fails CLOSED
