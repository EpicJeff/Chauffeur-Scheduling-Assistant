"""Route-kind facets on the auth table (family-network arc S7).

Every RULES row now carries an explicit fourth element: a facet from
scope.FACETS, or None for auth/infra/administration/shells and the welded
payloads whose enforcement lives in their assemblers. The load-bearing test
is the first one — a row that answers neither is a classification gap, and a
table that has to be remembered is a table that drifts.

The guard properties: the facet check runs only for a resolved MEMBER (a
panel is a place, Argyle is a robot); only a hard 'none' on a ROUTE-kind
facet can refuse, and only once enforcing — field/instance kinds are
recorded and never denied here, because a route refusal would break exactly
the instance grants §7 promises are additive.

Run from chauffeur/:  python tests/test_route_facets.py
"""
from harness import check  # noqa: F401  (isolates CHAUFFEUR_DATA_DIR)

from services import auth, scope, storage


def scenario_every_row_names_a_facet_or_says_none():
    bad = [(r[0], r[1]) for r in auth.RULES if len(r) != 4]
    check(not bad, f"rows with no explicit facet slot: {bad[:5]}")
    unknown = [(r[1], r[3]) for r in auth.RULES
               if r[3] is not None and r[3] not in scope.FACETS]
    check(not unknown, f"rows naming a facet scope has never heard of: {unknown}")


def scenario_every_app_route_resolves_a_facet_answer():
    """Through the wildcards, every real route must land on a classified row —
    which the tier test already guarantees; this pins the facet side."""
    import main
    for route in main.app.routes:
        path = getattr(route, 'path', None)
        methods = getattr(route, 'methods', None)
        if not path or not methods:
            continue
        for m in methods:
            if m in ('HEAD', 'OPTIONS'):
                continue
            # resolve_facet returning None is a valid answer (explicit
            # no-facet); what cannot happen is a row with a missing slot,
            # which scenario one refuses at the table itself.
            auth.resolve_facet(m, path)


def _seed():
    storage.members_table.truncate()
    storage.add_member({"id": "cuz", "name": "Cousin", "role": "guest"})
    storage.add_member({"id": "gran", "name": "Gran", "role": "adult",
                        "scope": {"preset": "keeping_up"}})
    return {mid: storage.create_member_token(mid) for mid in ("cuz", "gran")}


def scenario_reach_governs_route_kind_facets():
    tok = _seed()
    auth.reset_audit()
    hdr = {'x-member-token': tok['cuz']}
    check(auth.check_request('GET', '/api/pets', hdr, {}) is None,
          "a guest reaches pets — their one route-kind grant besides moments")
    check(auth.check_request('GET', '/api/meals/plan', hdr, {}) is None,
          "dark: a guest on the meals prefix is recorded, never refused")
    rows = auth.audit_report()['scope_would_deny']
    check(any(r['facet'] == 'meals.plan' and 'cuz' in r['saw'] for r in rows),
          f"…and the audit wrote it down: {rows}")

    real = storage.get_settings
    storage.get_settings = lambda: {"auth_enforce": True}
    try:
        refusal = auth.check_request('GET', '/api/meals/plan', hdr, {})
        check(refusal and refusal['status'] == 403
              and refusal.get('facet') == 'meals.plan',
              "enforcing: the same request is refused, naming the facet")
        check(auth.check_request('GET', '/api/pets', hdr, {}) is None,
              "…while the granted facet still answers")
    finally:
        storage.get_settings = real
        auth.reset_audit()


def scenario_field_kind_facets_are_recorded_never_denied():
    tok = _seed()
    auth.reset_audit()
    hdr = {'x-member-token': tok['gran']}   # keeping-up: carpool_contacts none
    real = storage.get_settings
    storage.get_settings = lambda: {"auth_enforce": True}
    try:
        check(auth.check_request('GET', '/api/assist-contacts', hdr, {}) is None,
              "a field-kind facet never refuses at the route, even enforcing — "
              "the assembler owns it (S9)")
    finally:
        storage.get_settings = real
    rows = auth.audit_report()['scope_would_deny']
    check(any(r['facet'] == 'schedule.carpool_contacts' for r in rows),
          "…but the audit still knows")
    auth.reset_audit()


def scenario_a_place_has_no_scope():
    _seed()
    auth.reset_audit()
    check(auth.check_request('GET', '/api/meals/plan', {}, {}) is None,
          "no member resolved: tiers govern, scope stays out of it")
    check(not auth.audit_report()['scope_would_deny'],
          "and nothing is recorded — a panel is a place, not a person")


SCENARIOS = [
    scenario_every_row_names_a_facet_or_says_none,
    scenario_every_app_route_resolves_a_facet_answer,
    scenario_reach_governs_route_kind_facets,
    scenario_field_kind_facets_are_recorded_never_denied,
    scenario_a_place_has_no_scope,
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
