"""The scope model (services/scope.py, family-network arc S3).

S3 ships dark — nothing calls scope yet — so these tests ARE the slice: they
pin the preset table to the design doc (docs/family_network_design.md §9) by
transcribing it a second time. Two independent transcriptions must agree, so
a drive-by edit to either fails loudly instead of shipping a quiet change to
what a person may see.

The load-bearing constraints from §9/§13:
- Household adult, Child and Helper reproduce today's behaviour exactly.
- Keeping up is the one preset that deliberately changes what a person sees.
- A guest reaches presence.moments and pets and is refused everything else.
- Scope and stages COMPOSE; neither consults the other.
- Audiences fail CLOSED for secrets; instance grants are additive; a closed
  default is not a grant.

Run from chauffeur/:  python tests/test_scope.py
"""
from harness import check  # noqa: F401  (isolates CHAUFFEUR_DATA_DIR)

from services import scope, storage


def _m(role='adult', mid='m1', **kw):
    return {'id': mid, 'name': mid, 'role': role, **kw}


# --- the table, transcribed a second time (§9) -------------------------------
# Facet -> (household PARENT, household ADULT, keeping_up, child, helper, guest)
# after resolution: what reach() must answer. This is deliberately the
# RESOLVED view — 'parents' rows split into the parent/adult columns.

EXPECTED = {
    'calendar.events':           ('all', 'all', 'all', 'own', 'own', 'none'),
    'schedule.assignment':       ('all', 'all', 'none', 'own', 'own', 'none'),
    'schedule.logistics':        ('all', 'all', 'none', 'own', 'own', 'none'),
    'schedule.diagnostics':      ('all', 'all', 'none', 'none', 'none', 'none'),
    'schedule.driver_calendars': ('all', 'all', 'none', 'none', 'none', 'none'),
    'schedule.carpool_contacts': ('all', 'all', 'none', 'none', 'none', 'none'),
    'drives.sheet':              ('all', 'all', 'none', 'none', 'own', 'none'),
    'drives.status_writes':      ('all', 'all', 'none', 'none', 'own', 'none'),
    'chat.family':               ('all', 'all', 'all', 'all', 'none', 'none'),
    'chat.groups':               ('all', 'all', 'all', 'all', 'none', 'none'),
    'chat.dms':                  ('all', 'all', 'all', 'all', 'all', 'none'),
    'chat.event_threads':        ('all', 'all', 'all', 'all', 'none', 'none'),
    'chat.agent':                ('all', 'all', 'all', 'all', 'none', 'none'),
    'meals.plan':                ('all', 'all', 'all', 'all', 'none', 'none'),
    'meals.repertoire':          ('all', 'all', 'all', 'all', 'none', 'none'),
    'meals.prep':                ('all', 'all', 'all', 'all', 'none', 'none'),
    'lists.shopping':            ('all', 'all', 'none', 'all', 'none', 'none'),
    'lists.errands':             ('all', 'all', 'none', 'none', 'none', 'none'),
    'lists.household_tasks':     ('all', 'all', 'none', 'own', 'none', 'none'),
    'lists.kid_tasks':           ('all', 'all', 'all', 'own', 'none', 'none'),
    'chores.board':              ('all', 'all', 'all', 'own', 'none', 'none'),
    'routines':                  ('all', 'all', 'all', 'own', 'none', 'none'),
    'points.balances':           ('all', 'all', 'all', 'all', 'none', 'none'),
    'points.ledger':             ('all', 'all', 'none', 'own', 'none', 'none'),
    'rewards':                   ('all', 'all', 'all', 'all', 'none', 'none'),
    'presence.location':         ('all', 'all', 'none', 'own', 'none', 'none'),
    'presence.status':           ('all', 'all', 'all', 'all', 'none', 'none'),
    'presence.moments':          ('all', 'all', 'all', 'all', 'none', 'all'),
    'trips.gallery':             ('all', 'none', 'none', 'none', 'none', 'none'),
    'trips.detail':              ('all', 'none', 'none', 'none', 'none', 'none'),
    'trips.planning':            ('all', 'none', 'none', 'none', 'none', 'none'),
    'occasions':                 ('all', 'none', 'none', 'none', 'none', 'none'),
    'music':                     ('all', 'all', 'all', 'all', 'none', 'none'),
    'pets':                      ('all', 'all', 'all', 'all', 'none', 'all'),
}

_COLUMNS = [
    _m('parent', 'p'),
    _m('adult', 'a'),
    _m('adult', 'k', scope={'preset': 'keeping_up'}),
    _m('child', 'c'),
    _m('helper', 'h'),
    _m('guest', 'g'),
]


def scenario_every_preset_covers_every_facet():
    for name, p in scope.PRESETS.items():
        check(set(p['facets']) == set(scope.FACETS),
              f"preset {name} must answer every facet, no more, no less")
        for f, v in p['facets'].items():
            check(v in scope._TABLE_VALUES, f"{name}.{f} holds junk: {v}")


def scenario_the_table_is_the_table():
    """Per facet, per column — never in aggregate (§13)."""
    for facet, row in EXPECTED.items():
        for member, want in zip(_COLUMNS, row):
            got = scope.reach(member, facet)
            check(got == want,
                  f"{facet} for {member['id']}: want {want}, got {got}")


def scenario_guest_gets_the_social_surfaces_and_nothing_else():
    g = _m('guest', 'g')
    reachable = {f for f in scope.FACETS if scope.reach(g, f) != 'none'}
    check(reachable == {'presence.moments', 'pets'},
          f"a guest reaches moments and pets only, got {sorted(reachable)}")
    check(scope.chat_initiate(g) == 'none', "a guest can never open a conversation")


def scenario_invited_honours_instance_membership():
    g = _m('guest', 'g')
    check(not scope.can_see(g, 'chat.groups'),
          "a guest does not discover group chats")
    check(scope.can_see(g, 'chat.groups', instance_member_ids=['a', 'g']),
          "…but one they are explicitly added to is theirs (Slack-guest shape)")
    check(not scope.can_see(g, 'chat.groups', instance_member_ids=['a', 'b']),
          "somebody else's membership is not a grant")


def scenario_keeping_up_is_the_decided_deviation():
    """The one intentional behaviour change in the table (§9): calendar
    without any driving, narrowed to the children. Today she sees driver
    chips on every family card; after S13 she must not."""
    k = _m('adult', 'k', scope={'preset': 'keeping_up'})
    check(scope.reach(k, 'calendar.events') == 'all', "she keeps the calendar")
    for f in ('schedule.assignment', 'schedule.logistics', 'schedule.diagnostics',
              'schedule.driver_calendars', 'schedule.carpool_contacts',
              'drives.sheet', 'drives.status_writes'):
        check(scope.reach(k, f) == 'none', f"every driving facet is off ({f})")
    kids = scope.sees_people(k, [_m('parent', 'p'), _m('child', 'c1'),
                                 _m('child', 'c2'), k])
    check(kids == {'c1', 'c2', 'k'},
          "sees_people: the children — computed from role, so it self-updates")


def scenario_overrides_deviate_without_replacing_the_preset():
    a = _m('adult', 'a', scope={'overrides': {'presence.location': 'none'}})
    check(scope.reach(a, 'presence.location') == 'none', "the override wins")
    check(scope.reach(a, 'chores.board') == 'all', "everything else is the preset")
    junk = _m('adult', 'a2', scope={'overrides': {'presence.location': 'sometimes'}})
    check(scope.reach(junk, 'presence.location') == 'all',
          "a junk override is ignored, never obeyed")


def scenario_a_roleless_record_is_not_a_guest():
    """Legacy rows predate roles; ensure_member_roles() backfills them, and
    preset_for reads them the same way. An UNKNOWN role stays a guest — for
    a novel role the failure to survive is over-granting."""
    check(scope.preset_for({'id': 'x'}) == 'household_adult',
          "no role reads as the adult backfill")
    check(scope.preset_for({'id': 'x', 'is_child': True}) == 'child',
          "no role + is_child reads as the child backfill")
    check(scope.preset_for({'id': 'x', 'role': 'assistant'}) == 'guest',
          "a role this module never heard of fails closed")


def scenario_sees_people_intents():
    fam = [_m('parent', 'p'), _m('child', 'c1'), _m('child', 'c2')]
    check(scope.sees_people(_m('adult', 'a'), fam) is None,
          "everyone = None = today's behaviour")
    chosen = _m('adult', 'gran', scope={'sees_people': {'kind': 'chosen',
                                                        'ids': ['c1']}})
    check(scope.sees_people(chosen, fam) == {'c1', 'gran'},
          "a chosen list is those people plus always yourself")


def scenario_sees_people_driven_comes_from_the_schedule():
    storage.members_table.truncate()
    storage.add_member({"id": "nan", "name": "Nanny", "role": "helper",
                        "is_child": False, "driver_id": "d_nan"})
    storage.add_member({"id": "emma", "name": "Emma", "role": "child",
                        "is_child": True, "passenger_id": "p_emma"})
    storage.add_member({"id": "jack", "name": "Jack", "role": "child",
                        "is_child": True, "passenger_id": "p_jack"})
    nan = storage.get_member("nan")
    # Placement is the same four-way binding S2 trusts: the assigned driver
    # plus passenger-bound members (here: the event carries Emma's resolved
    # passenger id in calendar_ids, exactly as the solver writes it back).
    sched = {'events': [{'id': 'ev1', 'title': "Volleyball",
                         'calendar_ids': ['p_emma']}],
             'assignments': {'ev1': 'd_nan'}, 'matched_rules': {}}
    ids = scope.sees_people(nan, storage.get_all_members(), sched)
    check(ids == {'nan', 'emma'},
          "the helper sees the kid they drive (and themselves) — never Jack")
    check(scope.sees_people(nan, storage.get_all_members(), {}) == {'nan'},
          "no schedule, no drives: the computed list fails closed")


def scenario_filter_subjects_only_bites_subject_facets():
    k = _m('adult', 'k', scope={'preset': 'keeping_up'})
    fam = [_m('parent', 'p'), _m('child', 'c1'), k]
    rows = [{'member_id': 'p'}, {'member_id': 'c1'}]
    check(scope.filter_subjects(k, 'calendar.events', rows, fam)
          == [{'member_id': 'c1'}],
          "a ◍ facet is narrowed to the children")
    check(scope.filter_subjects(k, 'meals.repertoire', rows, fam) == rows,
          "a household-shaped facet ignores the axis entirely")


def scenario_the_delivered_map_is_the_resolved_truth():
    """S13: the shell shapes itself from resolved_map — so the map must be
    the same answers reach() gives, every facet, plus the capabilities."""
    k = _m('adult', 'k', scope={'preset': 'keeping_up'})
    m = scope.resolved_map(k)
    check(set(m['facets']) == set(scope.FACETS), "every facet answered")
    check(m['facets']['calendar.events'] == 'all'
          and m['facets']['schedule.assignment'] == 'none'
          and m['facets']['presence.location'] == 'none',
          "the keeping-up shape the shell keys on is delivered, not guessed")
    check(m['chat_initiate'] == 'household' and m['moments_contribute'] == 'none',
          "the two capabilities ride along")


def scenario_the_editor_draws_from_one_meta():
    """S14: groups cover every facet exactly once, labels name them all, and
    the preset defaults the editor shows beside each row are resolved_map's
    own answers — the editor can never disagree with enforcement."""
    meta = scope.editor_meta()
    grouped = [f for g in meta['groups'] for f in g['facets']]
    check(sorted(grouped) == sorted(scope.FACETS),
          "groups cover every facet exactly once")
    check(set(meta['labels']) == set(scope.FACETS), "every facet has a label")
    check(set(meta['presets']) == set(scope.PRESETS), "every preset resolved")
    check(meta['presets']['keeping_up']['facets']['schedule.assignment'] == 'none',
          "the defaults shown are enforcement's own answers")
    check(set(meta['own_capable'])
          == {'schedule.assignment', 'schedule.logistics', 'chores.board',
              'chat.event_threads', 'points.ledger', 'presence.location'},
          "own is offered on exactly the §9 six")


def scenario_audience_fails_closed():
    trip = {'id': 't1', 'title': 'Disney'}       # no audience declared
    check(scope.audience_allows(trip, 'trip', _m('parent', 'p')),
          "parents always see the surprise they are planning")
    check(not scope.audience_allows(trip, 'trip', _m('child', 'c')),
          "the default for a trip is CLOSED — no declaration needed")
    check(not scope.audience_allows(trip, 'trip', _m('adult', 'a')),
          "closed means closed for non-parent adults too")
    check(scope.audience_allows({'id': 'l1'}, 'shopping_list', _m('child', 'c')),
          "a shopping list defaults open — today's behaviour")
    weird = {'id': 't2', 'audience': 'everybody!!'}
    check(not scope.audience_allows(weird, 'trip', _m('child', 'c')),
          "an unknown audience value fails closed, never open")


def scenario_sharing_reveals_to_exactly_those_people():
    trip = {'id': 't1', 'audience': 'shared', 'shared_with': ['c1']}
    check(scope.audience_allows(trip, 'trip', _m('child', 'c1')),
          "sharing with one child reveals it to that child")
    check(not scope.audience_allows(trip, 'trip', _m('child', 'c2')),
          "…and to nobody else")
    check(scope.audience_allows(trip, 'trip', _m('parent', 'p')),
          "parents are never locked out of their own surprise")


def scenario_a_closed_default_is_not_a_grant():
    """§7: 'trips.gallery: all' does not reveal a parents-audience trip."""
    a = _m('adult', 'a', scope={'overrides': {'trips.gallery': 'all'}})
    check(scope.reach(a, 'trips.gallery') == 'all', "the facet is granted")
    check(not scope.audience_allows({'id': 't1'}, 'trip', a),
          "…and the audience still refuses: both doors must agree")


def scenario_scope_and_stage_compose():
    """§11: different lifecycles, never merged. A Navigator with
    calendar.events: own still gets horizon_days 13."""
    from services import stages
    kid = _m('child', 'c', stage_override='navigator',
             scope={'overrides': {'calendar.events': 'own'}})
    check(scope.reach(kid, 'calendar.events') == 'own', "scope answers scope")
    check(stages.capabilities(kid).get('horizon_days') == 13,
          "stages answer stages, unmoved by any scope override")


SCENARIOS = [
    scenario_every_preset_covers_every_facet,
    scenario_the_table_is_the_table,
    scenario_guest_gets_the_social_surfaces_and_nothing_else,
    scenario_invited_honours_instance_membership,
    scenario_keeping_up_is_the_decided_deviation,
    scenario_overrides_deviate_without_replacing_the_preset,
    scenario_a_roleless_record_is_not_a_guest,
    scenario_sees_people_intents,
    scenario_sees_people_driven_comes_from_the_schedule,
    scenario_filter_subjects_only_bites_subject_facets,
    scenario_the_delivered_map_is_the_resolved_truth,
    scenario_the_editor_draws_from_one_meta,
    scenario_audience_fails_closed,
    scenario_sharing_reveals_to_exactly_those_people,
    scenario_a_closed_default_is_not_a_grant,
    scenario_scope_and_stage_compose,
]

if __name__ == "__main__":
    import traceback
    failed = 0
    for fn in SCENARIOS:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL  {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(SCENARIOS) - failed}/{len(SCENARIOS)} scenarios passed")
    raise SystemExit(1 if failed else 0)
