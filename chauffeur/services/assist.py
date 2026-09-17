"""Outside hands — what a contact helps with (load arc A1, slice 2).

`AssistContact.kinds` is a free tag list, and the arc's founding rule is that
**nothing branches on it**: behaviour comes from what REFERENCES a contact, or
every new kind of help ("tutoring", "pet sitting", "grandma who cooks Sunday
dinner") becomes a code change.

That rule is about CAPABILITY, and it still holds — nothing here permits or
refuses anything. What it never meant is that a family should be offered the
thirteen-year-old who does the dishes when they are looking for somebody to
drive. So the two tags that name the app's two hand-over surfaces are given
one job and one job only: **narrowing a picker list**.

The filter rule, which is the whole design:

    A contact is OFFERED unless the family has positively said they do the
    other thing and not this one.

    no work tags at all      -> offered everywhere (we know nothing)
    only 'tutoring', 'pets'  -> offered everywhere (still nothing about these)
    'housework'              -> offered for tasks, not for drives
    'driving'                -> offered for drives, not for tasks
    both                     -> offered for both

Hiding therefore requires positive information, which is what keeps this a
filter instead of a gate. A contact nobody has tagged never silently becomes
unusable, an unrecognised tag never costs anyone their place in a list, and
**the server refuses nothing on this basis** — `set_assist_assignment` and the
task assignment path both accept any contact, because the family knows things
the tags do not.
"""

# The app's two hand-over surfaces. A third would be a new picker and a new
# assignment path — i.e. real work — so mirroring them here adds no trap that
# building the surface itself would not already have.
SURFACES = ('driving', 'housework')

# What families actually type. Kept small on purpose: an unknown tag is not a
# mistake, it simply says nothing about these two surfaces.
_SYNONYMS = {
    'driving': {'driving', 'carpool', 'carpooling', 'rides', 'ride', 'drives', 'driver'},
    'housework': {'housework', 'house work', 'tasks', 'task', 'chores', 'chore',
                  'cleaning', 'help', 'housekeeping'},
}


# How an outside hand is named in a field that otherwise holds a member id
# (`HouseholdTask.assigned_to`). A prefix rather than a parallel column because
# the question "who holds this?" has one answer, and a second nullable field
# would let a task be held by two people at once. Drives took the other route —
# a separate `assist_assignments` map — because there the solver has to be told
# the event is gone, and that is a different question from who has it.
ID_PREFIX = 'assist:'


# --- Instance vs series -----------------------------------------------------
# Coverage keys mirror what overrides and event configs already do: an
# occurrence is keyed by its own event id, a whole series by the bare
# `recurring_event_id`. Nothing new is invented here on purpose — a family that
# has learnt "Entire Series / This Instance" from the event modal should not
# have to learn a second recurrence model for carpools.
#
# Resolution is instance-first, which is the rule that makes the useful
# sentence expressible: "Emma's mom has Tuesdays, except she can't this one."
# Split drives keep that model at leg granularity: `X_dropoff` and `X_pickup`
# are independent instance keys, while `SERIES_dropoff` and `SERIES_pickup`
# are independent standing arrangements. Existing X/SERIES rows remain
# whole-drive fallbacks.

LEG_SUFFIXES = ('_dropoff', '_pickup')


def split_leg(event_id):
    """Return (parent id, leg name or None) for a schedule event id."""
    value = str(event_id or '')
    for suffix in LEG_SUFFIXES:
        if value.endswith(suffix):
            return value[:-len(suffix)], suffix[1:]
    return value, None


def scoped_key(event_id, recurring_event_id=None, scope='instance'):
    """Storage key for this occurrence/series without losing its drive leg."""
    event_id = str(event_id or '')
    _, leg = split_leg(event_id)
    if scope == 'series' and recurring_event_id:
        recurring_base, recurring_leg = split_leg(recurring_event_id)
        chosen_leg = leg or recurring_leg
        return f"{recurring_base}_{chosen_leg}" if chosen_leg else recurring_base
    return event_id

def coverage_keys(event) -> list:
    """The keys a coverage row for this event may be stored under, most
    specific first."""
    get = event.get if isinstance(event, dict) else lambda k, d=None: getattr(event, k, d)
    keys = []
    eid = get('id')
    if eid:
        keys.append(str(eid))
    # `original_event_id` is the unsplit occurrence. It stays ahead of series
    # keys so a one-off whole-drive decision overrides a standing arrangement.
    # It also preserves old whole-drive assignments and unrolled copies.
    orig = get('original_event_id')
    if orig and str(orig) not in keys:
        keys.append(str(orig))
    rec = get('recurring_event_id')
    _, leg = split_leg(eid)
    if rec and leg:
        leg_series = scoped_key(eid, rec, 'series')
        if leg_series not in keys:
            keys.append(leg_series)
    if rec and str(rec) not in keys:
        keys.append(str(rec))
    return keys


def coverage_for(assist_map: dict, event):
    """The contact id covering this event, or None. Two dict lookups, never a
    scan — this runs per event on every solve and every board build."""
    if not assist_map:
        return None
    for k in coverage_keys(event):
        got = assist_map.get(k)
        if got:
            return got
    return None


def clear_coverage(event_id, recurring_event_id=None, actor=None):
    """Take one drive (or one leg) back without changing its sibling leg.

    A legacy whole-drive row is split onto the sibling before removal. That
    makes "Emma's mom had both; we will pick up" behave as spoken instead of
    letting the parent fallback silently cover the pickup again.
    """
    from services import storage
    event_id = str(event_id or '')
    base, leg = split_leg(event_id)
    rec_base, _ = split_leg(recurring_event_id)
    rows = {str(r.get('event_id') or ''): r
            for r in storage.get_assist_assignments()}

    if leg:
        sibling = 'pickup' if leg == 'dropoff' else 'dropoff'
        moves = [(base, f"{base}_{sibling}")]
        if rec_base:
            moves.append((rec_base, f"{rec_base}_{sibling}"))
        for source, target in moves:
            row = rows.get(source)
            if row and target not in rows:
                storage.set_assist_assignment(
                    target, row.get('contact_id'), row.get('note') or '',
                    scope=row.get('scope') or 'instance',
                    event_date=row.get('event_date') or '',
                    event_title=row.get('event_title') or '', actor=actor)
            if row:
                storage.clear_assist_assignment(source, actor=actor)

    if leg:
        targets = [event_id]
        if rec_base:
            targets.append(scoped_key(event_id, rec_base, 'series'))
    else:
        # A parent/whole-drive take-back means every stored shape of it.
        targets = [base, f"{base}_dropoff", f"{base}_pickup"]
        if rec_base:
            targets.extend([rec_base, f"{rec_base}_dropoff", f"{rec_base}_pickup"])
    for target in dict.fromkeys(targets):
        storage.clear_assist_assignment(target, actor=actor)


def is_assist_id(value) -> bool:
    return str(value or '').startswith(ID_PREFIX)


def contact_id(value):
    """The bare contact id inside an `assist:` reference, or None."""
    v = str(value or '')
    return v[len(ID_PREFIX):] if v.startswith(ID_PREFIX) else None


def make_id(cid: str) -> str:
    return f"{ID_PREFIX}{cid}"


def _tags(contact: dict):
    return {str(k).strip().lower() for k in ((contact or {}).get('kinds') or []) if str(k).strip()}


def helps_with(contact: dict) -> list:
    """The KNOWN work surfaces this contact is tagged for, normalised.

    Empty means "nobody has said" — which the filter reads as "offer them",
    never as "they do nothing"."""
    tags = _tags(contact)
    return [s for s in SURFACES if tags & _SYNONYMS[s]]


def offers(contact: dict, surface: str) -> bool:
    """Should this contact appear in the picker for `surface`?

    True whenever the family has told us nothing relevant — see the module
    docstring. Never call this to REFUSE an assignment; it decides what a list
    shows, not what is allowed."""
    known = helps_with(contact)
    if not known:
        return True
    return surface in known


def for_surface(contacts, surface: str) -> list:
    """The picker list: active contacts that `offers` lets through, in the
    order they were given."""
    return [c for c in (contacts or [])
            if c.get('active', True) is not False and offers(c, surface)]


def other_kinds(contact: dict) -> list:
    """The free tags that say nothing about the two work surfaces — 'tutoring',
    'pets', 'grandma'. Returned so the editor can show them separately without
    the synonym table needing a JavaScript twin."""
    return [k for k in ((contact or {}).get('kinds') or [])
            if not any(str(k).strip().lower() in _SYNONYMS[s] for s in SURFACES)]


def decorate(contacts):
    """Stamp `helps_with` and `other_kinds` onto contact rows for the UI, so a
    picker filters on a normalised list rather than re-implementing the synonym
    table in JavaScript — two copies of this rule would drift the day they
    shipped."""
    for c in (contacts or []):
        if isinstance(c, dict):
            c['helps_with'] = helps_with(c)
            c['other_kinds'] = other_kinds(c)
    return contacts
