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

def coverage_keys(event) -> list:
    """The keys a coverage row for this event may be stored under, most
    specific first."""
    get = event.get if isinstance(event, dict) else lambda k, d=None: getattr(event, k, d)
    keys = []
    eid = get('id')
    if eid:
        keys.append(str(eid))
    rec = get('recurring_event_id')
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
